from pathlib import Path

import pytest

from cve_engine import build_repo_model
from cve_engine.loader import RepoTooLargeError

FIXTURES = Path(__file__).parent / "fixtures"


def test_broken_file_does_not_stop_the_build():
    model = build_repo_model(FIXTURES / "mini_repo")
    broken = next(f for f in model.files if f.path == "broken.py")
    assert broken.parse_error is not None
    assert len(model.files) == 4


def test_skipped_files_are_reported(tmp_path):
    (tmp_path / "bad.py").write_bytes(b"\xff")
    model = build_repo_model(tmp_path)
    assert [(s.path, s.reason) for s in model.skipped] == [("bad.py", "not UTF-8")]


def test_too_large_repo_raises(tmp_path):
    for i in range(3001):
        (tmp_path / f"f{i}.py").write_text("")
    with pytest.raises(RepoTooLargeError):
        build_repo_model(tmp_path)
