"""Unified signal scoring.

Weights 35/25/20/15/5 and the /80 renormalization when macro is NOT calibrated are
AUTORITÉ (PRD §0). The component formulas below are v1 provisional PLACEHOLDERS (D-007):
pure, isolated, bounded 0-100, easy to swap once the operators fix them.
"""
from __future__ import annotations

from typing import Optional

from . import config
from .meta import Freshness, MetaField
from .schema import (BridgeVariables, S1State, S2State, SignalBreakdown,
                     UnifiedSignalOutput)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _val(m: MetaField) -> Optional[float]:
    """Usable value only when data exists — STALE is usable but flagged; ABSENT never is."""
    if m.freshness == Freshness.ABSENT or m.value is None:
        return None
    try:
        return float(m.value)
    except (TypeError, ValueError):
        return None


def score_structure(s1: S1State) -> Optional[float]:
    # v1 provisional — position of price proxy (vpoc) inside the value area + defined LVNs.
    vpoc, vah, val_ = _val(s1.structure.vpoc), _val(s1.structure.vah), _val(s1.structure.val)
    if vpoc is None or vah is None or val_ is None or vah <= val_:
        return None
    centeredness = 1.0 - abs((vpoc - (val_ + vah) / 2) / ((vah - val_) / 2))
    lvn = s1.structure.lvn.value if s1.structure.lvn.freshness != Freshness.ABSENT else None
    lvn_bonus = 10.0 if isinstance(lvn, list) and len(lvn) > 0 else 0.0
    return round(_clamp(centeredness * 90.0 + lvn_bonus), 1)


def score_order_flow(s1: S1State) -> Optional[float]:
    # v1 provisional — |CVD| conviction, absorption confirmation, aggressor imbalance.
    cvd = _val(s1.order_flow.cvd)
    if cvd is None:
        return None
    conviction = _clamp(abs(cvd) / 20.0)  # |cvd| ~ 0-2000 -> 0-100
    absorption = s1.order_flow.absorption.value is True
    ratio = _val(s1.order_flow.aggressor_ratio)
    imbalance = _clamp(abs((ratio or 0.5) - 0.5) * 200.0)
    return round(_clamp(conviction * 0.6 + imbalance * 0.3 + (10.0 if absorption else 0.0)), 1)


def score_sentiment(bridge: BridgeVariables, s2: S2State) -> Optional[float]:
    # v1 provisional — calm VIX/VVIX = tradable sentiment; panic collapses the score.
    vix = _val(s2.cascade.vix)
    vvix = _val(bridge.vvix)
    if vix is None:
        return None
    vix_part = _clamp((config.VIX_CRIT - vix) / config.VIX_CRIT * 100.0)
    vvix_part = _clamp((130.0 - (vvix if vvix is not None else 100.0)) / 60.0 * 100.0)
    return round(_clamp(vix_part * 0.7 + vvix_part * 0.3), 1)


def score_quality(s1: S1State, bridge: BridgeVariables) -> Optional[float]:
    # v1 provisional — data pedigree: share of FRESH fields on the fast path (ICE-style QoD).
    fields = [s1.svs_score, s1.chop, s1.order_flow.cvd, s1.order_flow.aggressor_ratio,
              s1.structure.vpoc, bridge.gex, bridge.vvix, bridge.dxy]
    fresh = sum(1 for f in fields if f.freshness == Freshness.FRESH)
    absent = sum(1 for f in fields if f.freshness == Freshness.ABSENT)
    if absent == len(fields):
        return None
    return round(_clamp((fresh / len(fields)) * 100.0), 1)


def compute_unified_signal(s1: S1State, s2: S2State, bridge: BridgeVariables) -> UnifiedSignalOutput:
    """AUTORITÉ aggregation (PRD §0): Structure*0.35 + OrderFlow*0.25 + Macro*0.20 +
    Sentiment*0.15 + Quality*0.05. Macro not calibrated -> weight 0, renormalize /80,
    degraded=true. No component data -> that component contributes nothing (no invention).
    """
    structure = score_structure(s1)
    order_flow = score_order_flow(s1)
    sentiment = score_sentiment(bridge, s2)
    quality = score_quality(s1, bridge)

    macro_calibrated = s2.s2_macro_score.calibrated and s2.s2_macro_score.value is not None
    macro = s2.s2_macro_score.value if macro_calibrated else None
    degraded = not macro_calibrated

    parts: list[tuple[Optional[float], float]] = [
        (structure, config.WEIGHT_STRUCTURE),
        (order_flow, config.WEIGHT_ORDER_FLOW),
        (macro, config.WEIGHT_MACRO if macro_calibrated else 0.0),
        (sentiment, config.WEIGHT_SENTIMENT),
        (quality, config.WEIGHT_QUALITY),
    ]
    denominator = 100.0 if macro_calibrated else config.DEGRADED_DENOMINATOR
    weighted = sum((v or 0.0) * w for v, w in parts)
    available = [v for v, w in parts if w > 0.0]
    score = None if all(v is None for v in available) else round(weighted / denominator * 100.0, 1)

    def contrib(v: Optional[float], w: float) -> Optional[float]:
        return None if v is None else round(v * w, 1)

    return UnifiedSignalOutput(
        score=score,
        degraded=degraded,
        breakdown=SignalBreakdown(
            structure=contrib(structure, config.WEIGHT_STRUCTURE),
            order_flow=contrib(order_flow, config.WEIGHT_ORDER_FLOW),
            macro=contrib(macro, config.WEIGHT_MACRO) if macro_calibrated else None,
            sentiment=contrib(sentiment, config.WEIGHT_SENTIMENT),
            quality=contrib(quality, config.WEIGHT_QUALITY),
        ),
    )
