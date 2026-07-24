"""Feature — Endpoint & consolidation ROBUSTESSE (D-043, tranche 3).

Approche figée AVANT implémentation (Loop 1 étape 3) :
- `projections.robustness(store)` consolide `walk_forward(store)` + `monte_carlo(store)` en UN payload
  `{"walk_forward": {...}, "monte_carlo": {...}}` (analyse OFFLINE, hors ContextSchema live §1) ;
- `GET /analyses/robustness` expose ce payload, **fail-closed** : données insuffisantes → verdicts
  `INSUFFICIENT_DATA` propres en **HTTP 200**, JAMAIS une 500 (§3).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)

_WF_VERDICTS = {"ROBUST", "OVERFIT_DETECTED", "IS_UNPROFITABLE", "INSUFFICIENT_DATA"}
_MC_VERDICTS = {"OK", "INSUFFICIENT_DATA"}


class _StubStore:
    def __init__(self, outcomes, recons):
        self._d = {"OutcomeEvent": outcomes, "ReconEvent": recons}

    def events(self, t):
        return self._d.get(t, [])


def test_robustness_projection_consolidates_both_engines():
    from app.projections import robustness
    outcomes = [{"decision_id": f"d{i}", "r_multiple": (1.0 if i % 3 else -0.8)} for i in range(30)]
    recons = [{"decision_id": f"d{i}", "matched": True} for i in range(30)]
    res = robustness(_StubStore(outcomes, recons))
    assert set(res) == {"walk_forward", "monte_carlo"}
    assert res["walk_forward"]["verdict"] in _WF_VERDICTS
    assert res["monte_carlo"]["verdict"] == "OK"
    assert res["monte_carlo"]["threshold"] == 2.0          # seuil challenge (settings, source unique)


def test_robustness_projection_fail_closed_on_empty():
    from app.projections import robustness
    res = robustness(_StubStore([], []))                   # aucun trade réconcilié
    assert res["walk_forward"]["verdict"] == "INSUFFICIENT_DATA"
    assert res["monte_carlo"]["verdict"] == "INSUFFICIENT_DATA"
    assert res["monte_carlo"]["max_dd_p95"] is None        # jamais un nombre fabriqué (§8)


def test_robustness_endpoint_200_and_contract():
    r = _client.get("/analyses/robustness")
    assert r.status_code == 200                            # fail-closed : jamais une 500
    body = r.json()
    assert "walk_forward" in body and "monte_carlo" in body
    assert body["walk_forward"]["verdict"] in _WF_VERDICTS  # contrat (store de test partagé → valeurs libres)
    assert body["monte_carlo"]["verdict"] in _MC_VERDICTS
