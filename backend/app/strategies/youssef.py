"""Youssef — the REAL macro analysis pipeline (AUTORITÉ: reference/youssef/01-03).

Implemented here, deterministically:
- Phase 0 / D4 regime: VIX tiers with hysteresis + carry/fund/score multipliers.
- Étape 0: Bridgewater quadrant from (g, pi) + canonical WEIGHTS table (file 1 — D-021).
- N3 Flux 1: weight renormalization, tanh aggregation, D4 gate, conviction, 4 horizons.
- N3 Flux 2: the 6 anticipation arbitrages (thresholds/caps from file 3, which "fait foi").

Inputs (g, pi, D1-D5, arbitrage deltas) are SIMULATED by the MockDataSource until real
feeds exist — the formulas below are the canonical ones (see reference/MANIFEST.md).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from ..schema import Arbitrage, BridgewaterQuadrant, Flux1, MacroRegime, S2Pipeline

# --- Phase 0 / D4 — AUTORITÉ (file 1 §3/§6; carry_mult conflict resolved to Arb4 values) ---

GATES = {
    "GREEN":  {"carry": 1.0, "fund": 1.0, "score": 1.0},
    "YELLOW": {"carry": 0.7, "fund": 1.0, "score": 0.7},
    "ORANGE": {"carry": 0.4, "fund": 0.7, "score": 0.4},
    "RED":    {"carry": 0.0, "fund": 0.3, "score": 0.0},
}
HYSTERESIS = {"green_yellow": {"entry": 18, "exit": 14},
              "yellow_orange": {"entry": 26, "exit": 22},
              "orange_red": {"entry": 37, "exit": 33}}


def update_regime(current: str, vix: Optional[float], kurtosis: Optional[float]) -> str:
    """ENTRY != EXIT (dead zones). kurtosis > 9 forces RED even if VIX is low."""
    if vix is None:
        return current
    r, h = current, HYSTERESIS
    if r == "GREEN" and vix > h["green_yellow"]["entry"]:
        r = "YELLOW"
    elif r == "YELLOW" and vix < h["green_yellow"]["exit"]:
        r = "GREEN"
    elif r == "YELLOW" and vix > h["yellow_orange"]["entry"]:
        r = "ORANGE"
    elif r == "ORANGE" and vix < h["yellow_orange"]["exit"]:
        r = "YELLOW"
    elif r == "ORANGE" and vix > h["orange_red"]["entry"]:
        r = "RED"
    elif r == "RED" and vix < h["orange_red"]["exit"]:
        r = "ORANGE"
    if kurtosis is not None and kurtosis > 9:
        r = "RED"
    return r


def make_regime(tier: str, vix: Optional[float], kurtosis: Optional[float]) -> MacroRegime:
    gate = GATES[tier]
    return MacroRegime(tier=tier, vix=vix, kurtosis=kurtosis,
                       carry_mult=gate["carry"], fund_mult=gate["fund"],
                       score_mult=gate["score"])


# --- Étape 0 — quadrant Bridgewater (canonical WEIGHTS: file 1 §4 — D-021) ---

WEIGHTS = {
    "SURCHAUFFE":   {"D1": 0.15, "D2": 0.35, "D3": 0.30, "D4": 0.10, "D5": 0.10},
    "GOLDILOCKS":   {"D1": 0.20, "D2": 0.15, "D3": 0.10, "D4": 0.30, "D5": 0.25},
    "STAGFLATION":  {"D1": 0.15, "D2": 0.15, "D3": 0.25, "D4": 0.25, "D5": 0.20},
    "DESINFLATION": {"D1": 0.30, "D2": 0.30, "D3": 0.10, "D4": 0.15, "D5": 0.15},
}


def classify_quadrant(g: Optional[float], pi: Optional[float]) -> BridgewaterQuadrant:
    if g is None or pi is None:
        return BridgewaterQuadrant()
    if g >= 0 and pi >= 0:
        quadrant = "SURCHAUFFE"
    elif g < 0 <= pi:
        quadrant = "STAGFLATION"
    elif g < 0 and pi < 0:
        quadrant = "DESINFLATION"
    else:
        quadrant = "GOLDILOCKS"
    r = math.sqrt(g * g + pi * pi)
    theta = math.degrees(math.atan2(pi, g)) % 360
    confidence = min(r / 0.8, 1.0)
    d_boundary = min(theta % 90, 90 - (theta % 90))
    transition = "high" if d_boundary < 15 else "moderate" if d_boundary < 30 else "low"
    return BridgewaterQuadrant(quadrant=quadrant, g=round(g, 3), pi=round(pi, 3),
                               r=round(r, 3), theta=round(theta, 1),
                               confidence=round(confidence, 2), transition_risk=transition,
                               weights=WEIGHTS[quadrant])


# --- N3 Flux 1 — AUTORITÉ (file 3) ---

def compute_flux1(d_scores: dict[str, Optional[float]], quadrant: BridgewaterQuadrant,
                  regime: MacroRegime) -> Flux1:
    required = ("D1", "D2", "D3", "D4", "D5")
    if not quadrant.weights or any(d_scores.get(k) is None for k in required):
        return Flux1(d_scores=d_scores)
    w = dict(quadrant.weights)
    total = sum(w.values())
    w = {k: v / total for k, v in w.items()}  # renormalisation obligatoire
    raw = sum(w[k] * float(d_scores[k]) for k in required)
    score_pre_gate = math.tanh(raw)
    score_final = score_pre_gate * regime.fund_mult   # gate D4 (fundamental multiplier)
    conviction = abs(score_final) * 10
    d1, d2, d3, d4, d5 = (float(d_scores[k]) for k in required)
    return Flux1(
        d_scores=d_scores,
        raw_score=round(raw, 3),
        score_final=round(score_final, 3),
        conviction=round(conviction, 1),
        direction="SHORT" if score_final < -0.05 else "LONG" if score_final > 0.05 else "NEUTRE",
        horizons={
            "long_4_12_sem": round(0.5 * d1 + 0.5 * d5, 3),
            "moyen_1_4_sem": round(0.6 * d2 + 0.4 * d3, 3),   # ★ sweet spot
            "court_1_5_j": round(d4, 3),
            "intra": None,  # overlay d'exécution (flux), pas un score
        })


# --- N3 Flux 2 — the 6 arbitrages (thresholds/caps AUTORITÉ file 3; conviction scale
#     for Arb1/2/3 is a documented convention, see MANIFEST/D-021) ---

def _direction(delta: float, inverted: bool = False) -> str:
    positive = delta > 0
    if inverted:
        positive = not positive
    return "LONG_BASE" if positive else "SHORT_BASE"


def compute_arbitrages(inputs: dict[str, Optional[float]], regime: MacroRegime) -> list[Arbitrage]:
    arbs: list[Arbitrage] = []

    def add(arb_id, name, dim, horizon, threshold, delta, active, direction, conviction, note=""):
        arbs.append(Arbitrage(arb_id=arb_id, name=name, source_dim=dim, horizon=horizon,
                              threshold=threshold,
                              delta=None if delta is None else round(delta, 2),
                              active=active, direction=direction,
                              conviction=None if conviction is None else round(conviction, 1),
                              note=note))

    d = inputs.get("taylor_ois_delta")
    if d is None:
        add(1, "Taylor vs OIS", "D2", "1-4 sem", "|δ| > 0.30 %", None, None, None, None, "intrants absents")
    else:
        active = abs(d) > 0.30
        add(1, "Taylor vs OIS", "D2", "1-4 sem", "|δ| > 0.30 %", d, active,
            _direction(d) if active else None,
            min(abs(d) / 0.30 * 5, 9) if active else None, "le QUAND (tactique)")

    d = inputs.get("phillips_tips_delta")
    if d is None:
        add(2, "Phillips vs TIPS", "D3", "2-4 sem", "|δ| > 0.25 %", None, None, None, None, "intrants absents")
    else:
        active = abs(d) > 0.25
        add(2, "Phillips vs TIPS", "D3", "2-4 sem", "|δ| > 0.25 %", d, active,
            _direction(d) if active else None,
            min(abs(d) / 0.25 * 5, 9) if active else None, "précède Arb1 de 3-6 mois")

    z = inputs.get("beer_z")
    if z is None:
        add(3, "BEER vs spot", "D5", "6-12+ sem", "|z| > 1.5", None, None, None, None, "intrants absents")
    else:
        active = abs(z) > 1.5
        add(3, "BEER vs spot", "D5", "6-12+ sem", "|z| > 1.5", z, active,
            _direction(z, inverted=True) if active else None,  # retour à la moyenne
            min(abs(z) / 1.5 * 4, 6) if active else None, "jamais seul — requiert D2/D3")

    carry = inputs.get("carry_net")
    if carry is None:
        add(4, "Carry / UIP", "D2+D4", "1-3 sem", "|signal| > 2.0 après gate", None, None, None, None, "intrants absents")
    else:
        signal = carry * regime.carry_mult  # le gate s'applique AVANT le seuil
        active = abs(signal) > 2.0
        add(4, "Carry / UIP", "D2+D4", "1-3 sem", "|signal| > 2.0 après gate", signal, active,
            _direction(signal) if active else None,
            min(abs(signal) / 2.0 * 5, 8) if active else None,
            f"gate D4 {regime.tier} ×{regime.carry_mult} — surveiller en continu")

    d = inputs.get("cycle_div_delta")
    turn = inputs.get("leading_turn") or 0.0
    if d is None:
        add(5, "Cycle Divergence", "D1", "4-8 sem", "|δ| > 0.5", None, None, None, None, "intrants absents")
    else:
        active = abs(d) > 0.5
        timing_factor = 1.0 + 0.3 * abs(turn)
        add(5, "Cycle Divergence", "D1", "4-8 sem", "|δ| > 0.5", d, active,
            _direction(d) if active else None,
            min(abs(d) / 0.5 * 4 * timing_factor, 7) if active else None,
            f"timing_quality {'élevé' if abs(turn) > 0.5 else 'faible'} (tf ×{timing_factor:.2f})")

    z = inputs.get("rr_zscore")
    momentum = inputs.get("spot_momentum")
    if z is None or momentum is None:
        add(6, "Risk Reversal", "D4", "1-3 sem", "|z| > 1.5 ET divergence > 0", None, None, None, None, "intrants absents")
    else:
        divergence = abs(z) - abs(momentum)
        active = abs(z) > 1.5 and divergence > 0  # SEUL arbitrage à 2 conditions
        extreme = abs(z) > 2.0
        add(6, "Risk Reversal", "D4", "1-3 sem", "|z| > 1.5 ET divergence > 0", z, active,
            _direction(z) if active else None,
            min(abs(z) / 1.5 * 4, 6) if active else None,
            ("sentiment_extreme — risque contrarian · " if extreme else "")
            + f"boucle carry → D4 {regime.tier}")

    return arbs


def compute_pipeline(regime_tier: str, raws: dict[str, Any]) -> S2Pipeline:
    """Assemble the full visible pipeline from mock-simulated N1/N2A outputs."""
    def val(key):
        raw = raws.get(key)
        if raw is None or raw.get("value") is None:
            return None
        v = raw["value"]
        return None if isinstance(v, float) and math.isnan(v) else float(v)

    vix = val("vix")
    regime = make_regime(regime_tier, vix, None)  # kurtosis feed absent -> None, honest
    quadrant = classify_quadrant(val("g_momentum"), val("pi_momentum"))
    d_scores = {k: val(k.lower()) for k in ("D1", "D2", "D3", "D4", "D5")}
    flux1 = compute_flux1(d_scores, quadrant, regime)
    arb_inputs = {k: val(k) for k in ("taylor_ois_delta", "phillips_tips_delta", "beer_z",
                                      "carry_net", "cycle_div_delta", "leading_turn",
                                      "rr_zscore", "spot_momentum")}
    arbitrages = compute_arbitrages(arb_inputs, regime)
    return S2Pipeline(regime=regime, quadrant=quadrant, flux1=flux1, arbitrages=arbitrages)
