"""Decision Log — event-sourced, append-only (AUTORITÉ PRD §Zone D, CLAUDE §2.5).

Murex/Calypso grammar: a decision is an immutable event; the outcome is a LATER event that
references it; current state is a projection replaying events. Append-only is enforced by
the engine itself (SQLite BEFORE UPDATE/DELETE triggers -> RAISE ABORT), not by convention
(D-003). No code path performs UPDATE or DELETE — and none could.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

from . import config

EVENT_TYPES = ("DecisionEvent", "OutcomeEvent", "ReconEvent")

_DDL = """
CREATE TABLE IF NOT EXISTS events (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  id      TEXT NOT NULL UNIQUE,
  ts      REAL NOT NULL,
  type    TEXT NOT NULL CHECK (type IN ('DecisionEvent','OutcomeEvent','ReconEvent')),
  payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;

CREATE TABLE IF NOT EXISTS snapshots (
  id      TEXT PRIMARY KEY,
  ts      REAL NOT NULL,
  payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS snapshots_no_update BEFORE UPDATE ON snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots is append-only'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_no_delete BEFORE DELETE ON snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots is append-only'); END;

CREATE TABLE IF NOT EXISTS ai_calls (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         REAL NOT NULL,
  provider   TEXT NOT NULL,
  purpose    TEXT NOT NULL,
  status     TEXT NOT NULL,
  latency_ms REAL,
  cost_usd   REAL,
  detail     TEXT
);
"""


class EventStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or config.EVENT_DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    # -- writes (INSERT only) --

    def append(self, event_type: str, payload: dict[str, Any], ts: Optional[float] = None) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {event_type}")
        event = {"id": str(uuid.uuid4()), "ts": ts if ts is not None else time.time(),
                 "type": event_type, **payload}
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (id, ts, type, payload) VALUES (?, ?, ?, ?)",
                (event["id"], event["ts"], event_type, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
        return event

    def save_snapshot(self, payload: dict[str, Any]) -> str:
        snap_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute("INSERT INTO snapshots (id, ts, payload) VALUES (?, ?, ?)",
                               (snap_id, time.time(), json.dumps(payload, ensure_ascii=False)))
            self._conn.commit()
        return snap_id

    def log_ai_call(self, provider: str, purpose: str, status: str,
                    latency_ms: Optional[float] = None, cost_usd: Optional[float] = None,
                    detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ai_calls (ts, provider, purpose, status, latency_ms, cost_usd, detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), provider, purpose, status, latency_ms, cost_usd, detail))
            self._conn.commit()

    # -- reads --

    def events(self, event_type: Optional[str] = None, since_seq: int = 0) -> list[dict[str, Any]]:
        query = "SELECT seq, id, ts, type, payload FROM events WHERE seq > ?"
        params: list[Any] = [since_seq]
        if event_type:
            query += " AND type = ?"
            params.append(event_type)
        query += " ORDER BY seq ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        out = []
        for row in rows:
            payload = json.loads(row["payload"])
            out.append({"seq": row["seq"], "id": row["id"], "ts": row["ts"],
                        "type": row["type"], **payload})
        return out

    def snapshot(self, snap_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM snapshots WHERE id = ?", (snap_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def ai_calls(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, provider, purpose, status, latency_ms, cost_usd, detail"
                " FROM ai_calls ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


_store: Optional[EventStore] = None


def get_store() -> EventStore:
    global _store
    if _store is None:
        _store = EventStore()
    return _store
