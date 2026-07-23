"""Projections over the append-only event store (PRD §Zone D).

'Current state' of a decision = replay of its events. Nothing here writes anything.
The two C4 gauges are computed by INDEPENDENT projections — no API can validate one
through the other (D-010): the impossibility is structural.
"""
from __future__ import annotations

import math
from typing import Any

from . import config
from .event_store import EventStore


def decision_log(store: EventStore, limit: int = 200) -> list[dict[str, Any]]:
    """Blotter projection: each decision joined with its outcome/recon events."""
    decisions = store.events("DecisionEvent")
    outcomes = store.events("OutcomeEvent")
    recons = store.events("ReconEvent")
    outcome_by_ref = {o.get("decision_id"): o for o in outcomes}
    recon_by_ref: dict[str, dict] = {}
    unmatched_fills = []
    for r in recons:
        ref = r.get("decision_id")
        if ref:
            recon_by_ref[ref] = r
        else:
            unmatched_fills.append(r)
    rows = []
    for d in reversed(decisions[-limit:]):
        outcome = outcome_by_ref.get(d["id"])
        recon = recon_by_ref.get(d["id"])
        rows.append({
            "id": d["id"], "ts": d["ts"], "operator": d.get("operator"),
            "instrument": d.get("instrument"), "decision": d.get("decision"),
            "signal_score": d.get("signal_score"), "degraded": d.get("degraded"),
            "reason": d.get("reason"),
            "cognitive_selfcheck": d.get("cognitive_selfcheck") is not None,
            "schema_snapshot_ref": d.get("schema_snapshot_ref"),
            "outcome": None if not outcome else {
                "outcome": outcome.get("outcome"), "error_type": outcome.get("error_type"),
                "r_multiple": outcome.get("r_multiple"), "ts": outcome["ts"]},
            "recon": None if not recon else {
                "matched": recon.get("matched"), "fill_source": recon.get("fill_source"),
                "ts": recon["ts"]},
        })
    return rows


def unmatched_fills(store: EventStore) -> list[dict[str, Any]]:
    return [r for r in store.events("ReconEvent") if not r.get("decision_id")]


def loss_streak(store: EventStore) -> int:
    """Consecutive losses, most recent outcomes first."""
    outcomes = store.events("OutcomeEvent")
    streak = 0
    for o in reversed(outcomes):
        if o.get("outcome") == "LOSS":
            streak += 1
        else:
            break
    return streak


def _reconciled_r_multiples(store: EventStore) -> list[float]:
    """r_multiples of outcomes whose decision has a matched=true ReconEvent (D-013)."""
    matched_ids = {r.get("decision_id") for r in store.events("ReconEvent")
                   if r.get("matched") and r.get("decision_id")}
    rs = []
    for o in store.events("OutcomeEvent"):
        if o.get("decision_id") in matched_ids and o.get("r_multiple") is not None:
            rs.append(float(o["r_multiple"]))
    return rs


def walk_forward(store: EventStore) -> dict[str, Any]:
    """Walk-Forward robustness (D-043) sur les R-multiples RÉCONCILIÉS, dans l'ordre chronologique
    (event store append-only). Analyse OFFLINE de recherche — HORS ContextSchema live (§1). Renvoie
    la projection typée du `WalkForwardEngine` (verdict, WFE, fenêtres). Données insuffisantes →
    INSUFFICIENT_DATA (jamais un faux nombre autoritaire §8)."""
    from .walk_forward import WalkForwardEngine
    rs = _reconciled_r_multiples(store)
    engine = WalkForwardEngine(is_frac=config.WF_IS_FRAC, window=config.WF_WINDOW,
                               step=config.WF_STEP, threshold=config.WF_OVERFIT_THRESHOLD,
                               min_trades=config.WF_MIN_TRADES)
    return engine.run(rs).model_dump()


