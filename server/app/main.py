"""HTTP API for PlainFlow."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from cve_engine import build_repo_model, check_intent, explain_function, explain_lines
from cve_engine.explain import PLACEHOLDER, PLACEHOLDER_LINE
from cve_engine.cache import ExplanationCache
from cve_engine.export import (
    chat_example, explanation_record, merge_reviews, mismatch_record, onboarding_markdown,
    record_key, source_hash, validate_record,
)
from cve_engine.intent import IntentError
from cve_engine.llm import LLMClient, LLMError, detect_local, detect_provider, list_models, make_client
from cve_engine.loader import RepoTooLargeError
from cve_engine.models import CallRef, FunctionNode, Step, StepEdge, function_source

from . import ingest
from .ingest import IngestError
from .reviews import ReviewStore
from .sessions import SESSION_TTL_SECONDS, SessionStore

SWEEP_INTERVAL_SECONDS = 60 * 60


class ExplainRequest(BaseModel):
    function_id: str
    depth: Literal["beginner", "developer"]


class ExplainLineRequest(BaseModel):
    function_id: str
    line: int
    end_line: int | None = None  # set to explain a range of lines as one piece of logic
    depth: Literal["beginner", "developer"]


class IntentRequest(BaseModel):
    function_id: str
    intent: str


NO_MODEL = "No AI model is set up. Choose one in Settings."


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewRequest(BaseModel):
    type: Literal["explanation", "mismatch"]
    function_id: str
    step_id: str
    verdict: str
    depth: str = ""          # explanation reviews
    explanation: str = ""
    corrected: str | None = None
    intent: str = ""         # mismatch reviews
    reason: str = ""


class _Recording:
    """Wraps a client and remembers a failure, so the API can report its reason."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.error: str | None = None

    def complete_json(self, system: str, user: str) -> dict:
        try:
            return self._inner.complete_json(system, user)
        except LLMError as e:
            self.error = str(e)
            raise


class _ScopedCache:
    """Keeps cached explanations separate per provider and model."""

    def __init__(self, cache: ExplanationCache, scope: str) -> None:
        self._cache = cache
        self._scope = scope

    def _key(self, key: str) -> str:
        return hashlib.sha256(f"{self._scope}\0{key}".encode()).hexdigest()

    def get(self, key: str):
        return self._cache.get(self._key(key))

    def put(self, key: str, value: dict, now: float) -> None:
        self._cache.put(self._key(key), value, now)


