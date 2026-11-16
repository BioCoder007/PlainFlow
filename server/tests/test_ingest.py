import asyncio
import io
import zipfile

import httpx
import pytest

from app import ingest
from app.ingest import IngestError, extract_zip, fetch_github_zip, parse_github_url


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize("url", [
    "https://github.com/owner/repo", "https://github.com/owner/repo/",
    "https://github.com/owner/repo.git", "  https://github.com/owner/repo  "])
def test_github_url_accepted(url):
    assert parse_github_url(url) == ("owner", "repo")


@pytest.mark.parametrize("url", [
    "http://github.com/o/r", "https://gitlab.com/o/r", "https://github.com/o",
    "https://github.com/o/r/tree/main", "https://github.com@evil.com/o/r",
    "file:///etc/passwd", "https://github.com/o/r?x=1", "https://github.com/../r",
    "https://github.com/o/..", ""])
def test_github_url_rejected(url):
    with pytest.raises(IngestError) as exc:
        parse_github_url(url)
    assert str(exc.value) == (
        "Enter a public GitHub repository URL, like https://github.com/owner/repo.")


def test_extract_writes_only_py_and_strips_single_top_dir(tmp_path):
    data = make_zip({"repo-main/a.py": "a = 1", "repo-main/pkg/b.py": "b = 2",
                     "repo-main/README.md": "hi", "repo-main/img.png": b"\x89PNG"})
    extract_zip(data, tmp_path)
    found = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert found == ["a.py", "pkg/b.py"]
    assert (tmp_path / "a.py").read_text() == "a = 1"


def test_extract_keeps_layout_when_there_is_no_single_top_dir(tmp_path):
    extract_zip(make_zip({"a.py": "", "pkg/b.py": ""}), tmp_path)
    assert (tmp_path / "a.py").is_file() and (tmp_path / "pkg" / "b.py").is_file()


@pytest.mark.parametrize("name", ["../../evil.py", "/abs/evil.py", "repo/../../evil.py"])
def test_zip_slip_entry_rejected_and_nothing_written_outside(tmp_path, name):
    dest = tmp_path / "session" / "src"
    dest.mkdir(parents=True)
    with pytest.raises(IngestError) as exc:
        extract_zip(make_zip({"ok.py": "x = 1", name: "evil = 1"}), dest)
    assert str(exc.value) == "The zip file could not be read safely."
    assert not list(tmp_path.rglob("evil.py"))
    assert list(dest.iterdir()) == []


def test_zip_over_uncompressed_limit_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ZIP_BYTES", 100)
    with pytest.raises(IngestError):
        extract_zip(make_zip({"a.py": "#" * 60, "b.py": "#" * 60}), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_non_python_entries_do_not_count_toward_the_limit(tmp_path, monkeypatch):
    # final review I5: data files are never extracted, so they must not block a repo
    monkeypatch.setattr(ingest, "MAX_ZIP_BYTES", 100)
    extract_zip(make_zip({"a.py": "x", "big.bin": "0" * 500}), tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.py"]


def test_oversized_python_content_message_states_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ZIP_BYTES", 100)
    with pytest.raises(IngestError) as exc:
        extract_zip(make_zip({"a.py": "#" * 60, "b.py": "#" * 60}), tmp_path)
    assert str(exc.value) == "The Python files in this zip are larger than 250 MB."


def test_macos_zip_metadata_is_ignored(tmp_path):
    # final review I3: Finder adds __MACOSX/ and ._ files beside the real folder
    data = make_zip({"proj/main.py": "import pkg.a", "proj/pkg/a.py": "x = 1",
                     "__MACOSX/proj/._main.py": b"\x00\x05\x16\x07", "proj/._junk.py": b"\x00"})
    extract_zip(data, tmp_path)
    found = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert found == ["main.py", "pkg/a.py"]


def test_not_a_zip_rejected(tmp_path):
    with pytest.raises(IngestError) as exc:
        extract_zip(b"definitely not a zip", tmp_path)
    assert str(exc.value) == "The zip file could not be read safely."


def test_symlink_entries_are_skipped(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.py", "a = 1")
        info = zipfile.ZipInfo("link.py")
        info.external_attr = 0o120777 << 16  # symlink
        z.writestr(info, "/etc/passwd")
    extract_zip(buf.getvalue(), tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.py"]


def fetch(handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_github_zip("owner", "repo", client)
    return asyncio.run(run())


def test_github_fetch_returns_archive_bytes():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=b"zipbytes")

    assert fetch(handler) == b"zipbytes"
    assert seen == ["https://api.github.com/repos/owner/repo/zipball"]


def test_github_404_message():
    with pytest.raises(IngestError) as exc:
        fetch(lambda request: httpx.Response(404))
    assert str(exc.value) == (
        "Repository not found. Private repositories are not supported; upload a zip instead.")


def test_github_other_failure_message():
    with pytest.raises(IngestError) as exc:
        fetch(lambda request: httpx.Response(500))
    assert str(exc.value) == "GitHub could not be reached. Try again or upload a zip."


def test_github_network_error_message():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(IngestError) as exc:
        fetch(handler)
    assert str(exc.value) == "GitHub could not be reached. Try again or upload a zip."


def test_github_archive_over_limit_rejected(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ZIP_BYTES", 10)
    with pytest.raises(IngestError) as exc:
        fetch(lambda request: httpx.Response(200, content=b"x" * 11))
    assert str(exc.value) == "Repository archive is larger than 250 MB."


@pytest.mark.parametrize("status", [403, 429])
def test_github_rate_limit_message(status):
    with pytest.raises(IngestError) as exc:
        fetch(lambda request: httpx.Response(status))
    assert str(exc.value) == (
        "GitHub refused the request, usually because of its rate limit. "
        "Try again later or upload a zip.")
