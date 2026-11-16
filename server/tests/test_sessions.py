from app.sessions import SESSION_TTL_SECONDS, SessionStore


def test_create_and_roundtrip_model(tmp_path):
    store = SessionStore(tmp_path)
    repo_id = store.create(now=0.0)
    assert len(repo_id) == 32 and store.exists(repo_id)
    assert store.src_dir(repo_id).is_dir()
    store.save_model(repo_id, {"files": []})
    assert store.load_model(repo_id) == {"files": []}


def test_ttl_is_24_hours():
    assert SESSION_TTL_SECONDS == 24 * 60 * 60


def test_sweep_deletes_only_sessions_older_than_24h(tmp_path):
    store = SessionStore(tmp_path)
    old = store.create(now=0.0)
    new = store.create(now=3600.0)
    assert store.sweep(now=24 * 3600 + 1) == 1
    assert not store.exists(old) and store.exists(new)


def test_delete_removes_the_session_directory(tmp_path):
    store = SessionStore(tmp_path)
    repo_id = store.create(now=0.0)
    store.delete(repo_id)
    assert not store.exists(repo_id)
    assert list(tmp_path.iterdir()) == []


def test_bad_repo_id_is_not_found(tmp_path):
    store = SessionStore(tmp_path)
    (tmp_path / "notes").mkdir()
    for bad in ["../etc", "notes", "", "A" * 32, "g" * 32]:
        assert store.exists(bad) is False


def test_delete_ignores_bad_ids(tmp_path):
    store = SessionStore(tmp_path / "data")
    (tmp_path / "keep").mkdir()
    store.delete("../keep")
    assert (tmp_path / "keep").is_dir()