def create_app(data_dir: Path, llm: LLMClient | None,
               transport: httpx.AsyncBaseTransport | None = None,
               web_origin: str = "http://localhost:5173") -> FastAPI:
    store = SessionStore(Path(data_dir))
    cache = ExplanationCache(Path(data_dir) / "cache.sqlite")
    reviews = ReviewStore(Path(data_dir) / "reviews.sqlite")  # never swept

    def sweep() -> None:
        now = time.time()
        store.sweep(now)
        cache.sweep(now - SESSION_TTL_SECONDS)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        sweep()

        async def hourly() -> None:
            while True:
                await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
                await run_in_threadpool(sweep)

        task = asyncio.create_task(hourly())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="PlainFlow", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=[web_origin],
        allow_methods=["GET", "POST"], allow_headers=["*"])

    def choose_llm(request: Request) -> tuple[_Recording, str]:
        """The developer's own model from the request headers, else the server default.
        The key is used for this request only; it is never stored or logged."""
        provider = request.headers.get("x-llm-provider", "").strip()
        if provider:
            model = request.headers.get("x-llm-model", "")
            base_url = request.headers.get("x-llm-base-url", "")
            try:
                client = make_client(provider, model, request.headers.get("x-llm-key", ""), base_url)
            except LLMError as e:
                raise HTTPException(400, str(e))
            return _Recording(client), f"{provider}\0{model.strip()}\0{base_url.strip()}"
        if llm is None:
            raise HTTPException(400, NO_MODEL)
        return _Recording(llm), "server-default"

    def failed(recording: _Recording) -> HTTPException:
        return HTTPException(502, f"The AI model request failed: {recording.error}")

    def load_model(repo_id: str) -> dict:
        if not store.exists(repo_id):
            raise HTTPException(404, "Repository not found. It may have expired.")
        try:
            return store.load_model(repo_id)
        except KeyError:
            raise HTTPException(404, "Repository not found. It may have expired.")

    def read_source(repo_id: str, model: dict, path: str) -> str:
        # Only paths the parser produced are accepted; no path is built from raw input.
        if path not in {f["path"] for f in model["files"]}:
            raise HTTPException(404, "File not found.")
        return (store.src_dir(repo_id) / path).read_text(encoding="utf-8-sig")

    def to_node(fn: dict) -> FunctionNode:
        return FunctionNode(
            id=fn["id"], name=fn["name"], qualname=fn["qualname"],
            line_start=fn["line_start"], line_end=fn["line_end"],
            steps=[Step(**s) for s in fn["steps"]],
            edges=[StepEdge(**e) for e in fn["edges"]],
            calls=[CallRef(**c) for c in fn["calls"]])

    def locate(repo_id: str, model: dict, function_id: str) -> tuple[FunctionNode, str, str]:
        """The function, the path of its file and that file's text."""
        for f in model["files"]:
            for fn in f["functions"]:
                if fn["id"] == function_id:
                    return to_node(fn), f["path"], read_source(repo_id, model, f["path"])
        raise HTTPException(404, "Function not found.")

    def find_function(repo_id: str, model: dict, function_id: str) -> tuple[FunctionNode, str]:
        node, _, text = locate(repo_id, model, function_id)
        return node, function_source(text, node)

    def model_label(request: Request) -> dict | None:
        """Which model wrote the reviewed text. Never includes the key."""
        provider = request.headers.get("x-llm-provider", "").strip()
        if not provider:
            return None
        return {"provider": provider, "model": request.headers.get("x-llm-model", "").strip()}

    def jsonl(rows: list[dict], filename: str) -> PlainTextResponse:
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        return PlainTextResponse(body, media_type="application/x-ndjson", headers={
            "Content-Disposition": f'attachment; filename="{filename}"'})

    async def read_request_zip(request: Request) -> bytes:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                raise IngestError("Upload a zip file or enter a GitHub URL.")
            data = await upload.read(ingest.MAX_ZIP_BYTES + 1)
            if len(data) > ingest.MAX_ZIP_BYTES:
                raise IngestError("The zip file is larger than 250 MB.")
            return data
        try:
            body = await request.json()
        except Exception:
            body = None
        url = body.get("github_url") if isinstance(body, dict) else None
        if not isinstance(url, str):
            raise IngestError("Upload a zip file or enter a GitHub URL.")
        owner, repo = ingest.parse_github_url(url)
        async with httpx.AsyncClient(transport=transport, timeout=60) as client:
            return await ingest.fetch_github_zip(owner, repo, client)

    @app.post("/api/repos")
    async def create_repo(request: Request) -> dict:
        # Refuse oversized bodies from their declared length, before reading them.
        declared = request.headers.get("content-length", "")
        if not declared.isdigit():
            raise HTTPException(400, "The upload must declare its size.")
        if int(declared) > ingest.MAX_ZIP_BYTES + 1024 * 1024:
            raise HTTPException(400, "The upload is larger than 250 MB.")
        repo_id = store.create(time.time())
        try:
            data = await read_request_zip(request)
            await run_in_threadpool(ingest.extract_zip, data, store.src_dir(repo_id))
            model = await run_in_threadpool(build_repo_model, store.src_dir(repo_id))
            if not model.files:
                raise IngestError("No Python files were found in this repository.")
            payload = model.to_dict()
            store.save_model(repo_id, payload)
        except (IngestError, RepoTooLargeError) as e:
            store.delete(repo_id)
            raise HTTPException(400, str(e))
        except BaseException:
            store.delete(repo_id)
            raise
        return {"repo_id": repo_id, "model": payload}

    @app.get("/api/repos/{repo_id}")
    def get_repo(repo_id: str) -> dict:
        return {"repo_id": repo_id, "model": load_model(repo_id)}

    @app.get("/api/repos/{repo_id}/source")
    def get_source(repo_id: str, path: str = Query(...)) -> dict:
        model = load_model(repo_id)
        return {"path": path, "source": read_source(repo_id, model, path)}

    @app.post("/api/repos/{repo_id}/explain")
    def explain(repo_id: str, body: ExplainRequest, request: Request) -> dict:
        model = load_model(repo_id)
        fn, source = find_function(repo_id, model, body.function_id)
        client, scope = choose_llm(request)
        explanations = explain_function(
            fn, source, body.depth, client, _ScopedCache(cache, scope), time.time())
        # A long function is sent in parts: report a failure only when no part worked.
        if client.error and all(text == PLACEHOLDER for text in explanations.values()):
            raise failed(client)
        return {"explanations": explanations}

    @app.post("/api/repos/{repo_id}/explain-line")
    def explain_one_line(repo_id: str, body: ExplainLineRequest, request: Request) -> dict:
        model = load_model(repo_id)
        fn, source = find_function(repo_id, model, body.function_id)
        end = body.line if body.end_line is None else body.end_line
        if not fn.line_start <= body.line <= end <= fn.line_end:
            raise HTTPException(400, "The lines are not in this function.")
        client, scope = choose_llm(request)
        text = explain_lines(fn, source, body.line, end, body.depth, client,
                             _ScopedCache(cache, scope), time.time())
        if client.error and text == PLACEHOLDER_LINE:  # a usable plain-text answer is not a failure
            raise failed(client)
        return {"line": body.line, "end_line": end, "explanation": text}

    @app.post("/api/repos/{repo_id}/intent")
    def intent(repo_id: str, body: IntentRequest, request: Request) -> dict:
        model = load_model(repo_id)
        fn, source = find_function(repo_id, model, body.function_id)
        client, _ = choose_llm(request)
        try:
            mismatches = check_intent(fn, source, body.intent, client)
        except IntentError as e:
            if client.error:
                raise failed(client)
            raise HTTPException(400, str(e))
        return {"mismatches": [m.to_dict() for m in mismatches]}

    @app.post("/api/repos/{repo_id}/reviews")
    def save_review(repo_id: str, body: ReviewRequest, request: Request) -> dict:
        model = load_model(repo_id)
        fn, path, text = locate(repo_id, model, body.function_id)
        now = now_iso()
        # The name is percent-encoded by the web app so any script survives an HTTP header.
        reviewer = unquote(request.headers.get("x-reviewer", ""))
        try:
            if body.type == "explanation":
                record = explanation_record(
                    path, fn, text, body.step_id, body.depth, body.explanation,
                    body.verdict, body.corrected, model_label(request), now, reviewer)
            else:
                record = mismatch_record(
                    path, fn, text, body.step_id, body.intent, body.reason,
                    body.verdict, model_label(request), now, reviewer)
        except ValueError as e:
            raise HTTPException(400, str(e))
        reviews.save(record_key(record), source_hash(record["function_source"]), record)
        return {"review": record}

    @app.get("/api/repos/{repo_id}/reviews")
    def list_reviews(repo_id: str, function_id: str = Query(...)) -> dict:
        model = load_model(repo_id)
        _, source = find_function(repo_id, model, function_id)
        return {"reviews": reviews.for_sources([source_hash(source)])}

    @app.post("/api/reviews/import")
    async def import_reviews(request: Request) -> dict:
        """Merge a teammate's full-records export into this machine's reviews."""
        declared = request.headers.get("content-length", "")
        if not declared.isdigit() or int(declared) > ingest.MAX_ZIP_BYTES:
            raise HTTPException(400, "The file is larger than 250 MB.")
        upload = None
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            upload = (await request.form()).get("file")
        if upload is None or isinstance(upload, str):
            raise HTTPException(400, "Choose a reviews file to import.")
        text = (await upload.read()).decode("utf-8", errors="replace")

        incoming, skipped = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                incoming.append(validate_record(json.loads(line)))
            except ValueError:  # includes malformed JSON
                skipped += 1
        if not incoming:
            raise HTTPException(
                400, "No reviews were found in this file. Use a full-records export.")

        def merge() -> dict:
            before = reviews.all_by_key()
            result = merge_reviews(before, incoming)
            for key, record in result.records.items():
                if before.get(key) is not record:
                    reviews.save(key, source_hash(record["function_source"]), record)
            return {"added": result.added, "updated": result.updated, "kept": result.kept,
                    "conflicts": result.conflicts, "skipped": skipped}

        return await run_in_threadpool(merge)

    @app.get("/api/reviews/summary")
    def review_summary() -> dict:
        rows = reviews.all()
        explanations = sum(1 for r in rows if r["type"] == "explanation")
        return {"total": len(rows), "explanations": explanations,
                "mismatches": len(rows) - explanations}

    @app.get("/api/export/training")
    def export_training(format: Literal["records", "chat"] = Query(...)) -> PlainTextResponse:
        rows = reviews.all()
        if format == "chat":
            return jsonl([chat_example(r) for r in rows], "training-chat.jsonl")
        return jsonl(rows, "training-records.jsonl")

    @app.get("/api/repos/{repo_id}/export/onboarding")
    def export_onboarding(repo_id: str) -> PlainTextResponse:
        model = load_model(repo_id)
        hashes = []
        for f in model["files"]:
            if not f["functions"]:
                continue
            text = read_source(repo_id, model, f["path"])
            hashes += [source_hash(function_source(text, to_node(fn))) for fn in f["functions"]]
        paths = {f["path"] for f in model["files"]}
        records = [r for r in reviews.for_sources(sorted(set(hashes))) if r["file"] in paths]
        return PlainTextResponse(
            onboarding_markdown("This repository", records), media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="onboarding.md"'})

    @app.post("/api/llm/models")
    def llm_models(request: Request) -> dict:
        h = request.headers
        try:
            ids = list_models(h.get("x-llm-provider", "").strip(), h.get("x-llm-key", ""),
                              h.get("x-llm-base-url", ""), transport=transport)
        except LLMError as e:
            raise HTTPException(400, str(e))
        return {"models": ids}

    @app.post("/api/llm/detect")
    def llm_detect(request: Request) -> dict:
        """Which service an API key belongs to. The key comes in a header and is not stored."""
        try:
            return detect_provider(request.headers.get("x-llm-key", ""), transport=transport)
        except LLMError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/llm/detect-local")
    def llm_detect_local() -> dict:
        try:
            return detect_local(transport=transport)
        except LLMError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/llm/test")
    def test_llm(request: Request) -> dict:
        client, _ = choose_llm(request)
        try:
            client.complete_json(
                'Reply with this JSON object and nothing else: {"ok": true}', "ping")
        except LLMError:
            raise failed(client)
        return {"ok": True}

    static_dir = Path(__file__).parent / "static"
    if (static_dir / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles
        from starlette.exceptions import HTTPException as StarletteHTTPException

        @app.api_route("/api/{rest:path}", methods=["GET", "POST"], include_in_schema=False)
        async def api_not_found(rest: str):
            raise HTTPException(status_code=404, detail="Not found.")

        class WebApp(StaticFiles):
            """Serves the built web app. Any unknown path (such as /repo/<id>/file/a.py after
            a page refresh) gets index.html, so the app's own router can show it."""

            async def get_response(self, path, scope):
                try:
                    response = await super().get_response(path, scope)
                except StarletteHTTPException as e:
                    if e.status_code != 404:
                        raise
                    return await super().get_response("index.html", scope)
                if response.status_code == 404:
                    return await super().get_response("index.html", scope)
                return response

        # Registered last so every /api route wins over the web app.
        app.mount("/", WebApp(directory=static_dir, html=True), name="web")
    return app


def _app_from_env() -> FastAPI:
    """Optional server-wide default model, used when a request names none."""
    provider = os.environ.get("CVE_PROVIDER", "anthropic")
    model = os.environ.get("CVE_MODEL", "")
    api_key = os.environ.get("CVE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    llm: LLMClient | None = None
    if model:
        try:
            llm = make_client(provider, model, api_key, os.environ.get("CVE_BASE_URL"))
        except LLMError:
            llm = None
    return create_app(
        Path(os.environ.get("CVE_DATA_DIR", "./data")), llm,
        web_origin=os.environ.get("CVE_WEB_ORIGIN", "http://localhost:5173"))


def __getattr__(name: str):
    # `uvicorn app.main:app` builds the app on first access, so importing this
    # module (as the tests do) creates no data directory.
    if name == "app":
        globals()["app"] = _app_from_env()
        return globals()["app"]
    raise AttributeError(name)
