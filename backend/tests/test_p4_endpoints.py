"""Feature — endpoints du dashboard v17 (P4, D-088).

Ce que le dashboard consomme en plus du canal SSE `options` : le **blotter** (projection du
journal des setups), la **matrice de calibration**, et l'**instantané** de santé des boucles.

Le canal SSE pousse la santé sur CHANGEMENT d'état (D-075) : sans instantané REST, un client qui
vient de se connecter resterait vide jusqu'au prochain changement — c'est-à-dire potentiellement
plusieurs minutes sur un système sain.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router
from app.event_store import EventStore
from app.setup_journal import SetupJournal


@pytest.fixture
def client(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "p4.db")
    store = EventStore(path)
    monkeypatch.setattr("app.api.SetupJournal", lambda: SetupJournal(store))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), SetupJournal(store)


def _armed(setup_id, ts, **over):
    base = {"setup_id": setup_id, "armed_ts_ms": ts, "instrument": "MES", "side": "LONG",
            "entry_price": 5000.0, "o1_status": "PASS", "o2_status": "PASS",
            "o3_status": "PASS", "o4_status": "O4_SOURCE_UNCONFIRMED", "o5_status": "PASS"}
    base.update(over)
    return base


def test_le_blotter_rend_les_setups_PLUS_RECENT_en_tete(client):
    api, journal = client
    journal.record_armed(_armed("s-1", 1_000.0))
    journal.record_armed(_armed("s-2", 3_000.0))
    journal.record_armed(_armed("s-3", 2_000.0))
    body = api.get("/setups").json()
    assert body["count"] == 3
    assert [s["setup_id"] for s in body["setups"]] == ["s-2", "s-3", "s-1"]


def test_le_blotter_porte_l_issue_quand_elle_existe(client):
    api, journal = client
    journal.record_armed(_armed("s-1", 1_000.0))
    journal.record_outcome({"setup_id": "s-1", "status": "NO_FILL"})
    row = api.get("/setups").json()["setups"][0]
    assert row["outcome_status"] == "NO_FILL"


def test_un_setup_sans_issue_reste_PENDING_dans_le_blotter(client):
    api, journal = client
    journal.record_armed(_armed("s-1", 1_000.0))
    assert api.get("/setups").json()["setups"][0]["outcome_status"] == "PENDING"


def test_le_blotter_VIDE_ne_leve_pas(client):
    api, _ = client
    assert api.get("/setups").json() == {"count": 0, "setups": []}


def test_la_limite_du_blotter_est_BORNEE(client):
    api, journal = client
    for i in range(30):
        journal.record_armed(_armed(f"s-{i}", float(i)))
    assert api.get("/setups?limit=5").json()["count"] == 5
    assert api.get("/setups?limit=99999").json()["count"] == 30      # borne haute appliquée
    assert api.get("/setups?limit=0").json()["count"] == 1           # borne basse appliquée


def test_la_matrice_est_servie_et_ne_CONCLUT_rien(client):
    api, journal = client
    journal.record_armed(_armed("s-1", 1_000.0))
    journal.record_outcome({"setup_id": "s-1", "status": "WIN", "pnl_usd": 6.25})
    body = api.get("/setups/calibration").json()
    assert set(body["by_gate"]) == {"o1", "o2", "o3", "o4", "o5"}
    # Un seul trade : sous l'échantillon minimal, aucun taux n'est publié.
    assert body["by_gate"]["o1"]["PASS"]["win_rate"] is None
    assert body["by_gate"]["o1"]["PASS"]["status"] == "INSUFFICIENT_DATA"
    assert body["result_visible"] is False


def test_le_seuil_d_echantillon_de_la_matrice_est_reglable_et_borne(client):
    api, journal = client
    journal.record_armed(_armed("s-1", 1_000.0))
    journal.record_outcome({"setup_id": "s-1", "status": "WIN", "pnl_usd": 6.25})
    body = api.get("/setups/calibration?min_sample=1").json()
    assert body["by_gate"]["o1"]["PASS"]["win_rate"] == pytest.approx(1.0)
    assert api.get("/setups/calibration?min_sample=0").json()["min_cell_sample"] == 1


def test_la_sante_des_boucles_est_servie_en_INSTANTANE():
    """Le canal SSE ne pousse que sur CHANGEMENT d'état : sans cet instantané, un client qui
    vient de se connecter resterait vide jusqu'au prochain changement."""
    from app.loops.registry import default_specs
    from app.loops.supervisor import LoopSupervisor

    app = FastAPI()
    app.include_router(router)
    supervisor = LoopSupervisor()
    for spec in default_specs():
        supervisor.register(spec)
    app.state.loops = supervisor
    with TestClient(app) as api:
        body = api.get("/loops/health").json()
    assert [entry["name"] for entry in body["loops"]] == [
        "core.tick", "options.sync", "o5.kurtosis", "gates.eval", "ui.broadcast"]
    assert body["all_healthy"] is False


def test_sans_superviseur_la_sante_est_une_503_pas_un_tout_va_bien():
    """Fail-closed : ne pas savoir n'est pas « tout va bien »."""
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as api:
        assert api.get("/loops/health").status_code == 503
