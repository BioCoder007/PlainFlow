"""Session directories: one per ingested repo, deleted after 24 hours."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

SESSION_TTL_SECONDS = 24 * 60 * 60
_ID = re.compile(r"^[0-9a-f]{32}$")


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _dir(self, repo_id: str) -> Path | None:
        if not isinstance(repo_id, str) or not _ID.match(repo_id):
            return None
        return self._root / repo_id

    def create(self, now: float) -> str:
        repo_id = uuid.uuid4().hex
        path = self._root / repo_id
        (path / "src").mkdir(parents=True)
        (path / "created_at").write_text(repr(float(now)))
        return repo_id

    def exists(self, repo_id: str) -> bool:
        path = self._dir(repo_id)
        return path is not None and path.is_dir()

    def src_dir(self, repo_id: str) -> Path:
        path = self._dir(repo_id)
        if path is None:
            raise KeyError(repo_id)
        return path / "src"

    def save_model(self, repo_id: str, model: dict) -> None:
        path = self._dir(repo_id)
        if path is None:
            raise KeyError(repo_id)
        (path / "model.json").write_text(json.dumps(model))

    def load_model(self, repo_id: str) -> dict:
        path = self._dir(repo_id)
        if path is None or not (path / "model.json").is_file():
            raise KeyError(repo_id)
        return json.loads((path / "model.json").read_text())

    def delete(self, repo_id: str) -> None:
        path = self._dir(repo_id)
        if path is not None and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    def sweep(self, now: float) -> int:
        """Delete sessions created more than SESSION_TTL_SECONDS before now."""
        deleted = 0
        for path in self._root.iterdir():
            if not path.is_dir() or not _ID.match(path.name):
                continue
            try:
                created = float((path / "created_at").read_text())
            except (OSError, ValueError):
                created = float("-inf")
            if now - created > SESSION_TTL_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
                deleted += 1
        return deleted
