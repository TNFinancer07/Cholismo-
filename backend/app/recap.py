"""RECAP — the session cockpit projection (brainstorm « Récapitulatif », D-023).

One deterministic pass over the append-only stores + the live schema. Answers the three
questions of the cockpit at once: am I winning? (P&L), what is running? (modules), what
market am I in? (weather/windows). Nothing here writes anything; nothing here invents a
number — data missing means an explicit null, never a fake value (CLAUDE §2.3).

Two-tier display contract (brainstorm tension 01): the payload separates the REFLEX
level (pnl, risk, weather, windows — readable < 3 s) from the ANALYSIS level (gauges,
equity, split, modules, agents) that the UI folds away.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import config, journal, settings
from .event_store import EventStore
from .meta import Freshness
from .orchestrator import orchestrator_payload
from .schema import ContextSchema, Phase0State
from .strategies.sony import MR_WINDOW, SVS_WINDOW

MTL = ZoneInfo("America/Montreal")
GRANULARITIES = ("session", "week", "month")  # session = today (single-day sessions)


def _since_ts(granularity: str, now: float) -> float:
    local = datetime.fromtimestamp(now, tz=MTL)
    if granularity == "week":
        start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0,
                                                                  second=0, microsecond=0)
    elif granularity == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # session/day
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


def _pnl(trades: list[dict[str, Any]], r_unit_usd: float) -> dict[str, Any]:
    rs = [float(t.get("resultat_r") or 0.0) for t in trades]
    equity: list[float] = []
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cumulative = round(cumulative + r, 4)
        equity.append(cumulative)
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    wins = sum(1 for r in rs if r > 0)
    losses = sum(1 for r in rs if r < 0)
    r_total = round(cumulative, 2)
    return {
        "n_trades": len(rs),
        "r_total": r_total,
        "usd": round(r_total * r_unit_usd, 2),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100.0 * wins / len(rs), 1) if rs else None,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "drawdown_r": round(max_dd, 2),
        "equity_curve": equity[-120:],
    }


def _risk(trades_today: list[dict[str, Any]], store: EventStore) -> dict[str, Any]:
    max_r = float(settings.value("risk.max_r_per_session"))
    max_dd = float(settings.value("risk.max_drawdown_r_day"))
    loss_rs = [abs(float(t.get("resultat_r") or 0.0)) for t in trades_today
               if float(t.get("resultat_r") or 0.0) < 0]
    consumed = round(sum(loss_rs), 2)
    remaining = round(max(0.0, max_r - consumed), 2)
    avg_loss = round(sum(loss_rs) / len(loss_rs), 3) if loss_rs else None
    # Risk-clock (brainstorm idée ✦): remaining « play time » at the CURRENT loss size —
    # honest null while no loss has defined the rhythm yet.
    trades_left = int(remaining // avg_loss) if avg_loss else None
    return {
        "max_r": max_r,
        "max_drawdown_r_day": max_dd,
        "consumed_r": consumed,
        "remaining_r": remaining,
        "consumed_pct": round(100.0 * min(consumed, max_r) / max_r, 1) if max_r else None,
        "avg_loss_r": avg_loss,
        "risk_clock_trades_left": trades_left,
        "lockout": journal.derive_lockout(store),
    }


def _strategy_split(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}
    for t in trades:
        sid = t.get("strategy_id") or "?"
        slot = acc.setdefault(sid, {"strategy_id": sid,
                                    "label": journal.STRATEGIES.get(sid, {}).get("label", sid),
                                    "accent": journal.STRATEGIES.get(sid, {}).get("accent", ""),
                                    "n_trades": 0, "r_total": 0.0})
        slot["n_trades"] += 1
        slot["r_total"] = round(slot["r_total"] + float(t.get("resultat_r") or 0.0), 2)
    return sorted(acc.values(), key=lambda s: s["strategy_id"])


def _window_state(window: tuple[tuple[int, int], tuple[int, int]], now: float) -> dict[str, Any]:
    """Session clock (brainstorm ✦ compte à rebours) — deterministic Montréal clock."""
    local = datetime.fromtimestamp(now, tz=MTL)
    (h1, m1), (h2, m2) = window
    start = local.replace(hour=h1, minute=m1, second=0, microsecond=0)
    end = local.replace(hour=h2, minute=m2, second=0, microsecond=0)
    if local < start:
        return {"state": "AVANT", "opens_in_s": int((start - local).total_seconds()),
                "closes_in_s": None}
    if local < end:
        return {"state": "OUVERTE", "opens_in_s": None,
                "closes_in_s": int((end - local).total_seconds())}
    next_start = start + timedelta(days=1)
    return {"state": "FERMÉE", "opens_in_s": int((next_start - local).total_seconds()),
            "closes_in_s": None}


def _weather(schema: ContextSchema, rms: Optional[float]) -> dict[str, Any]:
    """Feu météo (brainstorm ✦) — single synthesis, SAME deterministic arbitration as
    the orchestrator console (PRD §Console): no second source of truth."""
    console = orchestrator_payload(schema, rms)
    reasons = [f"{name} : {src['detail']}" for name, src in console["sources"].items()
               if src["level"] != "VERT"]
    return {"level": console["risk_level"], "action": console["action"],
            "reasons": reasons[:4]}


def _modules(schema: ContextSchema, extras: dict[str, Any]) -> list[dict[str, Any]]:
    """Status grid — every state carries its explicit reason (« un état muet = un état
    dangereux ») and the failing gate answers « pourquoi pas de signal ? » in one look."""
    modules: list[dict[str, Any]] = []

    si = schema.session_identity
    blocked = si.phase0 == Phase0State.BLOCKED
    modules.append({
        "id": "phase0", "label": "Phase 0 (moteur de règles)",
        "state": "BLOQUÉ" if blocked else "ARMÉ",
        "reason": (" · ".join(b.label for b in si.phase0_blockers[:3]) or "règle non précisée")
                  if blocked else "toutes règles au vert",
    })

    strategies = schema.s1_state.strategies
    for sid, strat in (("SVS", strategies.svs if strategies else None),
                       ("MEAN_REVERSION", strategies.mean_reversion if strategies else None)):
        if strat is None:
            modules.append({"id": sid, "label": sid, "state": "MUET",
                            "reason": "stratégies non évaluées (moteur muet)"})
            continue
        failing = [g for g in strat.gates if g.status in ("FAIL", "ABSENT")]
        modules.append({
            "id": sid, "label": strat.label, "state": "ÉLIGIBLE" if strat.eligible else "BLOQUÉE",
            "reason": ("fenêtre + filtres au vert" if strat.eligible
                       else " · ".join(f"{g.name} : {g.detail or g.status}" for g in failing[:2])
                       or "hors fenêtre"),
            "gates": [{"name": g.name, "status": g.status, "detail": g.detail}
                      for g in strat.gates],
            "sizing_pct": strat.sizing_pct,
        })

    macro = schema.s2_state.s2_macro_score
    modules.append({
        "id": "macro_a3", "label": "Score macro S2 (A3)",
        "state": "CALIBRÉ" if macro.calibrated else "NON CALIBRÉ",
        "reason": ("contribue 20 % au signal" if macro.calibrated
                   else "poids macro → 0, signal renormalisé /80 (CLAUDE §8.1)"),
    })

    rms = extras.get("rms")
    modules.append({
        "id": "rms", "label": "RMS (5 couches)",
        "state": "ABSENT" if rms is None else
                 "CRITIQUE" if rms >= config.RMS_CRIT else
                 "SURVEILLANCE" if rms >= config.RMS_WARN else "ARMÉ",
        "reason": "fail-closed — donnée RMS absente" if rms is None
                  else f"niveau {rms:.1f} (warn ≥ {config.RMS_WARN:.0f}, crit ≥ {config.RMS_CRIT:.0f})",
    })
    return modules


def _agents(store: EventStore, now: float) -> list[dict[str, Any]]:
    """Pouls des agents IA — last heartbeat per provider from the ai_calls log."""
    latest: dict[str, dict[str, Any]] = {}
    for call in store.ai_calls(limit=100):
        latest.setdefault(call["provider"], call)  # ai_calls is DESC — first hit is latest
    out = []
    for provider in ("groq", "claude", "gemini"):
        call = latest.get(provider)
        if call is None:
            out.append({"provider": provider, "state": "SILENCIEUX",
                        "detail": "aucun appel loggé", "age_s": None, "latency_ms": None})
            continue
        age = now - call["ts"]
        status = str(call["status"])
        state = ("OK" if status == "OK" and age < 600 else
                 "INACTIF" if status.startswith("SKIPPED") else
                 "DÉGRADÉ")
        out.append({"provider": provider, "state": state, "detail": status,
                    "age_s": round(age, 1), "latency_ms": call.get("latency_ms")})
    return out


def recap_payload(store: EventStore, schema: ContextSchema, extras: dict[str, Any],
                  granularity: str = "session", now: Optional[float] = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    if granularity not in GRANULARITIES:
        granularity = "session"
    since = _since_ts(granularity, now)
    all_trades = store.journal_entries("trade_locked")
    trades = [t for t in all_trades if t["ts"] >= since]
    today = [t for t in all_trades if t["ts"] >= _since_ts("session", now)]
    r_unit = float(settings.value("risk.r_unit_usd"))

    return {
        "granularity": granularity,
        "granularities": list(GRANULARITIES),
        "generated_ts": now,
        "r_unit_usd": r_unit,
        # -- niveau réflexe --
        "pnl": _pnl(trades, r_unit),
        "risk": _risk(today, store),
        "weather": _weather(schema, extras.get("rms")),
        "windows": {"svs": _window_state(SVS_WINDOW, now),
                    "mean_reversion": _window_state(MR_WINDOW, now)},
        # -- niveau analyse --
        "strategy_split": _strategy_split(trades),
        "modules": _modules(schema, extras),
        "agents": _agents(store, now),
        "signal_degraded": schema.unified_signal_output.degraded,
        "gex_absent": schema.bridge_variables.gex.freshness == Freshness.ABSENT,
    }
