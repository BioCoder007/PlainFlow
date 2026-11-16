import os

import pytest

from cve_engine.loader import RepoTooLargeError, collect_python_files
from cve_engine.models import SkippedFile


def write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_collects_py_files_sorted_and_ignores_venv(tmp_path):
    write(tmp_path, "b.py", "x = 1")
    write(tmp_path, "pkg/a.py", "y = 2")
    write(tmp_path, "venv/lib/x.py")
    write(tmp_path, "notes.txt", "hi")
    result = collect_python_files(tmp_path)
    assert [f.path for f in result.files] == ["b.py", "pkg/a.py"]
    assert result.files[0].text == "x = 1"


def test_non_utf8_file_is_skipped_with_reason(tmp_path):
    (tmp_path / "bad.py").write_bytes(b"x = '\xff\xfe'")
    result = collect_python_files(tmp_path)
    assert result.files == []
    assert result.skipped == [SkippedFile("bad.py", "not UTF-8")]


def test_more_than_3000_files_raises(tmp_path):
    for i in range(3001):
        write(tmp_path, f"f{i}.py")
    with pytest.raises(RepoTooLargeError) as exc:
        collect_python_files(tmp_path)
    assert str(exc.value) == (
        "Repo exceeds the limit of 3000 Python files or 50 MB of Python source.")


def test_exactly_3000_files_is_allowed(tmp_path):
    for i in range(3000):
        write(tmp_path, f"f{i}.py")
    assert len(collect_python_files(tmp_path).files) == 3000


def test_more_than_50mb_raises(tmp_path):
    write(tmp_path, "big.py", "#" * (50 * 1024 * 1024 + 1))
    with pytest.raises(RepoTooLargeError):
        collect_python_files(tmp_path)


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside, "secret.py", "s = 1")
    root = tmp_path / "repo"
    root.mkdir()
    write(root, "a.py", "a = 1")
    os.symlink(outside / "secret.py", root / "link.py")
    os.symlink(outside, root / "linkdir")
    result = collect_python_files(root)
    assert [f.path for f in result.files] == ["a.py"]


def test_utf8_bom_is_stripped(tmp_path):
    (tmp_path / "bom.py").write_bytes(b"\xef\xbb\xbfdef f():\n    pass\n")
    result = collect_python_files(tmp_path)
    assert result.files[0].text == "def f():\n    pass\n"
