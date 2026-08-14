"""Invariants durs du terminal (CLAUDE §2) — le filet de sécurité de Loop 1/2/3.

Chaque test fige un comportement DÉJÀ vérifié end-to-end : verrous serveur des
paramètres 2 étages (D-023/D-024), projections RECAP honnêtes, Mode Live fail-closed,
event store append-only. Ordre d'exécution séquentiel dans le module (stores singletons).
"""
import sqlite3

import pytest

from app import live_mode, recap, settings
from app.event_store import get_store
from app.schema import ContextSchema

EXTRAS_EMPTY = {"rms": None}


# ---------- settings — deux étages, verrous serveur (D-023) ----------

def test_settings_default_then_global_override():
    assert settings.value("risk.max_r_per_session") == 3.0
    settings.set_value("risk.max_r_per_session", 4.0, None, "SONY")
    assert settings.value("risk.max_r_per_session") == 4.0


def test_settings_specific_is_reduce_only():
    with pytest.raises(settings.SettingsError) as exc:
        settings.set_value("risk.max_r_per_session", 5.0, "SVS", "SONY")
    assert exc.value.status == 422
    settings.set_value("risk.max_r_per_session", 2.0, "SVS", "SONY")
    assert settings.value("risk.max_r_per_session", "SVS") == 2.0
    assert settings.value("risk.max_r_per_session", "MEAN_REVERSION") == 4.0  # hérite


def test_settings_guard_requires_explicit_ack():
    with pytest.raises(settings.SettingsError) as exc:
        settings.set_value("decision.arm_threshold", 40, None, "SONY")
    assert exc.value.status == 428
    settings.set_value("decision.arm_threshold", 40, None, "SONY", ack_guard=True)
    assert settings.value("decision.arm_threshold") == 40.0


def test_settings_authority_is_locked():
    with pytest.raises(settings.SettingsError) as exc:
        settings.set_value("signal.weight_macro", 10, None, "SONY")
    assert exc.value.status == 409


def test_settings_live_mode_is_read_only_unless_unlocked():
    with pytest.raises(settings.SettingsError) as exc:
        settings.check_live_lock("LIVE", False)
    assert exc.value.status == 423
    settings.check_live_lock("LIVE", True)   # déverrouillage explicite
    settings.check_live_lock("PRE_SESSION", False)


def test_settings_revert_and_preset_roundtrip():
    settings.save_preset("test preset", "SONY")
    settings.revert("decision.arm_threshold", None, "SONY")
    assert settings.value("decision.arm_threshold") == 60.0
    settings.apply_preset("TEST PRESET", "SONY")
    assert settings.value("decision.arm_threshold") == 40.0
    settings.import_overrides(settings.export_overrides(), "SONY")
    payload = settings.payload(get_store())
    assert any(p["name"] == "TEST PRESET" for p in payload["presets"])


# ---------- event store — append-only structurel (CLAUDE §2.5) ----------

def test_setting_events_are_append_only_at_sql_level():
    store = get_store()
    # Peupler d'abord : un trigger BEFORE UPDATE/DELETE ne se déclenche que s'il y a
    # des lignes à toucher.
    store.append("DecisionEvent", {"operator": "SONY", "decision": "NO_GO",
                                   "reason": "test"})
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE setting_events SET key='x'")
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM events")


# ---------- recap — projection honnête (D-023) ----------

def test_recap_empty_schema_is_fail_closed():
    r = recap.recap_payload(get_store(), ContextSchema(), EXTRAS_EMPTY, "session")
    assert r["pnl"]["n_trades"] == 0
    assert r["weather"]["level"] == "ROUGE"          # données absentes → jamais VERT
    assert r["risk"]["risk_clock_trades_left"] is None  # pas de perte → pas de rythme inventé
    assert any(m["id"] == "phase0" and m["state"] == "BLOQUÉ" for m in r["modules"])


