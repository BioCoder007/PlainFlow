"""GitHub URL or zip -> Python source files in a session directory.

Nothing here executes repo content. Only .py entries are written to disk.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path, PurePosixPath

import httpx

MAX_ZIP_BYTES = 250 * 1024 * 1024
_GITHUB_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")
_UNSAFE_ZIP = "The zip file could not be read safely."
_UNREACHABLE = "GitHub could not be reached. Try again or upload a zip."


class IngestError(Exception):
    """A message that can be shown to the user."""


def parse_github_url(url: str) -> tuple[str, str]:
    match = _GITHUB_URL.match(url.strip()) if isinstance(url, str) else None
    if not match or set(match.group(1)) <= {"."} or set(match.group(2)) <= {"."}:
        raise IngestError(
            "Enter a public GitHub repository URL, like https://github.com/owner/repo.")
    return match.group(1), match.group(2)


async def fetch_github_zip(owner: str, repo: str, client: httpx.AsyncClient) -> bytes:
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball"
    chunks: list[bytes] = []
    size = 0
    try:
        async with client.stream(
                "GET", url, follow_redirects=True,
                headers={"User-Agent": "plainflow"}) as response:
            if response.status_code == 404:
                raise IngestError(
                    "Repository not found. Private repositories are not supported; "
                    "upload a zip instead.")
            if response.status_code in (403, 429):
                raise IngestError(
                    "GitHub refused the request, usually because of its rate limit. "
                    "Try again later or upload a zip.")
            if response.status_code != 200:
                raise IngestError(_UNREACHABLE)
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_ZIP_BYTES:
                    raise IngestError("Repository archive is larger than 250 MB.")
                chunks.append(chunk)
    except httpx.HTTPError as e:
        raise IngestError(_UNREACHABLE) from e
    return b"".join(chunks)


def extract_zip(data: bytes, dest: Path) -> None:
    """Write the zip's .py files under dest. All entries are checked before any write."""
    dest = Path(dest)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError) as e:
        raise IngestError(_UNSAFE_ZIP) from e

    with archive:
        entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        total = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if name.startswith("/") or ".." in path.parts or not path.parts:
                raise IngestError(_UNSAFE_ZIP)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink
                continue
            if "__MACOSX" in path.parts or path.name.startswith("._"):
                continue  # macOS Finder metadata, not part of the repo
            if path.suffix == ".py":
                # Only Python files are ever decompressed, so only they count.
                total += info.file_size
                if total > MAX_ZIP_BYTES:
                    raise IngestError("The Python files in this zip are larger than 250 MB.")
            entries.append((info, path))

        tops = {path.parts[0] for _, path in entries}
        strip = len(tops) == 1 and all(len(path.parts) > 1 for _, path in entries)

        written = 0
        root = dest.resolve()
        for info, path in entries:
            if path.suffix != ".py":
                continue
            rel = PurePosixPath(*path.parts[1:]) if strip else path
            target = (dest / rel).resolve()
            if root not in target.parents:
                raise IngestError(_UNSAFE_ZIP)
            try:
                with archive.open(info) as src:
                    content = src.read(MAX_ZIP_BYTES - written + 1)
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
                raise IngestError(_UNSAFE_ZIP) from e
            written += len(content)
            if written > MAX_ZIP_BYTES:  # header lied about the size
                raise IngestError(_UNSAFE_ZIP)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
