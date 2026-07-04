"""A3 — s2_macro_score. v1 provisional — calibration owner: Youssef.
NE PAS utiliser en live avant validation. (AUTORITÉ skeleton: PRD §A3, CLAUDE §8.1.)

While not calibrated the final score is None and its live contribution is ZERO; only the
inputs (coherence / tilt / gate) are exposed to help calibration — never a fake number.
"""
from __future__ import annotations

from typing import Optional

from . import config
from .schema import S2MacroScore


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _coherence(cascade_values: dict[str, Optional[float]]) -> Optional[float]:
    """Directional agreement of the cascade vs the EUR/USD bias (0-100). v1 provisional."""
    eur = cascade_values.get("eurusd")
    if eur is None:
        return None
    # Risk-on chain: NQ/ES up, VIX down, ZN down, DX down -> EUR up. Count agreements.
    votes = []
    for key, invert in (("nq_es", False), ("vix", True), ("zn", True), ("dx", True)):
        v = cascade_values.get(key)
        if v is None:
            continue
        direction = -v if invert else v
        votes.append(1.0 if direction * eur > 0 else 0.0)
    if not votes:
        return None
    return round(100.0 * sum(votes) / len(votes), 1)


def _tilt(matrix: Optional[list[list[float]]]) -> Optional[float]:
    """Mean |signed intensity| of the Bridgewater matrix, scaled 0-100. v1 provisional."""
    if not matrix:
        return None
    cells = [abs(c) for row in matrix for c in row if c is not None]
    if not cells:
        return None
    return round(_clamp(100.0 * sum(cells) / len(cells), 0, 100), 1)


def _gate(real_rates: Optional[float]) -> Optional[float]:
    """Real-rates amplifier 0.9-1.1 (primary driver, PRD §A1). v1 provisional."""
    if real_rates is None:
        return None
    return round(_clamp(1.0 + 0.05 * real_rates, 0.9, 1.1), 3)


def compute_s2_macro_score(
    cascade_values: dict[str, Optional[float]],
    matrix: Optional[list[list[float]]],
    real_rates: Optional[float],
) -> S2MacroScore:
    # v1 provisional — calibration owner: Youssef. NE PAS utiliser en live avant validation.
    coherence = _coherence(cascade_values)
    tilt = _tilt(matrix)
    gate = _gate(real_rates)
    if not config.MACRO_CALIBRATED:
        # Honest: inputs visible, final score withheld, live contribution = 0 (PRD §A3).
        return S2MacroScore(value=None, calibrated=False, coherence=coherence, tilt=tilt, gate=gate)
    if coherence is None or tilt is None or gate is None:
        return S2MacroScore(value=None, calibrated=True, coherence=coherence, tilt=tilt, gate=gate)
    value = _clamp((coherence * 0.50 + tilt * 0.40 + 10) * gate, 0, 100)
    return S2MacroScore(value=round(value, 1), calibrated=True, coherence=coherence, tilt=tilt, gate=gate)
