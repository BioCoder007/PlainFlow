import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.reviews import ReviewStore

MINI = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "mini_repo"
HEADERS = {"X-LLM-Provider": "local", "X-LLM-Model": "llama3", "X-LLM-Key": "secret-key",
           "X-LLM-Base-URL": "http://localhost:11434/v1"}
EXPLANATION = {"type": "explanation", "function_id": "app.py::main", "step_id": "s1",
               "depth": "developer", "explanation": "Cleans the text.", "verdict": "accepted"}
MISMATCH = {"type": "mismatch", "function_id": "app.py::main", "step_id": "s2",
            "intent": "returns a list", "reason": "Returns JSON text.", "verdict": "confirmed"}


def mini_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in sorted(MINI.rglob("*")):
            if p.is_file():
                z.write(p, "mini-main/" + p.relative_to(MINI).as_posix())
    return buf.getvalue()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def client(data_dir):
    with TestClient(create_app(data_dir, None)) as c:
        yield c


def upload(client):
    return client.post(
        "/api/repos", files={"file": ("mini.zip", mini_zip(), "application/zip")}).json()["repo_id"]


@pytest.fixture
def repo_id(client):
    return upload(client)


def test_review_store_upserts_by_key_and_survives_reopening(tmp_path):
    store = ReviewStore(tmp_path / "r.sqlite")
    store.save("k1", "h1", {"verdict": "accepted"})
    store.save("k1", "h1", {"verdict": "corrected"})
    store.save("k2", "h2", {"verdict": "confirmed"})
    again = ReviewStore(tmp_path / "r.sqlite")
    assert again.for_sources(["h1"]) == [{"verdict": "corrected"}]
    assert len(again.all()) == 2
    assert again.for_sources([]) == []


def test_saving_an_explanation_review_returns_the_full_record(client, repo_id):
    res = client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION, headers=HEADERS)
    assert res.status_code == 200
    rec = res.json()["review"]
    assert rec["file"] == "app.py" and rec["function"] == "main"
    assert rec["step"]["code"] == "    cleaned = util.clean(text)"
    assert rec["final_explanation"] == "Cleans the text."
    assert rec["model"] == {"provider": "local", "model": "llama3"}
    assert "secret-key" not in json.dumps(rec)


def test_reviews_are_listed_for_a_function_and_replaced_on_re_review(client, repo_id):
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION)
    client.post(f"/api/repos/{repo_id}/reviews", json={
        **EXPLANATION, "verdict": "corrected", "corrected": "Strips the text using util.clean."})
    client.post(f"/api/repos/{repo_id}/reviews", json=MISMATCH)
    reviews = client.get(f"/api/repos/{repo_id}/reviews",
                         params={"function_id": "app.py::main"}).json()["reviews"]
    assert sorted((r["type"], r["verdict"]) for r in reviews) == [
        ("explanation", "corrected"), ("mismatch", "confirmed")]
    assert reviews[0]["model"] is None or reviews[1]["model"] is None  # no model headers sent
    other = client.get(f"/api/repos/{repo_id}/reviews",
                       params={"function_id": "pkg/util.py::clean"}).json()["reviews"]
    assert other == []


def test_reviews_follow_the_code_into_a_new_upload_of_the_same_repo(client, repo_id):
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION)
    second = upload(client)
    reviews = client.get(f"/api/repos/{second}/reviews",
                         params={"function_id": "app.py::main"}).json()["reviews"]
    assert [r["verdict"] for r in reviews] == ["accepted"]


def test_reviews_are_not_deleted_by_the_24_hour_sweep(client, repo_id, data_dir):
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION)
    with TestClient(create_app(data_dir, None)) as later:  # startup sweep runs
        assert later.get("/api/reviews/summary").json() == {
            "total": 1, "explanations": 1, "mismatches": 0}


@pytest.mark.parametrize("body,status,detail", [
    ({**EXPLANATION, "step_id": "s9"}, 400, "Unknown step."),
    ({**EXPLANATION, "verdict": "corrected"}, 400, "Write the corrected explanation."),
    ({**EXPLANATION, "function_id": "nope"}, 404, "Function not found."),
    ({**MISMATCH, "verdict": "accepted"}, 400, "Unknown verdict."),
    ({**MISMATCH, "intent": ""}, 400, "There is no description to review against."),
])
def test_bad_reviews_are_refused_with_the_reason(client, repo_id, body, status, detail):
    res = client.post(f"/api/repos/{repo_id}/reviews", json=body)
    assert res.status_code == status and res.json() == {"detail": detail}


def test_review_with_an_unknown_type_is_422(client, repo_id):
    assert client.post(f"/api/repos/{repo_id}/reviews",
                       json={**EXPLANATION, "type": "other"}).status_code == 422


def test_summary_counts_reviews(client, repo_id):
    assert client.get("/api/reviews/summary").json() == {"total": 0, "explanations": 0, "mismatches": 0}
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION)
    client.post(f"/api/repos/{repo_id}/reviews", json=MISMATCH)
    assert client.get("/api/reviews/summary").json() == {"total": 2, "explanations": 1, "mismatches": 1}


def test_training_export_as_records(client, repo_id):
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION, headers=HEADERS)
    client.post(f"/api/repos/{repo_id}/reviews", json=MISMATCH)
    res = client.get("/api/export/training", params={"format": "records"})
    assert res.status_code == 200
    assert 'filename="training-records.jsonl"' in res.headers["content-disposition"]
    rows = [json.loads(line) for line in res.text.splitlines()]
    assert sorted(r["type"] for r in rows) == ["explanation", "mismatch"]
    assert all("function_source" in r and "step" in r for r in rows)
    assert "secret-key" not in res.text


