"""Orchestrator console (PRD §Console) — DETERMINISTIC arbitration over 6 sources.

SVS · S1 · News · RMS · WS · Youssef -> risk level (VERT/JAUNE/ROUGE) + action ->
real-time JSON payload. Fail-closed rules (CLAUDE §2.4):
  ROUGE + conflicting signals -> BLOCK_ENTRY
  ROUGE without a defined action -> REQUEST_ACK (no trade without explicit human ack)
No AUTORITÉ blocks exist in /reference/ for the per-source thresholds (see MANIFEST):
the thresholds reuse the AUTORITÉ ones from config; the mapping itself is PLACEHOLDER.
"""
from __future__ import annotations

from typing import Any, Optional

from . import config
from .meta import Freshness
from .schema import ContextSchema, SyncVerdict

GREEN, YELLOW, RED = "VERT", "JAUNE", "ROUGE"


def _level_svs(schema: ContextSchema) -> tuple[str, str]:
    m = schema.s1_state.svs_score
    if m.freshness == Freshness.ABSENT or m.value is None:
        return RED, "SVS absent — fail-closed"
    v = float(m.value)
    if v < 30:
        return RED, f"SVS {v:.0f} < 30"
    if v < 50 or m.freshness == Freshness.STALE:
        return YELLOW, f"SVS {v:.0f} / fraîcheur {m.freshness.value}"
    return GREEN, f"SVS {v:.0f}"


def _level_s1(schema: ContextSchema) -> tuple[str, str]:
    m = schema.s1_state.chop
    if m.value is None:
        return RED, "CHOP absent — fail-closed"
    v = float(m.value)
    if v >= config.CHOP_CRIT:
        return RED, f"CHOP {v:.1f} ≥ {config.CHOP_CRIT}"
    if v >= 50:
        return YELLOW, f"CHOP {v:.1f}"
    return GREEN, f"CHOP {v:.1f}"


def _level_news(schema: ContextSchema) -> tuple[str, str]:
    vix = schema.s2_state.cascade.vix
    if vix.value is None:
        return RED, "VIX absent — fail-closed"
    v = float(vix.value)
    if v > config.VIX_CRIT:
        return RED, f"VIX {v:.1f} > {config.VIX_CRIT:.0f}"
    if v > 20:
        return YELLOW, f"VIX {v:.1f}"
    return GREEN, f"VIX {v:.1f}"


def _level_rms(rms: Optional[float]) -> tuple[str, str]:
    if rms is None:
        return RED, "RMS absent — fail-closed"
    if rms >= config.RMS_CRIT:
        return RED, f"RMS {rms:.1f} ≥ {config.RMS_CRIT:.0f}"
    if rms >= config.RMS_WARN:
        return YELLOW, f"RMS {rms:.1f} ≥ {config.RMS_WARN:.0f}"
    return GREEN, f"RMS {rms:.1f}"


def _level_ws(schema: ContextSchema) -> tuple[str, str]:
    verdict = schema.sync_state.verdict
    if verdict == SyncVerdict.ALIGNED:
        return GREEN, "S1↔S2 alignés"
    if verdict == SyncVerdict.PARTIAL:
        return YELLOW, "Sync partiel (donnée périmée/absente)"
    return RED, "S1↔S2 divergents"


def _level_youssef(schema: ContextSchema) -> tuple[str, str]:
    macro = schema.s2_state.s2_macro_score
    if not macro.calibrated:
        return YELLOW, "Macro NON CALIBRÉ — contribution 0"
    rr = schema.s2_state.cascade.real_rates
    if rr.value is None:
        return RED, "Taux réels absents — fail-closed"
    return GREEN, f"Taux réels {float(rr.value):.2f}"


def orchestrator_payload(schema: ContextSchema, rms: Optional[float]) -> dict[str, Any]:
    sources = {
        "SVS": _level_svs(schema), "S1": _level_s1(schema), "News": _level_news(schema),
        "RMS": _level_rms(rms), "WS": _level_ws(schema), "Youssef": _level_youssef(schema),
    }
    reds = [name for name, (level, _) in sources.items() if level == RED]
    yellows = [name for name, (level, _) in sources.items() if level == YELLOW]

    # Deterministic arbitration (AUTORITÉ rules PRD §Console):
    if reds and (yellows or len(reds) > 1):
        action, risk = "BLOCK_ENTRY", RED          # ROUGE + conflict -> block
    elif reds:
        action, risk = "REQUEST_ACK", RED          # ROUGE without defined action -> ack
    elif yellows:
        action, risk = "REQUEST_ACK" if len(yellows) >= 3 else "NONE", YELLOW
    else:
        action, risk = "NONE", GREEN

    return {
        "sources": {name: {"level": level, "detail": detail}
                    for name, (level, detail) in sources.items()},
        "risk_level": risk,
        "action": action,
        "requires_human_ack": action in ("REQUEST_ACK", "BLOCK_ENTRY"),
    }
