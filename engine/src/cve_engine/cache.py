"""Explanation cache in sqlite, with expiry so derived text is not kept."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class ExplanationCache:
    def __init__(self, path: Path) -> None:
        self._path = str(path)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS explanations ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def get(self, key: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM explanations WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict[str, str], now: float) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO explanations (key, value, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), now))

    def sweep(self, older_than: float) -> int:
        with self._connect() as db:
            cur = db.execute(
                "DELETE FROM explanations WHERE created_at < ?", (older_than,))
            return cur.rowcount