def test_training_export_as_chat_examples(client, repo_id):
    client.post(f"/api/repos/{repo_id}/reviews", json={
        **EXPLANATION, "verdict": "corrected", "corrected": "Strips the text."})
    res = client.get("/api/export/training", params={"format": "chat"})
    assert 'filename="training-chat.jsonl"' in res.headers["content-disposition"]
    rows = [json.loads(line) for line in res.text.splitlines()]
    assert [m["role"] for m in rows[0]["messages"]] == ["system", "user", "assistant"]
    assert rows[0]["messages"][2]["content"] == "Strips the text."


def test_training_export_is_empty_without_reviews_and_rejects_unknown_formats(client):
    assert client.get("/api/export/training", params={"format": "records"}).text == ""
    assert client.get("/api/export/training", params={"format": "xml"}).status_code == 422


def test_onboarding_export_covers_only_this_repo(client, repo_id):
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION)
    client.post(f"/api/repos/{repo_id}/reviews", json=MISMATCH)
    res = client.get(f"/api/repos/{repo_id}/export/onboarding")
    assert res.status_code == 200
    assert 'filename="onboarding.md"' in res.headers["content-disposition"]
    assert "## app.py" in res.text and "### main (line 5)" in res.text
    assert "**Line 6.** Cleans the text." in res.text
    assert "**Reported issue at line 7.** Meant to: returns a list. Returns JSON text." in res.text

    other = client.post("/api/repos", files={"file": ("o.zip", _other_zip(), "application/zip")}).json()["repo_id"]
    assert "No reviewed explanations yet." in client.get(f"/api/repos/{other}/export/onboarding").text


def _other_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("solo.py", "def g():\n    return 1\n")
    return buf.getvalue()


# -- team reviews ------------------------------------------------------------------

def records_export(client):
    return client.get("/api/export/training", params={"format": "records"}).text


def import_file(client, text):
    return client.post("/api/reviews/import", files={"file": ("reviews.jsonl", text, "application/x-ndjson")})


def test_reviewer_name_from_the_request_is_saved_with_the_review(client, repo_id):
    rec = client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION,
                      headers={"X-Reviewer": "Sara%20Ahmed"}).json()["review"]
    assert rec["reviewer"] == "Sara Ahmed"
    anonymous = client.post(f"/api/repos/{repo_id}/reviews", json=MISMATCH).json()["review"]
    assert anonymous["reviewer"] is None


def test_non_latin_reviewer_names_survive(client, repo_id):
    rec = client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION,
                      headers={"X-Reviewer": "%D8%B9%D9%85%D8%A7%D9%86"}).json()["review"]
    assert rec["reviewer"] == "عمان"


def test_importing_a_teammates_export_adds_their_reviews(tmp_path):
    with TestClient(create_app(tmp_path / "sara", None)) as sara, \
            TestClient(create_app(tmp_path / "me", None)) as me:
        sara_repo = upload(sara)
        sara.post(f"/api/repos/{sara_repo}/reviews", json=EXPLANATION, headers={"X-Reviewer": "Sara"})
        sara.post(f"/api/repos/{sara_repo}/reviews", json=MISMATCH, headers={"X-Reviewer": "Sara"})

        res = import_file(me, records_export(sara))
        assert res.status_code == 200
        assert res.json() == {"added": 2, "updated": 0, "kept": 0, "conflicts": 0, "skipped": 0}
        my_repo = upload(me)
        mine = me.get(f"/api/repos/{my_repo}/reviews", params={"function_id": "app.py::main"}).json()["reviews"]
        assert sorted(r["reviewer"] for r in mine) == ["Sara", "Sara"]
        assert import_file(me, records_export(sara)).json() == {
            "added": 0, "updated": 0, "kept": 2, "conflicts": 0, "skipped": 0}


def test_import_reports_disagreements_and_keeps_the_newer_verdict(tmp_path, monkeypatch):
    from app import main as app_main
    clock = iter(["2026-11-14T10:00:00+00:00", "2026-11-14T12:00:00+00:00"])
    monkeypatch.setattr(app_main, "now_iso", lambda: next(clock))
    with TestClient(create_app(tmp_path / "sara", None)) as sara, \
            TestClient(create_app(tmp_path / "me", None)) as me:
        me.post(f"/api/repos/{upload(me)}/reviews", json=EXPLANATION, headers={"X-Reviewer": "Me"})
        sara.post(f"/api/repos/{upload(sara)}/reviews", headers={"X-Reviewer": "Sara"}, json={
            **EXPLANATION, "verdict": "corrected", "corrected": "Sara's wording."})
        assert import_file(me, records_export(sara)).json() == {
            "added": 0, "updated": 1, "kept": 0, "conflicts": 1, "skipped": 0}
        assert json.loads(records_export(me))["final_explanation"] == "Sara's wording."


def test_import_skips_damaged_lines_and_keeps_the_good_ones(client, repo_id):
    client.post(f"/api/repos/{repo_id}/reviews", json=EXPLANATION)
    good = records_export(client).strip()
    res = import_file(client, good + '\n{"type": "explanation"}\nnot json\n\n[1,2]\n')
    assert res.json() == {"added": 0, "updated": 0, "kept": 1, "conflicts": 0, "skipped": 3}


@pytest.mark.parametrize("text", ["", "hello\nworld\n", '{"messages": []}\n'])
def test_a_file_with_no_reviews_in_it_is_refused(client, text):
    res = import_file(client, text)
    assert res.status_code == 400
    assert res.json() == {"detail": "No reviews were found in this file. Use a full-records export."}
    assert client.get("/api/reviews/summary").json()["total"] == 0


def test_import_without_a_file_is_400(client):
    assert client.post("/api/reviews/import", json={}).status_code == 400
