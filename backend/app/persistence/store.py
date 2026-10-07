"""SQLite scenario store. Scenarios are stored as validated JSON documents."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.domain.models import Scenario
from app.samples.catalog import all_samples

DEFAULT_DB = os.environ.get("OES_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "scenarios.db"))


class ScenarioStore:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""CREATE TABLE IF NOT EXISTS scenarios (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, is_sample INTEGER NOT NULL DEFAULT 0,
            doc TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def seed_samples(self, force: bool = False) -> None:
        for sc in all_samples():
            if force or self.get(sc.id) is None:
                self._upsert(sc, created=None)

    def list(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, is_sample, doc, updated_at FROM scenarios ORDER BY is_sample DESC, name").fetchall()
        out = []
        for r in rows:
            doc = json.loads(r["doc"])
            out.append({"id": r["id"], "name": r["name"], "is_sample": bool(r["is_sample"]),
                        "business_process": doc.get("business_process", ""), "updated_at": r["updated_at"],
                        "has_benchmark": doc.get("benchmark") is not None})
        return out

    def get(self, sid: str) -> Scenario | None:
        r = self._conn.execute("SELECT doc FROM scenarios WHERE id = ?", (sid,)).fetchone()
        return Scenario.model_validate_json(r["doc"]) if r else None

    def create(self, sc: Scenario) -> Scenario:
        sc = sc.model_copy(deep=True)
        sc.id = sc.id if sc.id and self.get(sc.id) is None else f"sc-{uuid.uuid4().hex[:10]}"
        self._upsert(sc, created=self._now())
        return sc

    def update(self, sid: str, sc: Scenario) -> Scenario:
        sc = sc.model_copy(deep=True)
        sc.id = sid
        self._upsert(sc, created=None)
        return sc

    def delete(self, sid: str) -> bool:
        cur = self._conn.execute("DELETE FROM scenarios WHERE id = ?", (sid,))
        self._conn.commit()
        return cur.rowcount > 0

    def clone(self, sid: str, name: str | None = None) -> Scenario | None:
        src = self.get(sid)
        if src is None:
            return None
        copy = src.model_copy(deep=True)
        copy.id = None
        copy.name = name or f"{src.name} (copy)"
        # A clone is the user's own working scenario; it keeps the frozen benchmark for reference.
        copy.is_sample = False
        return self.create(copy)

    def _upsert(self, sc: Scenario, created: str | None) -> None:
        now = self._now()
        doc = sc.model_dump_json()
        existing = self._conn.execute("SELECT created_at FROM scenarios WHERE id = ?", (sc.id,)).fetchone()
        created_at = existing["created_at"] if existing else (created or now)
        self._conn.execute(
            "INSERT OR REPLACE INTO scenarios (id, name, is_sample, doc, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (sc.id, sc.name, int(sc.is_sample), doc, created_at, now))
        self._conn.commit()
