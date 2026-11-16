import io
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from cve_engine import loader
from cve_engine.llm import LLMError

MINI = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "mini_repo"


class FakeLLM:
    def __init__(self):
        self.reply = {}
        self.error = False
        self.calls = []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise LLMError("boom")
        return self.reply


def zip_dir(root, prefix="mini-main/"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, prefix + p.relative_to(root).as_posix())
    return buf.getvalue()


def zip_of(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def client(data_dir, llm):
    def github(request):
        if request.url.path == "/repos/owner/mini/zipball":
            return httpx.Response(200, content=zip_dir(MINI))
        return httpx.Response(404)

    app = create_app(data_dir, llm, transport=httpx.MockTransport(github))
    with TestClient(app) as c:
        yield c


def upload(client, data=None):
    data = zip_dir(MINI) if data is None else data
    return client.post("/api/repos", files={"file": ("repo.zip", data, "application/zip")})


@pytest.fixture
def repo_id(client):
    return upload(client).json()["repo_id"]


def session_dirs(data_dir):
    return [p for p in data_dir.iterdir() if p.is_dir()]


def test_upload_zip_returns_model(client):
    res = upload(client)
    assert res.status_code == 200
    body = res.json()
    assert len(body["repo_id"]) == 32
    assert [f["path"] for f in body["model"]["files"]] == [
        "app.py", "broken.py", "pkg/__init__.py", "pkg/util.py"]


def test_github_url_returns_model(client):
    res = client.post("/api/repos", json={"github_url": "https://github.com/owner/mini"})
    assert res.status_code == 200
    assert len(res.json()["model"]["files"]) == 4


def test_github_repo_not_found_is_400_with_message(client, data_dir):
    res = client.post("/api/repos", json={"github_url": "https://github.com/owner/nope"})
    assert res.status_code == 400
    assert res.json()["detail"].startswith("Repository not found.")
    assert session_dirs(data_dir) == []


def test_bad_github_url_is_400(client):
    res = client.post("/api/repos", json={"github_url": "https://evil.com/x/y"})
    assert res.status_code == 400
    assert "public GitHub repository URL" in res.json()["detail"]


def test_request_with_neither_url_nor_file_is_400(client):
    assert client.post("/api/repos", json={}).status_code == 400
    assert client.post("/api/repos", content=b"junk").status_code == 400


def test_get_repo_returns_same_model(client):
    created = upload(client).json()
    res = client.get(f"/api/repos/{created['repo_id']}")
    assert res.status_code == 200 and res.json() == created


def test_source_returns_file_text(client, repo_id):
    res = client.get(f"/api/repos/{repo_id}/source", params={"path": "pkg/util.py"})
    assert res.status_code == 200
    assert res.json() == {"path": "pkg/util.py", "source": (MINI / "pkg" / "util.py").read_text()}


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "nope.py", "../created_at"])
def test_source_rejects_path_not_in_model(client, repo_id, path):
    res = client.get(f"/api/repos/{repo_id}/source", params={"path": path})
    assert res.status_code == 404


def test_explain_returns_one_entry_per_step(client, repo_id, llm):
    llm.reply = {"steps": {"s1": "Cleans the text.", "s2": "Returns it as JSON."}}
    res = client.post(f"/api/repos/{repo_id}/explain",
                      json={"function_id": "app.py::main", "depth": "developer"})
    assert res.status_code == 200
    assert res.json() == {"explanations": {
        "s1": "Cleans the text.", "s2": "Returns it as JSON."}}
    assert "5 | def main(text):" in llm.calls[0][1]


def test_explain_unknown_function_404(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/explain",
                      json={"function_id": "app.py::nope", "depth": "developer"})
    assert res.status_code == 404


def test_explain_rejects_unknown_depth(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/explain",
                      json={"function_id": "app.py::main", "depth": "expert"})
    assert res.status_code == 422


def test_intent_returns_mismatches(client, repo_id, llm):
    llm.reply = {"mismatches": [{"step_id": "s2", "reason": "Returns JSON, not a list."}]}
    res = client.post(f"/api/repos/{repo_id}/intent",
                      json={"function_id": "app.py::main", "intent": "returns a list"})
    assert res.status_code == 200
    assert res.json() == {"mismatches": [
        {"step_id": "s2", "reason": "Returns JSON, not a list."}]}


def test_intent_blank_is_400_with_message(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/intent",
                      json={"function_id": "app.py::main", "intent": "  "})
    assert res.status_code == 400
    assert res.json() == {"detail": "Describe what the code should do."}


def test_intent_unknown_function_404(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/intent",
                      json={"function_id": "nope", "intent": "x"})
    assert res.status_code == 404


def test_zip_without_python_files_is_400(client, data_dir):
    res = upload(client, zip_of({"README.md": "hi"}))
    assert res.status_code == 400
    assert res.json() == {"detail": "No Python files were found in this repository."}
    assert session_dirs(data_dir) == []


