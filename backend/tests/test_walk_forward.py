"""Feature — Walk-Forward robustness engine (D-043).

Approche figée AVANT implémentation (Loop 1 étape 3) :
- découpe une série de rendements ORDONNÉE dans le temps en fenêtres glissantes (rolling), chacune
  scindée In-Sample (70 %) / Out-of-Sample (30 %) ;
- **WFE** = (profit OOS / n_oos) ÷ (profit IS / n_is) — NORMALISÉ par la taille des sous-fenêtres
  (la différence 70/30 ne biaise pas le ratio de rentabilité par trade) ;
- **OVERFIT_DETECTED** si le WFE agrégé (médiane des fenêtres valides) < seuil (0.5) ;
- FAIL-CLOSED (§3/§8) : rendement non-fini ignoré ; IS non profitable → WFE `None` (indéfini,
  jamais un ratio fabriqué) ; données insuffisantes → `INSUFFICIENT_DATA` (jamais un faux nombre
  autoritaire) ;
- analyse OFFLINE (hors ContextSchema live §1), déterministe (aucun LLM, aucune source live).
"""
from app.walk_forward import WalkForwardEngine


def test_wfe_normalized_per_trade():
    # IS 7 trades (profit 7 → 1.0/trade), OOS 3 trades (profit 1.2 → 0.4/trade) → WFE 0.4
    r = [1.0] * 7 + [0.4, 0.4, 0.4]
    res = WalkForwardEngine(is_frac=0.7, window=10, threshold=0.5).run(r)
    assert res.n_windows == 1
    w = res.windows[0]
    assert w.n_is == 7 and w.n_oos == 3
    assert abs(w.wfe - 0.4) < 1e-9 and w.overfit is True
    assert res.verdict == "OVERFIT_DETECTED"


def test_robust_when_oos_matches_is():
    r = [1.0] * 7 + [1.0, 1.0, 1.0]          # OOS/trade = IS/trade → WFE 1.0
    res = WalkForwardEngine(is_frac=0.7, window=10).run(r)
    assert abs(res.wfe - 1.0) < 1e-9 and res.verdict == "ROBUST"
    assert res.windows[0].overfit is False


def test_overfit_threshold_is_strict():
    # WFE exactement 0.5 → PAS overfit (comparaison stricte) → ROBUST
    r = [1.0] * 7 + [0.5, 0.5, 0.5]
    res = WalkForwardEngine(is_frac=0.7, window=10, threshold=0.5).run(r)
    assert abs(res.windows[0].wfe - 0.5) < 1e-9
    assert res.windows[0].overfit is False and res.verdict == "ROBUST"


def test_rolling_windows_count_and_step():
    r = [1.0] * 20
    res = WalkForwardEngine(is_frac=0.7, window=10, step=5).run(r)
    assert res.n_windows == 3
    assert [w.start for w in res.windows] == [0, 5, 10]


def test_is_unprofitable_wfe_none():
    # IS profit <= 0 → WFE indéfini (None), reason IS_UNPROFITABLE, jamais un ratio fabriqué
    r = [-1.0] * 7 + [2.0, 2.0, 2.0]
    res = WalkForwardEngine(is_frac=0.7, window=10).run(r)
    w = res.windows[0]
    assert w.wfe is None and w.overfit is None and w.reason == "IS_UNPROFITABLE"
    assert res.verdict == "IS_UNPROFITABLE" and res.wfe is None


def test_insufficient_data():
    res = WalkForwardEngine(window=10).run([1.0])
    assert res.verdict == "INSUFFICIENT_DATA" and res.wfe is None and res.n_windows == 0


def test_non_finite_returns_ignored():
    r = [float("nan")] + [1.0] * 7 + [0.4, 0.4, 0.4] + [float("inf")]
    res = WalkForwardEngine(is_frac=0.7, window=10).run(r)   # nan/inf retirés → 10 rendements
    assert res.n_windows == 1 and abs(res.windows[0].wfe - 0.4) < 1e-9


def test_single_window_whole_series_when_window_zero():
    r = [1.0] * 7 + [0.8, 0.8, 0.8]          # window=0 → toute la série en une fenêtre
    res = WalkForwardEngine(is_frac=0.7, window=0).run(r)
    assert res.n_windows == 1 and res.windows[0].n_is == 7


def test_deterministic():
    r = [0.5, -0.3, 1.2, 0.1, -0.5, 2.0, 0.3, -0.1, 0.9, 0.4, 1.1, -0.2]
    e = WalkForwardEngine(is_frac=0.7, window=6, step=3)
    assert e.run(r).model_dump() == e.run(r).model_dump()


def test_empty_returns():
    res = WalkForwardEngine().run([])
    assert res.verdict == "INSUFFICIENT_DATA" and res.windows == []


def test_bool_returns_ignored():
    # bool est un int en Python → ne doit pas compter comme rendement (fail-closed §3)
    r = [True] + [1.0] * 7 + [0.4, 0.4, 0.4]
    res = WalkForwardEngine(is_frac=0.7, window=10).run(r)
    assert res.n_windows == 1 and abs(res.windows[0].wfe - 0.4) < 1e-9


# ---------- projection : branchement sur la source RÉELLE (trades réconciliés, D-013) ----------


class _StubStore:
    """Stub minimal : `_reconciled_r_multiples` ne consomme que `.events(type)`."""
    def __init__(self, outcomes, recons):
        self._d = {"OutcomeEvent": outcomes, "ReconEvent": recons}

    def events(self, t):
        return self._d.get(t, [])


def test_projection_from_reconciled_store():
    from app.projections import walk_forward
    outcomes = [{"decision_id": f"d{i}", "outcome": "WIN", "r_multiple": (1.0 if i < 7 else 0.4)}
                for i in range(10)]
    recons = [{"decision_id": f"d{i}", "matched": True} for i in range(10)]
    res = walk_forward(_StubStore(outcomes, recons))       # ordre chronologique préservé
    assert res["n_windows"] == 1 and res["verdict"] == "OVERFIT_DETECTED"
    assert abs(res["wfe"] - 0.4) < 1e-9


def test_projection_ignores_unmatched_and_none_r():
    from app.projections import walk_forward
    outcomes = [{"decision_id": "d0", "r_multiple": 1.0},
                {"decision_id": "d1", "r_multiple": None},     # r None → ignoré
                {"decision_id": "d2", "r_multiple": 5.0}]      # non réconcilié → ignoré
    recons = [{"decision_id": "d0", "matched": True}, {"decision_id": "d2", "matched": False}]
    res = walk_forward(_StubStore(outcomes, recons))
    assert res["verdict"] == "INSUFFICIENT_DATA"               # 1 seul r valide < WF_MIN_TRADES
