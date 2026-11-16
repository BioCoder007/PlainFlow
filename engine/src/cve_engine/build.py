"""Directory -> RepoModel."""
from __future__ import annotations

from pathlib import Path

from .graph import resolve
from .loader import collect_python_files
from .models import RepoModel
from .parser import parse_file


def build_repo_model(root: Path) -> RepoModel:
    loaded = collect_python_files(Path(root))
    files = [parse_file(src.path, src.text) for src in loaded.files]
    return RepoModel(files=files, file_edges=resolve(files), skipped=loaded.skipped)