def monte_carlo(store: EventStore) -> dict[str, Any]:
    """Monte Carlo du Max Drawdown (D-043 tranche 2) sur les R-multiples RÉCONCILIÉS. Analyse
    OFFLINE de recherche — HORS ContextSchema live (§1). Seuil testé = `risk.max_drawdown_r_day`
    (réglage, source unique). Données insuffisantes → INSUFFICIENT_DATA (jamais fabriqué §8)."""
    from . import settings
    from .monte_carlo import MonteCarloSimulator
    rs = _reconciled_r_multiples(store)
    threshold = float(settings.value("risk.max_drawdown_r_day"))
    sim = MonteCarloSimulator(n_sims=config.MC_N_SIMS, threshold=threshold,
                              min_trades=config.MC_MIN_TRADES, seed=config.MC_SEED)
    return sim.run(rs).model_dump()


def sharpe(store: EventStore) -> dict[str, Any]:
    """Per-trade Sharpe = mean(r)/stdev(r), reconciled outcomes only.
    Result score is displayed ONLY after 20+ trades (CLAUDE §2.7)."""
    rs = _reconciled_r_multiples(store)
    n = len(rs)
    if n < 2:
        return {"n": n, "sharpe": None, "displayable": False,
                "min_trades": config.RESULT_SCORE_MIN_TRADES}
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / (n - 1)
    std = math.sqrt(var)
    value = None if std == 0 else round(mean / std, 3)
    return {"n": n, "sharpe": value, "displayable": n >= config.RESULT_SCORE_MIN_TRADES,
            "min_trades": config.RESULT_SCORE_MIN_TRADES}


def calibration(store: EventStore, streak_audit_acked: bool) -> dict[str, Any]:
    """C4 — two DISTINCT gauges (quantitative + behavioral), computed independently."""
    decisions = store.events("DecisionEvent")
    gos = [d for d in decisions if d.get("decision") == "GO"]
    recons = store.events("ReconEvent")
    matched_ids = {r.get("decision_id") for r in recons if r.get("matched") and r.get("decision_id")}
    sharpe_info = sharpe(store)
    n_reconciled = len(_reconciled_r_multiples(store))

    # Quantitative gauge: reconciled trade count vs N/60 window, 50+ target, Sharpe sign.
    quant = {
        "n_trades": n_reconciled,
        "window": config.CALIBRATION_WINDOW,
        "target": config.CALIBRATION_TARGET_TRADES,
        "progress_pct": round(100.0 * min(n_reconciled, config.CALIBRATION_WINDOW) / config.CALIBRATION_WINDOW, 1),
        "sharpe": sharpe_info["sharpe"] if sharpe_info["displayable"] else None,
        "sharpe_displayable": sharpe_info["displayable"],
        "valid": n_reconciled >= config.CALIBRATION_TARGET_TRADES
                 and sharpe_info["displayable"]
                 and (sharpe_info["sharpe"] or 0) > 0,
    }

    # Behavioral gauge: discipline proven by events, not by will (CLAUDE §2.6).
    go_with_selfcheck = sum(1 for d in gos if d.get("cognitive_selfcheck") is not None)
    go_reconciled = sum(1 for d in gos if d["id"] in matched_ids)
    timeouts = sum(1 for d in decisions if d.get("reason") == "timeout")
    selfcheck_rate = None if not gos else round(100.0 * go_with_selfcheck / len(gos), 1)
    recon_rate = None if not gos else round(100.0 * go_reconciled / len(gos), 1)
    behavioral = {
        "n_decisions": len(decisions),
        "n_go": len(gos),
        "selfcheck_rate_pct": selfcheck_rate,
        "recon_rate_pct": recon_rate,
        "timeouts": timeouts,
        "streak_audit_acked": streak_audit_acked,
        "valid": bool(gos) and selfcheck_rate == 100.0 and recon_rate == 100.0,
    }

    sizing_locked = not (quant["valid"] and behavioral["valid"])
    return {
        "quantitative": quant,
        "behavioral": behavioral,
        "sizing_locked": sizing_locked,
        "sizing_pct": config.SIZING_LOCK_PCT if sizing_locked else 100,
    }