def test_recap_pnl_and_risk_clock_from_journal():
    store = get_store()
    store.append_journal("trade_locked", {"strategy_id": "SVS", "resultat_r": 1.5,
                                          "direction": "LONG"})
    store.append_journal("trade_locked", {"strategy_id": "MEAN_REVERSION", "resultat_r": -1.0,
                                          "direction": "SHORT"})
    r = recap.recap_payload(store, ContextSchema(), EXTRAS_EMPTY, "week")
    assert r["pnl"]["r_total"] == 0.5 and r["pnl"]["wins"] == 1
    assert r["pnl"]["drawdown_r"] == 1.0
    assert r["risk"]["consumed_r"] == 1.0
    # max_r résolu = 4.0 (override global du test settings) → 3.0 restant / perte moy 1.0
    assert r["risk"]["risk_clock_trades_left"] == 3
    assert len(r["strategy_split"]) == 2


# ---------- Mode Live — advisory déterministe fail-closed (CLAUDE §2.8) ----------

def test_live_reading_fail_closed_on_absent_data():
    reading = live_mode.market_reading(ContextSchema(), EXTRAS_EMPTY, "PRE_SESSION")
    assert reading["level"] == "ROUGE"
    assert "absentes" in reading["message"]


def test_live_answer_refuses_out_of_scope_and_stays_advisory():
    a = live_mode.answer("dois-je acheter des actions Apple ?",
                         ContextSchema(), EXTRAS_EMPTY, "PRE_SESSION")
    assert a["advisory"] is True
    assert a["engine"] == "rules_deterministic"
    assert "périmètre" in a["answer"]


def test_live_answer_fail_closed_without_data():
    a = live_mode.answer("Le contexte est-il favorable ?",
                         ContextSchema(), EXTRAS_EMPTY, "PRE_SESSION")
    assert "absentes" in a["answer"]


def test_la_migration_des_types_d_events_ne_PERD_aucun_event(tmp_path):
    """D-095 élargit la contrainte CHECK d'`events` sur une base EXISTANTE — la seule opération
    du dépôt qui recrée la table du journal. Une migration qui perd un event perdrait la
    calibration : elle se teste, elle ne se suppose pas."""
    import json
    import sqlite3

    from app.event_store import EventStore

    chemin = str(tmp_path / "ancien.db")
    # Base à l'ANCIEN schéma (trois types), avec ses triggers append-only.
    conn = sqlite3.connect(chemin)
    conn.executescript("""
    CREATE TABLE events (
      seq     INTEGER PRIMARY KEY AUTOINCREMENT,
      id      TEXT NOT NULL UNIQUE,
      ts      REAL NOT NULL,
      type    TEXT NOT NULL CHECK (type IN ('DecisionEvent','OutcomeEvent','ReconEvent')),
      payload TEXT NOT NULL
    );
    CREATE TRIGGER events_no_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
    CREATE TRIGGER events_no_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
    """)
    attendus = [(1, "id-1", 100.5, "DecisionEvent", json.dumps({"decision": "GO"})),
                (2, "id-2", 200.5, "OutcomeEvent", json.dumps({"outcome": "LOSS"}))]
    conn.executemany("INSERT INTO events (seq, id, ts, type, payload) VALUES (?,?,?,?,?)", attendus)
    conn.commit()
    conn.close()

    store = EventStore(chemin)          # ouvre → migre

    # 1. Rien n'a été perdu ni renuméroté.
    survivants = store.events()
    assert [e["id"] for e in survivants] == ["id-1", "id-2"]
    assert [e["ts"] for e in survivants] == [100.5, 200.5]
    assert survivants[0]["decision"] == "GO" and survivants[1]["outcome"] == "LOSS"

    # 2. Le nouveau type passe.
    store.append("SetupRejectedEvent", {"setup_id": "s1", "reason": "F6_COOLDOWN_ACTIVE"})
    assert len(store.events("SetupRejectedEvent")) == 1

    # 3. Les triggers append-only ont bien été RECRÉÉS — c'est le vrai risque de la manœuvre.
    for sql in ("UPDATE events SET ts = 0 WHERE id = 'id-1'",
                "DELETE FROM events WHERE id = 'id-1'"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store._conn.execute(sql)

    # 4. Idempotent : rouvrir ne remigre pas et ne casse rien.
    again = EventStore(chemin)
    assert len(again.events()) == 3
