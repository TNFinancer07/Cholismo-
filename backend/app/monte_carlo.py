"""Simulateur Monte Carlo de robustesse (D-043, tranche 2).

Analyse OFFLINE (recherche, HORS ContextSchema live §1) du risque de drawdown d'une série de
rendements RÉELS (R-multiples de trades réconciliés, D-013). Rééchantillonne la séquence en
**bootstrap AVEC REMISE** (chaque simulation tire `len(série)` trades avec remise), calcule le
**Max Drawdown** de chaque courbe d'équité, et en tire la distribution : P50/P95/P99 + la
probabilité `P(MaxDD ≥ seuil)` (seuil d'invalidation du challenge, `risk.max_drawdown_r_day`).

Pur (aucun LLM, aucune source live). **Répétable** avec `seed`. FAIL-CLOSED (§3/§8) : rendement
non-fini/bool ignoré ; série < plancher → `INSUFFICIENT_DATA` (percentiles/proba `None`, jamais
fabriqués) ; seuil invalide → `prob_exceed` None. LECTURE SEULE (§2.1). Hors hot path (§7)."""
from __future__ import annotations

import math
import random
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel


def _finite(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def max_drawdown(returns: Iterable[float]) -> float:
    """Max Drawdown (magnitude ≥ 0) de la courbe d'équité cumulée. Le pic inclut le 0 initial :
    une perte d'ouverture depuis 0 compte déjà comme drawdown (pas de biais optimiste).
    Overflow IEEE 754 (somme → ±inf) → renvoie `inf` (indéterminé), jamais un faux 0 masqué par
    `nan` (`inf−inf=nan` et `nan>mdd` vaut False)."""
    peak = equity = mdd = 0.0
    for r in returns:
        equity += r
        if not math.isfinite(equity):
            return math.inf                        # overflow → drawdown indéterminé (§3)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > mdd:
            mdd = dd
    return mdd


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Percentile par interpolation linéaire (méthode « linear », comme numpy) sur liste triée."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


class MonteCarloResult(BaseModel):
    """Distribution du Max Drawdown sur `n_sims` rééchantillonnages bootstrap. `None` = indéfini
    (série insuffisante ou seuil invalide) — jamais un faux nombre autoritaire (§8)."""
    verdict: str                    # OK | INSUFFICIENT_DATA
    n_sims: int
    n_trades: int
    threshold: float | None
    max_dd_p50: float | None
    max_dd_p95: float | None
    max_dd_p99: float | None
    prob_exceed: float | None       # P(MaxDD ≥ threshold) ; None si seuil invalide
    mean_max_dd: float | None
    seed: int | None
    capped: bool = False            # n_sims réduit pour tenir le budget CPU (entrée énorme)


class MonteCarloSimulator:
    """Bootstrap Monte Carlo du Max Drawdown. Paramètres FIGÉS à la construction.

    - `n_sims` : nombre de rééchantillonnages (5 000–10 000 typique) ;
    - `threshold` : seuil d'invalidation (R, magnitude > 0) — sinon `prob_exceed` None ;
    - `min_trades` : plancher sous lequel → INSUFFICIENT_DATA (jamais un faux nombre §8) ;
    - `seed` : graine optionnelle → **répétabilité** (None = entropie système) ;
    - `max_work` : budget CPU `n_sims × n_trades` (0 = illimité) → borne le temps de calcul sur
      entrée énorme en RÉDUISANT n_sims (jamais un hang de worker), réduction reportée via `capped`."""

    def __init__(self, n_sims: int = 10000, threshold: float | None = None,
                 min_trades: int = 4, seed: int | None = None, max_work: int = 0):
        self.n_sims = n_sims
        self.threshold = threshold
        self.min_trades = min_trades
        self.seed = seed
        self.max_work = max_work

    def _insufficient(self, n: int, thr: float | None) -> MonteCarloResult:
        return MonteCarloResult(verdict="INSUFFICIENT_DATA", n_sims=0, n_trades=n, threshold=thr,
                                max_dd_p50=None, max_dd_p95=None, max_dd_p99=None,
                                prob_exceed=None, mean_max_dd=None, seed=self.seed)

    def run(self, returns: Iterable[Any] | None) -> MonteCarloResult:
        clean = [float(r) for r in (returns or []) if _finite(r)]          # fail-closed §3
        n = len(clean)
        thr = self.threshold if (_finite(self.threshold) and self.threshold > 0) else None
        if n < max(self.min_trades, 2):
            return self._insufficient(n, thr)
        rng = random.Random(self.seed)                                     # seed None → entropie
        n_sims = max(1, self.n_sims)
        capped = bool(self.max_work) and n * n_sims > self.max_work        # borne CPU (entrée énorme)
        if capped:
            n_sims = max(1, self.max_work // n)
        randrange = rng.randrange
        dds: list[float] = []
        exceed = 0
        for _ in range(n_sims):
            peak = equity = mdd = 0.0
            for _ in range(n):                                             # bootstrap AVEC REMISE
                equity += clean[randrange(n)]
                if equity > peak:
                    peak = equity
                dd = peak - equity
                if dd > mdd:
                    mdd = dd
            if not (math.isfinite(equity) and math.isfinite(mdd)):         # overflow → exclu (§3)
                continue                                                   # jamais un faux 0/nan
            dds.append(mdd)
            if thr is not None and mdd >= thr:
                exceed += 1
        if not dds:                                                        # tout exclu (overflow)
            return self._insufficient(n, thr)
        dds.sort()
        return MonteCarloResult(
            verdict="OK", n_sims=len(dds), n_trades=n, threshold=thr,
            max_dd_p50=round(_percentile(dds, 50), 6),
            max_dd_p95=round(_percentile(dds, 95), 6),
            max_dd_p99=round(_percentile(dds, 99), 6),
            prob_exceed=round(exceed / len(dds), 6) if thr is not None else None,
            mean_max_dd=round(sum(dds) / len(dds), 6), seed=self.seed, capped=capped)