def test_oversized_repo_is_400_with_cap_message(client, monkeypatch, data_dir):
    monkeypatch.setattr(loader, "MAX_FILES", 1)
    res = upload(client)
    assert res.status_code == 400
    assert "3000 Python files" in res.json()["detail"]
    assert session_dirs(data_dir) == []


def test_failed_ingest_leaves_no_session_directory(client, data_dir):
    res = upload(client, b"not a zip")
    assert res.status_code == 400
    assert res.json() == {"detail": "The zip file could not be read safely."}
    assert session_dirs(data_dir) == []


@pytest.mark.parametrize("bad", ["0" * 32, "nope", "..%2F..%2Fetc"])
def test_unknown_repo_id_404(client, bad):
    assert client.get(f"/api/repos/{bad}").status_code == 404
    assert client.get(f"/api/repos/{bad}/source", params={"path": "a.py"}).status_code == 404
    assert client.post(f"/api/repos/{bad}/explain",
                       json={"function_id": "x", "depth": "developer"}).status_code == 404


def test_startup_sweeps_expired_sessions(data_dir, llm):
    from app.sessions import SessionStore
    old = SessionStore(data_dir).create(now=0.0)
    with TestClient(create_app(data_dir, llm)) as c:
        assert c.get(f"/api/repos/{old}").status_code == 404
    assert not (data_dir / old).exists()


# -- final review I2, I6 --------------------------------------------------------

def test_source_of_a_bom_file_has_no_bom(client):
    res = upload(client, zip_of({"bom.py": b"\xef\xbb\xbfdef f():\n    pass\n"}))
    repo_id = res.json()["repo_id"]
    assert res.json()["model"]["files"][0]["parse_error"] is None
    src = client.get(f"/api/repos/{repo_id}/source", params={"path": "bom.py"}).json()["source"]
    assert src == "def f():\n    pass\n"


def test_oversized_request_is_rejected_from_its_declared_length(client, data_dir):
    res = client.post("/api/repos", content=b"x",
                      headers={"content-type": "application/json",
                               "content-length": str(300 * 1024 * 1024)})
    assert res.status_code == 400
    assert res.json() == {"detail": "The upload is larger than 250 MB."}
    assert session_dirs(data_dir) == []


def test_request_without_a_declared_length_is_rejected(client, data_dir):
    def chunks():
        yield b'{"github_url": "https://github.com/owner/mini"}'

    res = client.post("/api/repos", content=chunks(), headers={"content-type": "application/json"})
    assert res.status_code == 400
    assert session_dirs(data_dir) == []


# -- model choice -----------------------------------------------------------------
from app import main as app_main

HEADERS = {"X-LLM-Provider": "openai", "X-LLM-Model": "gpt-x", "X-LLM-Key": "sk-user"}
EXPLAIN = {"function_id": "app.py::main", "depth": "developer"}


@pytest.fixture
def chosen(monkeypatch):
    """Records what make_client is asked for and hands back a fake per (provider, model)."""
    made = []
    fakes = {}

    def fake_make_client(provider, model, api_key="", base_url=None):
        made.append((provider, model, api_key, base_url))
        if provider == "bad":
            raise LLMError("Unknown provider.")
        fake = fakes.setdefault((provider, model), FakeLLM())
        fake.reply = {"steps": {"s1": f"{model} one", "s2": f"{model} two"}, "ok": True}
        return fake

    monkeypatch.setattr(app_main, "make_client", fake_make_client)
    return made, fakes


@pytest.fixture
def bare_client(data_dir):
    """A server with no default model configured."""
    with TestClient(create_app(data_dir, None)) as c:
        yield c


def test_explain_uses_the_model_named_in_the_request(client, repo_id, llm, chosen):
    made, _ = chosen
    res = client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN, headers=HEADERS)
    assert res.json() == {"explanations": {"s1": "gpt-x one", "s2": "gpt-x two"}}
    assert made == [("openai", "gpt-x", "sk-user", "")]
    assert llm.calls == []  # the server default was not used


def test_endpoint_address_header_is_passed_through(client, repo_id, chosen):
    made, _ = chosen
    client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN, headers={
        "X-LLM-Provider": "other", "X-LLM-Model": "llama", "X-LLM-Base-URL": "http://localhost:11434/v1"})
    assert made == [("other", "llama", "", "http://localhost:11434/v1")]


def test_explanations_are_cached_per_provider_and_model(client, repo_id, chosen):
    _, fakes = chosen
    first = client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN, headers=HEADERS).json()
    again = client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN, headers=HEADERS).json()
    other = client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN,
                        headers={**HEADERS, "X-LLM-Model": "gpt-y"}).json()
    assert first == again and len(fakes[("openai", "gpt-x")].calls) == 1
    assert other == {"explanations": {"s1": "gpt-y one", "s2": "gpt-y two"}}


