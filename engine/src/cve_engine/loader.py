"""Find and read the Python files of a repo. Files are read as text, never run."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import SkippedFile

MAX_FILES = 3000
MAX_BYTES = 50 * 1024 * 1024
IGNORED_DIRS = {
    ".git", "venv", ".venv", "env", "node_modules", "__pycache__",
    "site-packages", "build", "dist",
}


class RepoTooLargeError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Repo exceeds the limit of 3000 Python files or 50 MB of Python source.")


@dataclass
class SourceFile:
    path: str
    text: str


@dataclass
class LoadResult:
    files: list[SourceFile] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)


def collect_python_files(root: Path) -> LoadResult:
    root = Path(root)
    found: list[tuple[str, Path]] = []
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS and not os.path.islink(os.path.join(dirpath, d))
        ]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = Path(dirpath) / name
            if full.is_symlink() or not full.is_file():
                continue
            total_bytes += full.stat().st_size
            found.append((full.relative_to(root).as_posix(), full))
            if len(found) > MAX_FILES or total_bytes > MAX_BYTES:
                raise RepoTooLargeError()

    result = LoadResult()
    for rel, full in sorted(found):
        try:
            text = full.read_bytes().decode("utf-8-sig")  # tolerate a BOM
        except UnicodeDecodeError:
            result.skipped.append(SkippedFile(rel, "not UTF-8"))
            continue
        result.files.append(SourceFile(rel, text))
    return result
