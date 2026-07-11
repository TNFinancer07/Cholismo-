"""Phase 0 — DETERMINISTIC rules engine (CLAUDE §2.2). The lock is pure boolean code.

Fail-closed: any dependency down, slow or ABSENT -> BLOCKED. An LLM (Groq) may attach an
ADVISORY string next to the verdict but can never open or close the lock. The UI only
reflects this verdict, it can never override it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import config
from .meta import Freshness
from .schema import (ContextSchema, Phase0Blocker, Phase0State, SessionMarker)


@dataclass(frozen=True)
class RuleResult:
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Rule:
    name: str
    label: str                       # French UI label
    severity: str                    # CRIT blocks, WARN displays only
    predicate: Callable[["Phase0Input"], RuleResult]


@dataclass
class Phase0Input:
    schema: ContextSchema
    streak: int
    streak_audit_acked: bool
    redis_up: bool
    engine_heartbeat_age: Optional[float]
    now: float


def _rule_redis_up(i: Phase0Input) -> RuleResult:
    return RuleResult(i.redis_up, "" if i.redis_up else "Redis injoignable — dépendance down")


def _rule_engine_fresh(i: Phase0Input) -> RuleResult:
    if i.engine_heartbeat_age is None:
        return RuleResult(False, "Moteur jamais démarré")
    ok = i.engine_heartbeat_age <= config.ENGINE_HEARTBEAT_MAX_AGE
    return RuleResult(ok, "" if ok else f"Heartbeat moteur périmé ({i.engine_heartbeat_age:.1f}s)")


def _rule_data_fresh(i: Phase0Input) -> RuleResult:
    """All fast-channel critical fields must exist (not ABSENT). Source cut -> BLOCKED."""
    s1, bridge = i.schema.s1_state, i.schema.bridge_variables
    critical = {
        "svs_score": s1.svs_score, "chop": s1.chop, "cvd": s1.order_flow.cvd,
        "gex": bridge.gex, "vix": i.schema.s2_state.cascade.vix,
    }
    missing = [k for k, m in critical.items() if m.freshness == Freshness.ABSENT]
    if missing:
        return RuleResult(False, "Données absentes : " + ", ".join(missing))
    return RuleResult(True)


def _rule_vix(i: Phase0Input) -> RuleResult:
    m = i.schema.s2_state.cascade.vix
    if m.value is None:
        return RuleResult(False, "VIX absent — fail-closed")
    ok = float(m.value) <= config.VIX_CRIT
    return RuleResult(ok, "" if ok else f"VIX {float(m.value):.1f} > {config.VIX_CRIT:.0f}")


def _rule_chop(i: Phase0Input) -> RuleResult:
    m = i.schema.s1_state.chop
    if m.value is None:
        return RuleResult(False, "CHOP absent — fail-closed")
    ok = float(m.value) < config.CHOP_CRIT
    return RuleResult(ok, "" if ok else f"CHOP {float(m.value):.1f} ≥ {config.CHOP_CRIT}")


def _rule_session(i: Phase0Input) -> RuleResult:
    ok = i.schema.session_identity.session_marker != SessionMarker.HORS_SESSION
    return RuleResult(ok, "" if ok else "Hors fenêtre de session (Londres obs / overlap NY)")


def _rule_streak(i: Phase0Input) -> RuleResult:
    if i.streak < config.STREAK_AUDIT_THRESHOLD:
        return RuleResult(True)
    if i.streak_audit_acked:
        return RuleResult(True)
    return RuleResult(False, f"Streak {i.streak} ≥ {config.STREAK_AUDIT_THRESHOLD} — audit forcé non acquitté (C2)")


CRIT_RULES: list[Rule] = [
    Rule("REDIS_UP", "Dépendances up", "CRIT", _rule_redis_up),
    Rule("ENGINE_FRESH", "Moteur de règles frais", "CRIT", _rule_engine_fresh),
    Rule("DATA_FRESH", "Données critiques présentes", "CRIT", _rule_data_fresh),
    Rule("VIX_LIMIT", "VIX ≤ 30", "CRIT", _rule_vix),
    Rule("CHOP_LIMIT", "CHOP < 61.8", "CRIT", _rule_chop),
    Rule("SESSION_WINDOW", "Fenêtre de session", "CRIT", _rule_session),
    Rule("STREAK_AUDIT", "Audit streak (seuil 8)", "CRIT", _rule_streak),
]


def _warn_rms(i: Phase0Input, rms: Optional[float]) -> Optional[Phase0Blocker]:
    if rms is None:
        return None
    if rms >= config.RMS_CRIT:
        return Phase0Blocker(rule="RMS_LIMIT", label="RMS critique",
                             detail=f"RMS {rms:.1f} ≥ {config.RMS_CRIT:.0f}", severity="CRIT")
    if rms >= config.RMS_WARN:
        return Phase0Blocker(rule="RMS_WARN", label="RMS élevé",
                             detail=f"RMS {rms:.1f} ≥ {config.RMS_WARN:.0f}", severity="WARN")
    return None


def evaluate_phase0(i: Phase0Input, rms: Optional[float]) -> tuple[Phase0State, list[Phase0Blocker], list[Phase0Blocker]]:
    """Pure, deterministic, fail-closed. Returns (state, blockers, warnings)."""
    blockers: list[Phase0Blocker] = []
    warnings: list[Phase0Blocker] = []
    for rule in CRIT_RULES:
        try:
            result = rule.predicate(i)
        except Exception as exc:  # any evaluation failure -> fail-closed (CLAUDE §2.4)
            result = RuleResult(False, f"Erreur d'évaluation ({type(exc).__name__}) — fail-closed")
        if not result.passed:
            blockers.append(Phase0Blocker(rule=rule.name, label=rule.label,
                                          detail=result.detail, severity="CRIT"))
    rms_flag = _warn_rms(i, rms)
    if rms_flag is not None:
        (blockers if rms_flag.severity == "CRIT" else warnings).append(rms_flag)
    state = Phase0State.OPEN if not blockers else Phase0State.BLOCKED
    return state, blockers, warnings