def test_no_model_configured_is_400_pointing_to_settings(bare_client):
    repo_id = upload(bare_client).json()["repo_id"]
    res = bare_client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN)
    assert res.status_code == 400
    assert res.json() == {"detail": "No AI model is set up. Choose one in Settings."}
    res = bare_client.post(f"/api/repos/{repo_id}/intent",
                           json={"function_id": "app.py::main", "intent": "x"})
    assert res.status_code == 400
    assert res.json() == {"detail": "No AI model is set up. Choose one in Settings."}


def test_incomplete_settings_are_400_with_the_reason(client, repo_id, chosen):
    res = client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN,
                      headers={"X-LLM-Provider": "bad", "X-LLM-Model": "m"})
    assert res.status_code == 400 and res.json() == {"detail": "Unknown provider."}


def test_provider_failure_during_explain_is_502_with_the_reason(client, repo_id, llm):
    llm.error = True
    res = client.post(f"/api/repos/{repo_id}/explain", json=EXPLAIN)
    assert res.status_code == 502
    assert res.json() == {"detail": "The AI model request failed: boom"}


def test_provider_failure_during_intent_is_502_with_the_reason(client, repo_id, llm):
    llm.error = True
    res = client.post(f"/api/repos/{repo_id}/intent",
                      json={"function_id": "app.py::main", "intent": "x"})
    assert res.status_code == 502
    assert res.json() == {"detail": "The AI model request failed: boom"}


def test_connection_test_succeeds_with_a_working_model(client, chosen):
    res = client.post("/api/llm/test", headers=HEADERS)
    assert res.status_code == 200 and res.json() == {"ok": True}


def test_connection_test_reports_the_provider_error(client, llm):
    llm.error = True
    res = client.post("/api/llm/test")
    assert res.status_code == 502
    assert res.json() == {"detail": "The AI model request failed: boom"}


def test_connection_test_without_any_model_is_400(bare_client):
    res = bare_client.post("/api/llm/test")
    assert res.status_code == 400
    assert res.json() == {"detail": "No AI model is set up. Choose one in Settings."}


def test_llm_models_without_a_provider_is_400(client):
    res = client.post("/api/llm/models")
    assert res.status_code == 400


def test_explain_line_returns_one_explanation(client, repo_id, llm):
    llm.reply = {"explanation": "Calls util.clean with text. Stores the result in cleaned."}
    res = client.post(f"/api/repos/{repo_id}/explain-line",
                      json={"function_id": "app.py::main", "line": 6, "depth": "developer"})
    assert res.status_code == 200
    assert res.json() == {"line": 6, "end_line": 6, "explanation": "Calls util.clean with text. Stores the result in cleaned."}
    assert ">> 6 |     cleaned = util.clean(text)" in llm.calls[0][1]


def test_explain_line_outside_function_is_400(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/explain-line",
                      json={"function_id": "app.py::main", "line": 1, "depth": "developer"})
    assert res.status_code == 400


def test_explain_line_model_failure_is_502(client, repo_id, llm):
    llm.error = True
    res = client.post(f"/api/repos/{repo_id}/explain-line",
                      json={"function_id": "app.py::main", "line": 6, "depth": "developer"})
    assert res.status_code == 502


def test_built_web_app_serves_deep_links(tmp_path, monkeypatch, llm):
    import app.main as m
    static = Path(m.__file__).parent / "static"
    if not (static / "index.html").is_file():
        pytest.skip("web app not built")
    from fastapi.testclient import TestClient
    c = TestClient(m.create_app(tmp_path / "d", llm))
    assert c.get("/repo/abc/file/a.py").status_code == 200
    assert "<!doctype html>" in c.get("/repo/abc/file/a.py").text.lower()
    assert c.get("/api/nope").status_code == 404


def test_explain_range_of_lines(client, repo_id, llm):
    llm.reply = {"explanation": "Cleans `text`. Returns it."}
    res = client.post(f"/api/repos/{repo_id}/explain-line",
                      json={"function_id": "app.py::main", "line": 5, "end_line": 7, "depth": "developer"})
    assert res.status_code == 200 and res.json()["end_line"] == 7
    assert "as a whole" in llm.calls[0][0]


def test_explain_range_backwards_is_400(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/explain-line",
                      json={"function_id": "app.py::main", "line": 7, "end_line": 5, "depth": "developer"})
    assert res.status_code == 400


def test_explain_line_uses_a_plain_text_answer(client, repo_id, llm):
    from cve_engine.llm import NotJSON

    def plain(system, user):
        raise NotJSON("Calls `util.clean` with `text`.")
    llm.complete_json = plain
    res = client.post(f"/api/repos/{repo_id}/explain-line",
                      json={"function_id": "app.py::main", "line": 6, "depth": "developer"})
    assert res.status_code == 200
    assert res.json()["explanation"] == "Calls `util.clean` with `text`."


def test_llm_detect_needs_a_key(client):
    res = client.post("/api/llm/detect")
    assert res.status_code == 400 and "Enter an API key" in res.json()["detail"]
