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

CREATE TABLE IF NOT EXISTS journal_entries (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  id      TEXT NOT NULL UNIQUE,
  ts      REAL NOT NULL,
  kind    TEXT NOT NULL CHECK (kind IN ('trade_locked','session_closed','manifest_outcome')),
  payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal_entries
BEGIN SELECT RAISE(ABORT, 'journal_entries is append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal_entries
BEGIN SELECT RAISE(ABORT, 'journal_entries is append-only'); END;

CREATE TABLE IF NOT EXISTS setup_journal (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  id       TEXT NOT NULL UNIQUE,
  ts       REAL NOT NULL,
  kind     TEXT NOT NULL CHECK (kind IN ('setup_armed','setup_outcome')),
  setup_id TEXT NOT NULL,
  payload  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS setup_journal_by_setup ON setup_journal (setup_id);
CREATE TRIGGER IF NOT EXISTS setup_journal_no_update BEFORE UPDATE ON setup_journal
BEGIN SELECT RAISE(ABORT, 'setup_journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS setup_journal_no_delete BEFORE DELETE ON setup_journal
BEGIN SELECT RAISE(ABORT, 'setup_journal is append-only'); END;

CREATE TABLE IF NOT EXISTS setting_events (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  id       TEXT NOT NULL UNIQUE,
  ts       REAL NOT NULL,
  action   TEXT NOT NULL CHECK (action IN ('set','revert','preset_save','preset_apply','import')),
  key      TEXT,
  scope    TEXT,
  value    TEXT,
  operator TEXT,
  name     TEXT
);
CREATE TRIGGER IF NOT EXISTS settings_no_update BEFORE UPDATE ON setting_events
BEGIN SELECT RAISE(ABORT, 'setting_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS settings_no_delete BEFORE DELETE ON setting_events
BEGIN SELECT RAISE(ABORT, 'setting_events is append-only'); END;

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
        self._migrate_journal_kinds()
        self._conn.executescript(_DDL)
        self._conn.commit()

    def _migrate_journal_kinds(self) -> None:
        """Élargit la contrainte CHECK de `journal_entries` (kind `manifest_outcome`, D-045) sur
        une base EXISTANTE. SQLite ne sait pas modifier un CHECK : reconstruction de table à
        l'identique, événements copiés VERBATIM (seq/id/ts/kind/payload) — l'append-only (§2.5)
        porte sur les événements, jamais sur le DDL. Les triggers anti UPDATE/DELETE sont
        recréés immédiatement après par `_DDL`. No-op sur base neuve ou déjà migrée."""
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='journal_entries'"
        ).fetchone()
        if row is None or "manifest_outcome" in (row["sql"] or ""):
            return
        self._conn.executescript("""
        DROP TRIGGER IF EXISTS journal_no_update;
        DROP TRIGGER IF EXISTS journal_no_delete;
        ALTER TABLE journal_entries RENAME TO journal_entries_old;
        CREATE TABLE journal_entries (
          seq     INTEGER PRIMARY KEY AUTOINCREMENT,
          id      TEXT NOT NULL UNIQUE,
          ts      REAL NOT NULL,
          kind    TEXT NOT NULL CHECK (kind IN ('trade_locked','session_closed','manifest_outcome')),
          payload TEXT NOT NULL
        );
        INSERT INTO journal_entries (seq, id, ts, kind, payload)
          SELECT seq, id, ts, kind, payload FROM journal_entries_old;
        DROP TABLE journal_entries_old;
        """)

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

    def append_journal(self, kind: str, payload: dict[str, Any],
                       ts: Optional[float] = None) -> dict[str, Any]:
        """Journal de trading (reference/journal, D-022) — locked entries are as
        immutable as decisions: same append-only guards, same grammar.
        `manifest_outcome` (D-045): issue d'une alerte TradeManifest (ACK / REJECT_USER /
        TIMEOUT) avec temps de réaction humain — même contrat append-only."""
        if kind not in ("trade_locked", "session_closed", "manifest_outcome"):
            raise ValueError(f"unknown journal kind: {kind}")
        entry = {"id": str(uuid.uuid4()), "ts": ts if ts is not None else time.time(),
                 "kind": kind, **payload}
        with self._lock:
            self._conn.execute(
                "INSERT INTO journal_entries (id, ts, kind, payload) VALUES (?, ?, ?, ?)",
                (entry["id"], entry["ts"], kind, json.dumps(payload, ensure_ascii=False)))
            self._conn.commit()
        return entry

    def journal_entries(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT seq, id, ts, kind, payload FROM journal_entries"
        params: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY seq ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [{"seq": r["seq"], "id": r["id"], "ts": r["ts"], "kind": r["kind"],
                 **json.loads(r["payload"])} for r in rows]

    def append_setup(self, kind: str, setup_id: str, payload: dict[str, Any],
                     ts: Optional[float] = None) -> dict[str, Any]:
        """Journal des setups (P2, D-082) — même grammaire et mêmes garde-fous que le Decision
        Log : `setup_armed` est immuable, `setup_outcome` est un event ULTÉRIEUR qui le
        RÉFÉRENCE par `setup_id`. Aucun chemin ne met à jour un armement : le corriger
        signifierait réécrire l'histoire de la calibration."""
        if kind not in ("setup_armed", "setup_outcome"):
            raise ValueError(f"unknown setup journal kind: {kind}")
        if not setup_id:
            raise ValueError("setup_id est obligatoire — sans lui l'issue ne référence rien")
        entry = {"id": str(uuid.uuid4()), "ts": ts if ts is not None else time.time(),
                 "kind": kind, "setup_id": setup_id, **payload}
        with self._lock:
            self._conn.execute(
                "INSERT INTO setup_journal (id, ts, kind, setup_id, payload) VALUES (?,?,?,?,?)",
                (entry["id"], entry["ts"], kind, setup_id,
                 json.dumps(payload, ensure_ascii=False)))
            self._conn.commit()
        return entry

    def setup_entries(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        """Rejeu ordonné du journal. `seq` (et non `ts`) porte l'ordre : deux events peuvent
        partager un horodatage, jamais un numéro de séquence."""
        query = "SELECT seq, id, ts, kind, setup_id, payload FROM setup_journal"
        params: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY seq ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [{"seq": r["seq"], "id": r["id"], "ts": r["ts"], "kind": r["kind"],
                 "setup_id": r["setup_id"], **json.loads(r["payload"])} for r in rows]

    def save_snapshot(self, payload: dict[str, Any]) -> str:
        snap_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute("INSERT INTO snapshots (id, ts, payload) VALUES (?, ?, ?)",
                               (snap_id, time.time(), json.dumps(payload, ensure_ascii=False)))
            self._conn.commit()
        return snap_id

    def append_setting(self, action: str, key: Optional[str] = None,
                       scope: Optional[str] = None, value: Any = None,
                       operator: Optional[str] = None, name: Optional[str] = None,
                       ts: Optional[float] = None) -> dict[str, Any]:
        """Settings change log — same event-sourced grammar as decisions: a change is an
        immutable event, current config is a projection, history comes for free."""
        if action not in ("set", "revert", "preset_save", "preset_apply", "import"):
            raise ValueError(f"unknown setting action: {action}")
        event = {"id": str(uuid.uuid4()), "ts": ts if ts is not None else time.time(),
                 "action": action, "key": key, "scope": scope, "value": value,
                 "operator": operator, "name": name}
        with self._lock:
            self._conn.execute(
                "INSERT INTO setting_events (id, ts, action, key, scope, value, operator, name)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event["id"], event["ts"], action, key, scope,
                 json.dumps(value, ensure_ascii=False), operator, name))
            self._conn.commit()
        return event

    def setting_events(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, id, ts, action, key, scope, value, operator, name"
                " FROM setting_events ORDER BY seq ASC").fetchall()
        return [{"seq": r["seq"], "id": r["id"], "ts": r["ts"], "action": r["action"],
                 "key": r["key"], "scope": r["scope"],
                 "value": json.loads(r["value"]) if r["value"] is not None else None,
                 "operator": r["operator"], "name": r["name"]} for r in rows]

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
