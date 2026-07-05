"""Sony — the two REAL execution strategies (AUTORITÉ: reference/sony/*, see MANIFEST).

1. SVS — Structural Vacuum Squeeze (breakout LVN, 09h30-11h00, score >= 88 ajusté).
2. Mean Reversion — Piège d'Absorption v5.8 (15h30-17h00, score >= 80, CI > 61.8 requis).

Only gates whose data actually exists in the schema are evaluated (PASS/FAIL/ABSENT);
gates without a wired source are surfaced as MANUAL — never invented (CLAUDE §2.3).
Score computation itself stays with the operator/upstream tools; the terminal shows
ELIGIBILITY and the sizing modifiers, deterministically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..meta import Freshness
from ..schema import (ExecutionStrategy, S1State, S1Strategies, SessionMarker,
                      StrategyGate)

MTL = ZoneInfo("America/Montreal")

# --- AUTORITÉ thresholds (reference/sony) ---
CHOP_BLOCKING = 61.8            # SVS filtre 1B (>= blocks) ; MR gate G4 (<= blocks)
VIX_SUSPEND = 30.0              # both strategies: session suspended above 30
SVS_WINDOW = ((9, 30), (11, 0))   # prime 09h30-11h00 (heure locale Montréal)
MR_WINDOW = ((15, 30), (17, 0))   # créneau optimal 15h30-17h00 (ouverture cash US)


def _vix_sizing_tier(vix: float) -> tuple[float, str]:
    """SVS §8 — VIX-tiered sizing (% of calibration size)."""
    if vix < 15:
        return 100.0, "VIX < 15 → 100 %"
    if vix <= 20:
        return 75.0, "VIX 15-20 → 75 %"
    if vix <= 30:
        return 50.0, "VIX 20-30 → 50 % (stop élargi autorisé)"
    return 0.0, "VIX > 30 → session suspendue"


def _mr_vix_modifier(vix: float) -> tuple[float, str]:
    """MR §2 — modificateur VIX multiplicatif."""
    if vix < 15:
        return 1.0, "VIX < 15 → ×1.0"
    if vix <= 20:
        return 0.75, "VIX 15-20 → ×0.75"
    if vix <= 30:
        return 0.50, "VIX 20-30 → ×0.50"
    return 0.0, "VIX > 30 → suspendu (CircuitBreaker)"


def _mr_ci_buffer(chop: float) -> Optional[tuple[int, str]]:
    """MR §2 — SL buffer calibrated on the Choppiness Index (G4 must PASS first)."""
    if chop > 90:
        return 2, "CI > 90 consolidation extrême → buffer 2 ticks"
    if chop >= 75:
        return 5, "CI 75-90 range actif large → buffer 5 ticks"
    if chop > CHOP_BLOCKING:
        return 3, "CI 61.8-75 range standard → buffer 3 ticks"
    return None


def _window_band(now_ts: float, window: tuple[tuple[int, int], tuple[int, int]]) -> tuple[str, float]:
    """Distance to the strategy window in minutes (0 = inside). Local Montréal clock."""
    local = datetime.fromtimestamp(now_ts, tz=MTL)
    minutes = local.hour * 60 + local.minute
    start = window[0][0] * 60 + window[0][1]
    end = window[1][0] * 60 + window[1][1]
    if start <= minutes <= end:
        return "FENÊTRE", 0.0
    distance = min(abs(minutes - start), abs(minutes - end))
    return ("TAMPON" if distance <= 30 else "ZONE MORTE"), float(distance)


def _values(s1: S1State) -> dict[str, Optional[float | bool]]:
    def val(meta):
        if meta.freshness == Freshness.ABSENT or meta.value is None:
            return None
        return meta.value
    return {"chop": val(s1.chop), "absorption": val(s1.order_flow.absorption)}


def evaluate_svs(s1: S1State, vix: Optional[float], session_marker: SessionMarker,
                 now_ts: float) -> ExecutionStrategy:
    v = _values(s1)
    gates: list[StrategyGate] = []

    band, _ = _window_band(now_ts, SVS_WINDOW)
    if session_marker == SessionMarker.OVERLAP_NY and band != "FENÊTRE":
        # Scenario simulates the session (D-020): treat simulated NY overlap as prime.
        band = "FENÊTRE"
    malus = {"FENÊTRE": 0, "TAMPON": -3, "ZONE MORTE": -7}[band]
    gates.append(StrategyGate(
        name="Fenêtre prime 09h30-11h00", status="PASS" if band == "FENÊTRE" else "FAIL",
        detail=f"{band} (malus {malus}, seuil brut requis {88 - malus})"))

    chop = v["chop"]
    if chop is None:
        gates.append(StrategyGate(name="Filtre 1B — CHOP < 61.8", status="ABSENT",
                                  detail="CHOP absent — fail-closed"))
    else:
        ok = float(chop) < CHOP_BLOCKING
        gates.append(StrategyGate(name="Filtre 1B — CHOP < 61.8",
                                  status="PASS" if ok else "FAIL",
                                  detail=f"CHOP(14) = {float(chop):.1f}"))

    if v["absorption"] is None:
        gates.append(StrategyGate(name="Filtre 2 — divergence de flux", status="ABSENT",
                                  detail="absorption non lue — fail-closed"))
    else:
        absorbed = bool(v["absorption"])
        gates.append(StrategyGate(name="Filtre 2 — divergence de flux",
                                  status="FAIL" if absorbed else "PASS",
                                  detail="absorption active sur le footprint" if absorbed else "pas d'absorption contraire"))

    sizing: Optional[float] = None
    if vix is None:
        gates.append(StrategyGate(name="Filtre 5 — régime VIX", status="ABSENT",
                                  detail="VIX absent — fail-closed"))
    else:
        suspended = vix > VIX_SUSPEND
        tier_pct, tier_note = _vix_sizing_tier(vix)
        gates.append(StrategyGate(name="Filtre 5 — régime VIX",
                                  status="FAIL" if suspended else "PASS",
                                  detail=f"VIX {vix:.1f} — {tier_note}"))
        session_mult = {"FENÊTRE": 1.0, "TAMPON": 0.75, "ZONE MORTE": 0.50}[band]
        sizing = round(tier_pct * session_mult, 1)

    # Gates whose sources are not wired into the terminal yet — surfaced, never guessed.
    for name, detail in (
        ("Filtre 1A — obstacle < 8 ticks", "Volume Profile non câblé"),
        ("Filtre 3 — news Tier 1 ±30 min", "calendrier macro non câblé"),
        ("Filtre 4 — corr NQ/ES ≥ +0.40", "corrélation rolling non câblée"),
    ):
        gates.append(StrategyGate(name=name, status="MANUAL", detail=detail))

    eligible = all(g.status == "PASS" for g in gates if g.status in ("PASS", "FAIL", "ABSENT"))
    return ExecutionStrategy(
        strategy_id="SVS", label="SVS — Structural Vacuum Squeeze",
        version="scoring v2.0 · CHOP intégré", window="09h30-11h00 · ES/corrélat NQ",
        score_threshold="score ajusté ≥ 88/100 · planchers C1 26/35 · C2 19/25 · C3 13/20 · C4 10/15 · C5 3/5",
        eligible=eligible, sizing_pct=sizing if eligible else 0.0, gates=gates,
        reference="reference/sony/SVS_System_Prompt_3.html")


def evaluate_mean_reversion(s1: S1State, vix: Optional[float],
                            now_ts: float) -> ExecutionStrategy:
    v = _values(s1)
    gates: list[StrategyGate] = []

    band, _ = _window_band(now_ts, MR_WINDOW)
    penalty = {"FENÊTRE": 0, "TAMPON": -5, "ZONE MORTE": -8}["FENÊTRE" if band == "FENÊTRE" else
                                                             "TAMPON" if band == "TAMPON" else "ZONE MORTE"]
    effective = 80 if band == "FENÊTRE" else 89
    gates.append(StrategyGate(
        name="Créneau 15h30-17h00 (floor 4b²)",
        status="PASS" if band == "FENÊTRE" else "FAIL",
        detail=f"{band} — pénalité {penalty}, seuil effectif {effective}, cap 1 hors-fenêtre/sem, taille ×0.75"))

    gates.append(StrategyGate(name="G1 — news High Impact 30 min", status="MANUAL",
                              detail="Forex Factory non câblé"))
    gates.append(StrategyGate(name="G2 — prix hors VWAP ±1σ", status="MANUAL",
                              detail="VWAP non câblé"))

    chop = v["chop"]
    buffer_note = ""
    if chop is None:
        gates.append(StrategyGate(name="G4 — CI > 61.8", status="ABSENT",
                                  detail="CHOP absent — fail-closed"))
    else:
        buffer = _mr_ci_buffer(float(chop))
        if buffer is None:
            gates.append(StrategyGate(name="G4 — CI > 61.8", status="FAIL",
                                      detail=f"CI = {float(chop):.1f} — mean reversion non viable (marché directionnel)"))
        else:
            buffer_note = buffer[1]
            gates.append(StrategyGate(name="G4 — CI > 61.8", status="PASS",
                                      detail=f"CI = {float(chop):.1f} — {buffer[1]}"))

    gates.append(StrategyGate(name="G3 — SL défini avant l'entrée", status="MANUAL",
                              detail=buffer_note or "buffer CI inconnu tant que G4 n'a pas statué"))

    sizing: Optional[float] = None
    if vix is None:
        gates.append(StrategyGate(name="Modificateur VIX", status="ABSENT",
                                  detail="VIX absent — fail-closed"))
    else:
        mult, note = _mr_vix_modifier(vix)
        gates.append(StrategyGate(name="Modificateur VIX",
                                  status="FAIL" if mult == 0.0 else "PASS",
                                  detail=f"VIX {vix:.1f} — {note}"))
        session_mult = 1.0 if band == "FENÊTRE" else 0.75
        sizing = round(100.0 * mult * session_mult, 1)

    gates.append(StrategyGate(name="Backwardation VIX9D ≥ VIX", status="ABSENT",
                              detail="VIX9D non câblé — mode ultra-sélectif (seuil 95) non évaluable"))

    eligible = all(g.status == "PASS" for g in gates if g.status in ("PASS", "FAIL", "ABSENT"))
    return ExecutionStrategy(
        strategy_id="MEAN_REVERSION", label="Mean Reversion — Piège d'Absorption",
        version="v5.8 · Bookmap natif", window="15h30-17h00 · ouverture cash US",
        score_threshold="score ≥ 80/100 · planchers S 21/30 · O 17/25 · M 15/25 · T 10/15 · 1 %/trade · 2 %/jour",
        eligible=eligible, sizing_pct=sizing if eligible else 0.0, gates=gates,
        reference="reference/sony/strategie2_mean_reversion_v5_afternoon.html")


def evaluate_strategies(s1: S1State, vix: Optional[float], session_marker: SessionMarker,
                        now_ts: float) -> S1Strategies:
    return S1Strategies(
        svs=evaluate_svs(s1, vix, session_marker, now_ts),
        mean_reversion=evaluate_mean_reversion(s1, vix, now_ts),
    )
