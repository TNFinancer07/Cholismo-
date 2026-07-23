"""Feature — Simulateur Monte Carlo de robustesse (D-043, tranche 2).

Approche figée AVANT implémentation (Loop 1 étape 3) :
- rééchantillonne N fois (5 000–10 000) la série des R-multiples RÉCONCILIÉS en **bootstrap AVEC
  REMISE** (tire `len(série)` trades avec remise à chaque simulation) ;
- calcule le **Max Drawdown** de chaque courbe d'équité (pic incluant le 0 initial → une perte
  d'ouverture compte comme drawdown) ;
- renvoie **P50/P95/P99** du MaxDD + **`P(MaxDD ≥ seuil)`** (seuil = `risk.max_drawdown_r_day`) ;
- FAIL-CLOSED (§3/§8) : rendement non-fini/bool ignoré ; série < plancher → `INSUFFICIENT_DATA`
  (percentiles/proba `None`, jamais fabriqués) ; seuil invalide → `prob_exceed` None ;
- **répétable** avec `seed` fixé ; déterministe sur les cas dégénérés (tout-gagnant / tout-perdant),
  ce qui permet des tests EXACTS sans flakiness. Analyse OFFLINE (hors ContextSchema live §1).
"""
from app.monte_carlo import MonteCarloSimulator, max_drawdown


def test_max_drawdown_pure_sequence():
    # équité 0→1→2→-1→0 : pic 2, creux -1 → MaxDD 3
    assert max_drawdown([1, 1, -3, 1]) == 3
    # perte d'ouverture depuis 0 : équité -1→-2, pic 0 → MaxDD 2
    assert max_drawdown([-1, -1]) == 2
    # monotone montant → aucun drawdown
    assert max_drawdown([1, 2, 3]) == 0


def test_all_wins_zero_drawdown():
    r = [1.0] * 12
    res = MonteCarloSimulator(n_sims=500, threshold=2.0, seed=1).run(r)
    assert res.verdict == "OK" and res.n_trades == 12
    assert res.max_dd_p50 == 0 and res.max_dd_p95 == 0 and res.max_dd_p99 == 0
    assert res.prob_exceed == 0.0            # jamais de drawdown → jamais au-dessus du seuil


def test_all_losses_deterministic_maxdd():
    # chaque rééchantillon = 8 pertes de 1.0 → MaxDD EXACT = 8, quel que soit le seed
    r = [-1.0] * 8
    res = MonteCarloSimulator(n_sims=300, threshold=5.0, seed=42).run(r)
    assert res.max_dd_p50 == 8 and res.max_dd_p95 == 8 and res.max_dd_p99 == 8
    assert res.prob_exceed == 1.0            # 8 ≥ 5 pour tous → proba 1


def test_percentiles_ordered_and_bounded():
    r = [1.5, -1.0, 0.5, -2.0, 1.0, -0.5, 2.0, -1.5, 0.8, -0.3]
    res = MonteCarloSimulator(n_sims=3000, threshold=3.0, seed=7).run(r)
    assert res.verdict == "OK"
    assert res.max_dd_p50 <= res.max_dd_p95 <= res.max_dd_p99
    assert res.max_dd_p50 >= 0
    assert 0.0 <= res.prob_exceed <= 1.0


def test_repeatable_with_seed():
    r = [0.5, -0.3, 1.2, -0.8, 0.4, -1.1, 0.9, -0.2, 0.6, -0.5]
    a = MonteCarloSimulator(n_sims=1000, threshold=2.0, seed=123).run(r)
    b = MonteCarloSimulator(n_sims=1000, threshold=2.0, seed=123).run(r)
    assert a.model_dump() == b.model_dump()   # même seed → résultat identique


def test_convergence_prob_near_theory():
    # série {+1,-1} de 10 trades ; MaxDD ≥ 10 exige les 10 tirages = -1 → p = (0.5)^10 ≈ 0.000977
    r = [1.0, -1.0] * 5
    res = MonteCarloSimulator(n_sims=20000, threshold=10.0, seed=99).run(r)
    assert 0.0 <= res.prob_exceed <= 0.005    # converge vers ~0.001 (seed fixé → déterministe)
    assert res.max_dd_p99 <= 10               # borne dure : jamais plus que 10 pertes


def test_insufficient_data_short_series():
    res = MonteCarloSimulator(n_sims=1000, threshold=2.0, min_trades=4, seed=1).run([1.0, -1.0])
    assert res.verdict == "INSUFFICIENT_DATA"
    assert res.max_dd_p95 is None and res.prob_exceed is None and res.n_sims == 0


def test_non_finite_and_bool_filtered():
    r = [float("nan"), True] + [-1.0] * 8 + [float("inf")]   # nan/inf/bool retirés → 8 pertes
    res = MonteCarloSimulator(n_sims=200, threshold=5.0, seed=3).run(r)
    assert res.n_trades == 8 and res.max_dd_p50 == 8


def test_invalid_threshold_prob_none_but_percentiles_computed():
    r = [1.0, -2.0, 1.0, -1.0, 0.5, -0.5, 1.0, -1.5]
    res = MonteCarloSimulator(n_sims=500, threshold=0.0, seed=5).run(r)   # seuil ≤ 0 → invalide
    assert res.prob_exceed is None and res.max_dd_p95 is not None


# ---------- projection : branchement sur la source RÉELLE (trades réconciliés) ----------


class _StubStore:
    def __init__(self, outcomes, recons):
        self._d = {"OutcomeEvent": outcomes, "ReconEvent": recons}

    def events(self, t):
        return self._d.get(t, [])


def test_projection_monte_carlo_from_store():
    from app.projections import monte_carlo
    outcomes = [{"decision_id": f"d{i}", "r_multiple": (1.0 if i % 2 == 0 else -1.0)} for i in range(10)]
    recons = [{"decision_id": f"d{i}", "matched": True} for i in range(10)]
    res = monte_carlo(_StubStore(outcomes, recons))
    assert res["verdict"] == "OK" and res["n_trades"] == 10
    assert res["threshold"] == 2.0                       # défaut settings risk.max_drawdown_r_day
    assert res["max_dd_p50"] <= res["max_dd_p95"] <= res["max_dd_p99"]
    assert 0.0 <= res["prob_exceed"] <= 1.0


def test_projection_insufficient_when_few_reconciled():
    from app.projections import monte_carlo
    outcomes = [{"decision_id": "d0", "r_multiple": 1.0}]
    recons = [{"decision_id": "d0", "matched": True}]
    assert monte_carlo(_StubStore(outcomes, recons))["verdict"] == "INSUFFICIENT_DATA"
