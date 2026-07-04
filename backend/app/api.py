"""REST + SSE API. The UI reflects state; it never overrides the deterministic locks:
every gate (Phase 0, self-check, window) is re-checked HERE, server-side.
No endpoint places an order — Go/No-Go only APPENDS a DecisionEvent (CLAUDE §2.1).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import config, projections
from .datasource import scenarios
from .datasource.mock import SOURCES
from .event_store import get_store
from .orchestrator import orchestrator_payload
from .recon import parse_ninjatrader_csv, reconcile
from .schema import Operator, Phase0State
from .sse import broadcaster

router = APIRouter()


# ---------- health / state ----------

@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    redis_up = await request.app.state.redis.ping()
    return {"status": "ok" if redis_up else "degraded", "redis": redis_up, "ts": time.time()}


@router.get("/state")
async def state(request: Request) -> dict[str, Any]:
    return request.app.state.engine.snapshot()


# ---------- SSE — cadence-segmented channels (CLAUDE §6) ----------

@router.get("/sse/{channel}")
async def sse(channel: str, request: Request) -> EventSourceResponse:
    if channel not in ("fast", "slow"):
        raise HTTPException(404, "canal inconnu (fast|slow)")
    queue = broadcaster.subscribe(channel)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                item = await queue.get()
                yield item
        finally:
            broadcaster.unsubscribe(channel, queue)

    return EventSourceResponse(stream(), ping=15)


# ---------- scenario / sources / mode (Étape 2) ----------

class ScenarioBody(BaseModel):
    name: str
    sliders: Optional[dict[str, float]] = None
    simulated_streak: Optional[int] = None
    force_session: Optional[str] = "OVERLAP_NY"  # null => real clock (D-020)


@router.get("/scenario")
async def get_scenario(request: Request) -> dict[str, Any]:
    current = scenarios.resolve(await request.app.state.redis.scenario())
    return {"current": current,
            "available": [{"name": k, "label": v["label"]} for k, v in scenarios.SCENARIOS.items()],
            "sliders": list(scenarios.SLIDER_FIELDS)}


@router.post("/scenario")
async def set_scenario(body: ScenarioBody, request: Request) -> dict[str, Any]:
    if body.name not in scenarios.SCENARIOS:
        raise HTTPException(400, f"scénario inconnu : {body.name}")
    payload: dict[str, Any] = {"name": body.name, "force_session": body.force_session}
    if body.sliders is not None:
        payload["sliders"] = body.sliders
    if body.simulated_streak is not None:
        payload["simulated_streak"] = body.simulated_streak
    await request.app.state.redis.set_scenario(payload)
    return {"ok": True, "scenario": scenarios.resolve(payload)}


@router.get("/sources")
async def get_sources(request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    return {name: {"up": await redis.source_up(name), "fields": fields}
            for name, fields in SOURCES.items()}


class SourceToggle(BaseModel):
    up: bool


@router.post("/sources/{name}/toggle")
async def toggle_source(name: str, body: SourceToggle, request: Request) -> dict[str, Any]:
    if name not in SOURCES:
        raise HTTPException(404, f"source inconnue : {name}")
    await request.app.state.redis.set_source_up(name, body.up)
    return {"ok": True, "source": name, "up": body.up}


class ModeBody(BaseModel):
    mode: str


@router.post("/mode")
async def set_mode(body: ModeBody, request: Request) -> dict[str, Any]:
    if body.mode not in ("PRE_SESSION", "LIVE", "POST_SESSION"):
        raise HTTPException(400, "mode inconnu")
    await request.app.state.redis.set_mode(body.mode)
    return {"ok": True, "mode": body.mode}


# ---------- C5 self-check (mandatory before any GO — PRD §C5) ----------

class SelfCheckBody(BaseModel):
    operator: Operator
    answers: dict[str, Any]

REQUIRED_SELFCHECK_KEYS = ("sleep_ok", "focus_ok", "no_tilt", "plan_written")


@router.post("/selfcheck")
async def post_selfcheck(body: SelfCheckBody, request: Request) -> dict[str, Any]:
    missing = [k for k in REQUIRED_SELFCHECK_KEYS if k not in body.answers]
    if missing:
        raise HTTPException(422, f"self-check incomplet : {', '.join(missing)}")
    await request.app.state.redis.set_selfcheck(body.operator.value, body.answers)
    return {"ok": True, "valid_for_seconds": config.SELF_CHECK_TTL_SECONDS}


@router.get("/selfcheck/{operator}")
async def get_selfcheck(operator: Operator, request: Request) -> dict[str, Any]:
    check = await request.app.state.redis.selfcheck(operator.value)
    return {"present": check is not None, "selfcheck": check}


# ---------- decisions (Étape 4) — APPEND ONLY, never an order ----------

class ArmBody(BaseModel):
    operator: Operator
    instrument: str = "ES"


@router.post("/decisions/arm")
async def arm_decision(body: ArmBody, request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    if await redis.decision_window():
        raise HTTPException(409, "une décision est déjà pendante")
    now = time.time()
    window = {"id": str(uuid.uuid4()), "opened_ts": now,
              "deadline_ts": now + config.ANTIPARALYSIS_SECONDS,
              "instrument": body.instrument, "armed_by": body.operator.value}
    await redis.set_decision_window(window)
    return {"ok": True, "window": window}


class DecisionBody(BaseModel):
    operator: Operator
    decision: str  # GO | NO_GO
    reason: Optional[str] = None


@router.post("/decisions")
async def post_decision(body: DecisionBody, request: Request) -> dict[str, Any]:
    if body.decision not in ("GO", "NO_GO"):
        raise HTTPException(400, "décision invalide (GO|NO_GO)")
    engine = request.app.state.engine
    redis = request.app.state.redis
    window = await redis.decision_window()
    if not window:
        raise HTTPException(409, "aucune décision pendante (fenêtre C3 fermée)")

    selfcheck = await redis.selfcheck(body.operator.value)
    if body.decision == "GO":
        # Deterministic server-side gates — the UI can never override them (CLAUDE §2.2).
        if engine.schema.session_identity.phase0 != Phase0State.OPEN:
            raise HTTPException(409, "Phase 0 BLOQUÉ — GO refusé (fail-closed)")
        if selfcheck is None:
            raise HTTPException(412, "Self-check cognitif obligatoire avant un GO (C5)")

    store = get_store()
    snapshot_ref = store.save_snapshot(engine.schema.model_dump(mode="json"))
    event = store.append("DecisionEvent", {
        "operator": body.operator.value,
        "instrument": window.get("instrument"),
        "decision": body.decision,
        "reason": body.reason,
        "signal_score": engine.schema.unified_signal_output.score,
        "degraded": engine.schema.unified_signal_output.degraded,
        "cognitive_selfcheck": (selfcheck or {}).get("answers") if body.decision == "GO" else
                               ((selfcheck or {}).get("answers")),
        "schema_snapshot_ref": snapshot_ref,
        "window_id": window.get("id"),
    })
    await redis.set_decision_window(None)
    await redis.set_decision_cooldown(30)
    broadcaster.publish("fast", "decision_log_dirty", {"ts": event["ts"]})
    return {"ok": True, "event": event, "order_placed": False}  # never an order (CLAUDE §2.1)


@router.get("/decisions")
async def get_decisions() -> dict[str, Any]:
    store = get_store()
    return {"decisions": projections.decision_log(store),
            "streak": projections.loss_streak(store)}


class OutcomeBody(BaseModel):
    decision_id: str
    outcome: str  # WIN | LOSS | SCRATCH
    error_type: Optional[str] = None  # A | B | C
    r_multiple: Optional[float] = None


@router.post("/outcomes")
async def post_outcome(body: OutcomeBody) -> dict[str, Any]:
    if body.outcome not in ("WIN", "LOSS", "SCRATCH"):
        raise HTTPException(400, "outcome invalide (WIN|LOSS|SCRATCH)")
    if body.error_type not in (None, "A", "B", "C"):
        raise HTTPException(400, "error_type invalide (A|B|C)")
    store = get_store()
    known = {d["id"] for d in store.events("DecisionEvent")}
    if body.decision_id not in known:
        raise HTTPException(404, "DecisionEvent inconnu")
    event = store.append("OutcomeEvent", {
        "decision_id": body.decision_id, "outcome": body.outcome,
        "error_type": body.error_type, "r_multiple": body.r_multiple, "source": "manual"})
    broadcaster.publish("fast", "decision_log_dirty", {"ts": event["ts"]})
    return {"ok": True, "event": event}


# ---------- C2 streak audit ----------

class AuditAckBody(BaseModel):
    operator: Operator


@router.post("/streak/audit-ack")
async def ack_audit(body: AuditAckBody, request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    streak = engine._extras.get("streak", 0)
    await request.app.state.redis.ack_streak_audit(body.operator.value, streak)
    return {"ok": True, "streak": streak}


# ---------- C4 calibration + Sharpe (Étape 5) ----------

@router.get("/calibration")
async def calibration(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    store = get_store()
    acked = bool(engine._extras.get("streak_acked"))
    return {**projections.calibration(store, streak_audit_acked=acked),
            "sharpe": projections.sharpe(store),
            "streak": engine._extras.get("streak", 0),
            "sizing_note": f"Sizing verrouillé à {config.SIZING_LOCK_PCT} % tant que les deux jauges ne sont pas validées"}


# ---------- reconciliation NinjaTrader (Étape 5) ----------

@router.post("/recon/import")
async def recon_import(file: UploadFile = File(...),
                       tz_offset_minutes: int = Form(0)) -> dict[str, Any]:
    data = await file.read()
    try:
        fills = parse_ninjatrader_csv(data, tz_offset_minutes=tz_offset_minutes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not fills:
        raise HTTPException(422, "aucun fill exploitable dans le CSV")
    store = get_store()
    summary = reconcile(store, fills)
    broadcaster.publish("fast", "decision_log_dirty", {"ts": time.time()})
    return {"ok": True, "fills_parsed": len(fills), **summary}


@router.get("/recon/unmatched")
async def recon_unmatched() -> dict[str, Any]:
    return {"unmatched_fills": projections.unmatched_fills(get_store())}


# ---------- orchestrator console (post-MVP, Étape 7) ----------

@router.get("/orchestrator")
async def orchestrator(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    return orchestrator_payload(engine.schema, engine._extras.get("rms"))
