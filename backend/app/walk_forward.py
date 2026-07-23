"""Walk-Forward robustness engine (D-043).

Analyse OFFLINE (recherche, HORS ContextSchema live §1) de la STABILITÉ temporelle d'une série de
rendements RÉELS (R-multiples de trades réconciliés, D-013). Découpe la série ordonnée dans le temps
en fenêtres glissantes (In-Sample / Out-of-Sample), calcule le Walk-Forward Efficiency
(WFE = rendement/trade OOS ÷ rendement/trade IS, normalisé par la taille des sous-fenêtres) et lève
`OVERFIT_DETECTED` quand le WFE agrégé chute sous le seuil.

Pur et déterministe (aucun LLM, aucune source live). FAIL-CLOSED (§3/§8) : rendement non-fini
ignoré ; IS non profitable → WFE indéfini (`None`), JAMAIS un ratio fabriqué ; données
insuffisantes → verdict `INSUFFICIENT_DATA`, jamais un faux nombre autoritaire. LECTURE SEULE (§2.1).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import median
from typing import Any

from pydantic import BaseModel


def _finite(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class WalkForwardWindow(BaseModel):
    """Une fenêtre glissante scindée IS/OOS. `wfe`/`overfit` = None si IS non profitable (indéfini)."""
    start: int
    n_is: int
    n_oos: int
    is_profit: float
    oos_profit: float
    wfe: float | None
    overfit: bool | None
    reason: str = ""            # "" | "IS_UNPROFITABLE"


class WalkForwardResult(BaseModel):
    """Résultat typé du balayage. `verdict` ∈ ROBUST | OVERFIT_DETECTED | IS_UNPROFITABLE |
    INSUFFICIENT_DATA. `wfe` = médiane des fenêtres valides (None si aucune)."""
    verdict: str
    wfe: float | None
    n_windows: int
    overfit_windows: int
    overfit_ratio: float | None
    is_frac: float
    window: int
    step: int
    threshold: float
    windows: list[WalkForwardWindow]


class WalkForwardEngine:
    """Découpe rolling IS/OOS + WFE + alerte `OVERFIT_DETECTED`. Paramètres FIGÉS à la construction
    (déterministe). `run(returns)` → `WalkForwardResult` typé.

    - `is_frac` ∈ ]0,1[ : part In-Sample de chaque fenêtre (défaut 0.70) ;
    - `window` : trades par fenêtre (0 → une seule fenêtre = toute la série) ;
    - `step` : décalage entre fenêtres (0 → = window, non chevauchant) ;
    - `threshold` : WFE < seuil ⇒ overfit (défaut 0.50) ;
    - `min_trades` : plancher sous lequel on renvoie INSUFFICIENT_DATA (jamais un faux nombre §8)."""

    def __init__(self, is_frac: float = 0.70, window: int = 0, step: int = 0,
                 threshold: float = 0.50, min_trades: int = 0):
        self.is_frac = is_frac
        self.window = window
        self.step = step
        self.threshold = threshold
        self.min_trades = min_trades

    def _insufficient(self, params: dict[str, Any]) -> WalkForwardResult:
        return WalkForwardResult(verdict="INSUFFICIENT_DATA", wfe=None, n_windows=0,
                                 overfit_windows=0, overfit_ratio=None, windows=[], **params)

    def run(self, returns: Iterable[Any] | None) -> WalkForwardResult:
        params = {"is_frac": self.is_frac, "window": self.window, "step": self.step,
                  "threshold": self.threshold}
        clean = [float(r) for r in (returns or []) if _finite(r)]           # fail-closed §3
        min_needed = max(self.min_trades, 2)                                # ≥ 1 IS + 1 OOS
        w = self.window if self.window and self.window > 0 else len(clean)  # 0 → toute la série
        if len(clean) < min_needed or w < 2:
            return self._insufficient(params)
        step = self.step if self.step and self.step > 0 else w             # défaut : non chevauchant

        windows: list[WalkForwardWindow] = []
        start = 0
        while start + w <= len(clean):
            seg = clean[start:start + w]
            n_is = max(1, min(w - 1, round(self.is_frac * w)))             # borné → n_oos ≥ 1
            is_seg, oos_seg = seg[:n_is], seg[n_is:]
            is_profit, oos_profit = sum(is_seg), sum(oos_seg)
            if is_profit <= 0:                                             # IS non profitable → indéfini (§3)
                wfe, overfit, reason = None, None, "IS_UNPROFITABLE"
            else:
                wfe = (oos_profit / len(oos_seg)) / (is_profit / n_is)     # rendement/trade OOS ÷ IS
                if math.isfinite(wfe):
                    overfit, reason = wfe < self.threshold, ""
                else:                                                      # overflow → nan → indéterminé (§3)
                    wfe, overfit, reason = None, None, "UNDEFINED"
            windows.append(WalkForwardWindow(
                start=start, n_is=n_is, n_oos=len(oos_seg),
                is_profit=round(is_profit, 6) if math.isfinite(is_profit) else is_profit,
                oos_profit=round(oos_profit, 6) if math.isfinite(oos_profit) else oos_profit,
                wfe=None if wfe is None else round(wfe, 6), overfit=overfit, reason=reason))
            start += step

        valid = [win.wfe for win in windows if win.wfe is not None]
        overfit_windows = sum(1 for win in windows if win.overfit is True)
        if not valid:                                                     # tout IS non profitable
            return WalkForwardResult(verdict="IS_UNPROFITABLE", wfe=None, n_windows=len(windows),
                                     overfit_windows=overfit_windows, overfit_ratio=None,
                                     windows=windows, **params)
        agg = median(valid)
        verdict = "OVERFIT_DETECTED" if agg < self.threshold else "ROBUST"
        return WalkForwardResult(verdict=verdict, wfe=round(agg, 6), n_windows=len(windows),
                                 overfit_windows=overfit_windows,
                                 overfit_ratio=round(overfit_windows / len(windows), 4),
                                 windows=windows, **params)
