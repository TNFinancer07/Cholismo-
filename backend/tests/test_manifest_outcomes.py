"""Devil D-045 — journalisation des issues de TradeManifest avec temps de réaction.

Approche figée AVANT implémentation :
- `POST /manifests/outcome` : événement APPEND-ONLY (journal, kind `manifest_outcome`) portant
  l'issue `ACK` / `REJECT_USER` / `TIMEOUT` et `reaction_time_ms` (affichage → action humaine) ;
- `reaction_time_ms` OBLIGATOIRE (fini, ≥ 0, borné au TTL affiché) pour ACK/REJECT_USER,
  INTERDIT (null) pour TIMEOUT — pas d'action humaine, on n'invente pas une latence (§3) ;
- `GET /manifests/outcomes` : projection post-session — événements + stats (médianes par issue).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)


def _body(**over) -> dict:
    base = {"manifest_id": "f8dc6f97ce888c0b", "instrument": "MNQ", "direction": "SELL",
            "outcome": "ACK", "reaction_time_ms": 742.0, "time_to_live_ms": 3000,
            "operator": "SONY"}
    base.update(over)
    return base


def test_ack_est_journalise_avec_temps_de_reaction():
    r = _client.post("/manifests/outcome", json=_body())
    assert r.status_code == 200
    got = _client.get("/manifests/outcomes").json()
    mine = [e for e in got["events"] if e["manifest_id"] == "f8dc6f97ce888c0b"]
    assert mine and mine[0]["outcome"] == "ACK" and mine[0]["reaction_time_ms"] == 742.0


def test_timeout_sans_temps_de_reaction():
    r = _client.post("/manifests/outcome",
                     json=_body(manifest_id="to1", outcome="TIMEOUT", reaction_time_ms=None))
    assert r.status_code == 200
    got = _client.get("/manifests/outcomes").json()
    mine = [e for e in got["events"] if e["manifest_id"] == "to1"]
    assert mine and mine[0]["reaction_time_ms"] is None


def test_timeout_avec_temps_de_reaction_refuse():
    # Pas d'action humaine sur un TIMEOUT — une latence fournie serait une fabrication (§3).
    r = _client.post("/manifests/outcome",
                     json=_body(outcome="TIMEOUT", reaction_time_ms=1200.0))
    assert r.status_code == 422


def test_ack_sans_temps_de_reaction_refuse():
    for bad in (None,):
        r = _client.post("/manifests/outcome", json=_body(reaction_time_ms=bad))
        assert r.status_code == 422
    r = _client.post("/manifests/outcome", json={**_body()} | {})
    assert r.status_code == 200  # contrôle : le corps nominal passe toujours


def test_temps_de_reaction_aberrant_refuse():
    r = _client.post("/manifests/outcome", json=_body(reaction_time_ms=-1.0))
    assert r.status_code == 422
    # au-delà du TTL affiché : l'action n'a pas pu avoir lieu après la mort du ticket
    r = _client.post("/manifests/outcome", json=_body(reaction_time_ms=3001.0))
    assert r.status_code == 422
    # inf ne peut pas voyager en JSON (refusé à l'encodage côté client ; JSON.stringify → null),
    # mais un appelant Python interne pourrait le produire : la garde du MODÈLE le refuse.
    import pytest as _pytest
    from pydantic import ValidationError

    from app.api import ManifestOutcomeBody
    for bad in (float("inf"), float("nan")):
        with _pytest.raises(ValidationError):
            ManifestOutcomeBody(**_body(reaction_time_ms=bad))


def test_issue_inconnue_refusee():
    for bad in ("EXECUTED", "", "ack"):
        r = _client.post("/manifests/outcome", json=_body(outcome=bad))
        assert r.status_code == 422, bad


def test_direction_et_champs_stricts():
    assert _client.post("/manifests/outcome", json=_body(direction="FLAT")).status_code == 422
    assert _client.post("/manifests/outcome", json=_body(manifest_id="")).status_code == 422
    assert _client.post("/manifests/outcome", json=_body(time_to_live_ms=0)).status_code == 422


def test_projection_stats_medianes_par_issue():
    for i, (out, ms) in enumerate([("ACK", 500.0), ("ACK", 700.0), ("ACK", 900.0),
                                   ("REJECT_USER", 300.0), ("TIMEOUT", None)]):
        r = _client.post("/manifests/outcome",
                         json=_body(manifest_id=f"st{i}", outcome=out, reaction_time_ms=ms))
        assert r.status_code == 200
    s = _client.get("/manifests/outcomes").json()["stats"]
    assert s["n"] >= 5
    assert s["ack"] >= 3 and s["reject_user"] >= 1 and s["timeout"] >= 1
    assert s["ack_median_reaction_ms"] is not None    # médiane RÉELLE, jamais sur du vide
    assert 500.0 <= s["ack_median_reaction_ms"] <= 900.0


def test_migration_base_existante_preserve_les_evenements():
    """Une base d'AVANT D-045 (CHECK sans `manifest_outcome`) est migrée à l'ouverture :
    événements copiés verbatim, nouveau kind accepté, triggers append-only toujours armés."""
    import os
    import sqlite3
    import tempfile

    import pytest as _pytest

    from app.event_store import EventStore

    path = os.path.join(tempfile.mkdtemp(prefix="cholismo-mig-"), "events.db")
    old = sqlite3.connect(path)
    old.executescript("""
    CREATE TABLE journal_entries (
      seq     INTEGER PRIMARY KEY AUTOINCREMENT,
      id      TEXT NOT NULL UNIQUE,
      ts      REAL NOT NULL,
      kind    TEXT NOT NULL CHECK (kind IN ('trade_locked','session_closed')),
      payload TEXT NOT NULL
    );
    INSERT INTO journal_entries (id, ts, kind, payload)
      VALUES ('legacy-1', 1000.0, 'trade_locked', '{"note":"pre-D-045"}');
    """)
    old.commit()
    old.close()

    store = EventStore(path=path)
    entries = store.journal_entries()
    assert [(e["id"], e["kind"]) for e in entries] == [("legacy-1", "trade_locked")]
    assert entries[0]["seq"] == 1                       # seq verbatim, pas renuméroté
    store.append_journal("manifest_outcome", {"manifest_id": "m1", "outcome": "ACK",
                                              "reaction_time_ms": 500.0})
    assert len(store.journal_entries()) == 2
    with _pytest.raises(sqlite3.IntegrityError):        # append-only toujours en vigueur
        store._conn.execute("UPDATE journal_entries SET ts = 0 WHERE id = 'legacy-1'")


def test_projection_vide_fail_closed():
    # Sur un store vierge la projection dit « rien », jamais un zéro déguisé en mesure.
    from app.projections import manifest_outcomes

    class _Empty:
        def journal_entries(self, kind=None):
            return []
    p = manifest_outcomes(_Empty())
    assert p["events"] == []
    assert p["stats"]["n"] == 0 and p["stats"]["ack_median_reaction_ms"] is None
