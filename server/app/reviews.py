"""Human reviews of explanations and mismatches. Kept until the team removes
the file: unlike uploaded code, these are the team's own work product."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class ReviewStore:
    def __init__(self, path: Path) -> None:
        self._path = str(path)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reviews ("
                "key TEXT PRIMARY KEY, source_hash TEXT NOT NULL, record TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS reviews_source ON reviews (source_hash)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def save(self, key: str, source_hash: str, record: dict) -> None:
        """Reviewing the same step again replaces the earlier verdict."""
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO reviews (key, source_hash, record) VALUES (?, ?, ?)",
                (key, source_hash, json.dumps(record)))

    def for_sources(self, source_hashes: list[str]) -> list[dict]:
        if not source_hashes:
            return []
        found: list[dict] = []
        with self._connect() as db:
            for i in range(0, len(source_hashes), 500):  # stay under sqlite's variable limit
                chunk = source_hashes[i:i + 500]
                marks = ",".join("?" * len(chunk))
                rows = db.execute(
                    f"SELECT record FROM reviews WHERE source_hash IN ({marks}) ORDER BY rowid",
                    chunk).fetchall()
                found += [json.loads(r[0]) for r in rows]
        return found

    def all(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT record FROM reviews ORDER BY rowid").fetchall()
        return [json.loads(r[0]) for r in rows]

    def all_by_key(self) -> dict[str, dict]:
        with self._connect() as db:
            rows = db.execute("SELECT key, record FROM reviews ORDER BY rowid").fetchall()
        return {key: json.loads(record) for key, record in rows}
