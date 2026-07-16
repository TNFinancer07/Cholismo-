"""REST + SSE API. The UI reflects state; it never overrides the deterministic locks:
every gate (Phase 0, self-check, window) is re-checked HERE, server-side.
No endpoint places an order — Go/No-Go only APPENDS a DecisionEvent (CLAUDE §2.1).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import config, journal, live_mode, projections, recap, settings
from .datasource import scenarios
from .datasource.mock import SOURCES
from .event_store import get_store
from .orchestrator import orchestrator_payload
from .recon import parse_ninjatrader_csv, reconcile
from .schema import Operator, Phase0State
from .snapshot import capture_snapshot, list_snapshots, read_snapshot
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


# ---------- Snapshot Déterministe (D-030) ----------

@router.post("/snapshot")
async def create_snapshot(request: Request) -> dict[str, Any]:
    """Capture instantanée déterministe des 4 blocs (carnet, CVD, calendrier, alertes IA) →
    JSON + Markdown dans SNAPSHOT_DIR. Écriture async non-bloquante ; observation, jamais un
    ordre (§2.1)."""
    return await capture_snapshot(request.app.state.engine, time.time())


# ---------- Journal de Bord — index + lecture des snapshots passés (D-032) ----------
# Note d'ordre : `/snapshots/list` est déclaré AVANT `/snapshots/{snapshot_id}` pour que
# « list » ne soit pas capté comme un identifiant. Lecture disque offloadée (to_thread).

@router.get("/snapshots/list")
async def snapshots_index(limit: int = 200) -> dict[str, Any]:
    """Index des snapshots (récent → ancien), pour le panneau Journal de Bord. Fail-closed :
    dossier absent → liste vide, jamais une erreur (§3)."""
    limit = max(1, min(limit, 1000))
    items = await asyncio.to_thread(list_snapshots, config.SNAPSHOT_DIR, limit)
    return {"directory": config.SNAPSHOT_DIR, "count": len(items), "snapshots": items}


@router.get("/snapshots/{snapshot_id}")
async def snapshot_content(snapshot_id: str) -> dict[str, Any]:
    """Contenu d'UN snapshot (JSON parsé + Markdown) pour le visualiseur. Id invalide ou
    inconnu → 404 (garde anti-traversal côté `read_snapshot`)."""
    snap = await asyncio.to_thread(read_snapshot, config.SNAPSHOT_DIR, snapshot_id)
    if snap is None:
        raise HTTPException(404, "snapshot introuvable ou identifiant invalide")
    return snap


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
    if await redis.mode() != "LIVE":
        raise HTTPException(409, "fenêtre de décision uniquement en mode LIVE (D-008)")
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


# ---------- trading journal (reference/journal, D-022) ----------

@router.get("/journal")
async def get_journal(request: Request) -> dict[str, Any]:
    store = get_store()
    redis = request.app.state.redis
    return {
        "strategies": journal.STRATEGIES,
        "exit_types": journal.EXIT_TYPES,
        "paliers": journal.PALIERS,
        "drafts": await redis.journal_drafts(),
        "entries": list(reversed(store.journal_entries("trade_locked")))[:200],
        "sessions": list(reversed(store.journal_entries("session_closed")))[:60],
        "sentiments": await redis.journal_sentiments(),
        "aggregates": journal.aggregates(store),
        "lockout": journal.derive_lockout(store),
        "n8n": {**(await redis.journal_n8n()), "api_key": "***"
                if (await redis.journal_n8n()).get("api_key") else ""},
    }


class JournalDraftCreate(BaseModel):
    strategy_id: str
    operator: Operator


@router.post("/journal/draft")
async def create_journal_draft(body: JournalDraftCreate, request: Request) -> dict[str, Any]:
    if body.strategy_id not in journal.STRATEGIES:
        raise HTTPException(400, f"stratégie inconnue : {body.strategy_id}")
    engine = request.app.state.engine
    redis = request.app.state.redis
    store = get_store()
    today = journal.day_of(time.time())
    same_day = [e for e in store.journal_entries("trade_locked")
                if e.get("strategy_id") == body.strategy_id and journal.day_of(e["ts"]) == today]
    same_day_drafts = [d for d in await redis.journal_drafts()
                       if d.get("strategy_id") == body.strategy_id]
    chop = engine.schema.s1_state.chop.value
    vix = engine.schema.s2_state.cascade.vix.value
    draft = {
        "draft_id": str(uuid.uuid4()),
        "strategy_id": body.strategy_id,
        "operator": body.operator.value,
        "created_ts": time.time(),
        "trade_num": len(same_day) + len(same_day_drafts) + 1,
        # Pré-rempli depuis le schéma live — pedigree réel, pas de saisie recopiée.
        "chop": None if chop is None else round(float(chop), 1),
        "vix": None if vix is None else round(float(vix), 2),
        "nq_es_corr": None,  # source non câblée (voir S1S) — saisie manuelle
    }
    await redis.journal_set_draft(draft["draft_id"], draft)
    return {"ok": True, "draft": draft}


class JournalDraftUpdate(BaseModel):
    fields: dict[str, Any]


@router.put("/journal/draft/{draft_id}")
async def update_journal_draft(draft_id: str, body: JournalDraftUpdate,
                               request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    draft = await redis.journal_get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "brouillon inconnu (déjà verrouillé ?)")
    unknown = set(body.fields) - journal.DRAFT_FIELDS
    if unknown:
        raise HTTPException(422, f"champs inconnus : {', '.join(sorted(unknown))}")
    draft.update(body.fields)
    await redis.journal_set_draft(draft_id, draft)
    return {"ok": True, "draft": draft}


@router.delete("/journal/draft/{draft_id}")
async def delete_journal_draft(draft_id: str, request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    if not await redis.journal_get_draft(draft_id):
        raise HTTPException(404, "brouillon inconnu")
    await redis.journal_delete_draft(draft_id)  # un brouillon Redis se supprime ;
    return {"ok": True}                          # une entrée verrouillée, jamais.


@router.post("/journal/draft/{draft_id}/lock")
async def lock_journal_draft(draft_id: str, request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    store = get_store()
    draft = await redis.journal_get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "brouillon inconnu")
    problems = journal.validate_lock(draft)
    if problems:
        raise HTTPException(422, " · ".join(problems))
    payload = {k: v for k, v in draft.items() if k != "draft_id"}
    entry = store.append_journal("trade_locked", payload)
    await redis.journal_delete_draft(draft_id)
    await journal.fire_webhook(await redis.journal_n8n(), "trade_closed", entry, store)
    return {"ok": True, "entry": entry}


class SentimentBody(BaseModel):
    phase: str  # PRE | POST
    operator: Operator
    humeur: int
    energie: int
    confiance: int
    facteurs: str = ""
    note: str = ""


@router.post("/journal/sentiment")
async def post_sentiment(body: SentimentBody, request: Request) -> dict[str, Any]:
    if body.phase not in ("PRE", "POST"):
        raise HTTPException(400, "phase invalide (PRE|POST)")
    for value in (body.humeur, body.energie, body.confiance):
        if not 1 <= value <= 5:
            raise HTTPException(422, "échelles 1-5")
    await request.app.state.redis.journal_set_sentiment(
        body.phase, body.operator.value,
        {"humeur": body.humeur, "energie": body.energie, "confiance": body.confiance,
         "facteurs": body.facteurs, "note": body.note, "ts": time.time()})
    return {"ok": True}


@router.post("/journal/close-session")
async def close_journal_session(request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    store = get_store()
    today = journal.day_of(time.time())
    day_trades = [e for e in store.journal_entries("trade_locked")
                  if journal.day_of(e["ts"]) == today]
    entry = store.append_journal("session_closed", {
        "day": today,
        "trades": len(day_trades),
        "r_total": round(sum(float(t.get("resultat_r") or 0) for t in day_trades), 2),
        "sentiments": await redis.journal_sentiments(),
        "trade_ids": [t["id"] for t in day_trades],
    })
    await redis.journal_clear_sentiments()
    await journal.fire_webhook(await redis.journal_n8n(), "session_closed", entry, store)
    return {"ok": True, "entry": entry}


class N8nConfig(BaseModel):
    url: str = ""
    api_key: str = ""
    enabled: bool = False


@router.post("/journal/n8n")
async def set_journal_n8n(body: N8nConfig, request: Request) -> dict[str, Any]:
    current = await request.app.state.redis.journal_n8n()
    api_key = body.api_key if body.api_key != "***" else current.get("api_key", "")
    await request.app.state.redis.journal_set_n8n(
        {"url": body.url, "api_key": api_key, "enabled": body.enabled})
    return {"ok": True}


# ---------- RECAP — session cockpit projection (brainstorm Récapitulatif, D-023) ----------

@router.get("/recap")
async def get_recap(request: Request, granularity: str = "session") -> dict[str, Any]:
    engine = request.app.state.engine
    return recap.recap_payload(get_store(), engine.schema, engine._extras, granularity)


# ---------- Settings — two-tier, event-sourced, server-validated (D-023) ----------

def _settings_guard(exc: settings.SettingsError) -> HTTPException:
    return HTTPException(exc.status, exc.detail)


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    return settings.payload(get_store())


@router.get("/settings/history")
async def get_settings_history() -> dict[str, Any]:
    return {"history": settings.history(get_store())}


@router.get("/settings/export")
async def export_settings() -> dict[str, Any]:
    return settings.export_overrides()


class SettingWrite(BaseModel):
    value: Any = None
    scope: Optional[str] = None
    operator: Operator = Operator.SONY
    ack_guard: bool = False       # explicit acknowledgement of a guard warning
    unlock_live: bool = False     # explicit unlock while a LIVE session is running


@router.put("/settings/{key:path}")
async def put_setting(key: str, body: SettingWrite, request: Request) -> dict[str, Any]:
    try:
        settings.check_live_lock(await request.app.state.redis.mode(), body.unlock_live)
        event = settings.set_value(key, body.value, body.scope, body.operator.value,
                                   ack_guard=body.ack_guard)
    except settings.SettingsError as exc:
        raise _settings_guard(exc) from exc
    return {"ok": True, "event": event, "settings": settings.payload(get_store())}


class SettingRevert(BaseModel):
    scope: Optional[str] = None
    operator: Operator = Operator.SONY
    unlock_live: bool = False


@router.post("/settings/{key:path}/revert")
async def revert_setting(key: str, body: SettingRevert, request: Request) -> dict[str, Any]:
    try:
        settings.check_live_lock(await request.app.state.redis.mode(), body.unlock_live)
        event = settings.revert(key, body.scope, body.operator.value)
    except settings.SettingsError as exc:
        raise _settings_guard(exc) from exc
    return {"ok": True, "event": event, "settings": settings.payload(get_store())}


class PresetBody(BaseModel):
    name: str
    operator: Operator = Operator.SONY
    unlock_live: bool = False


@router.post("/settings/presets")
async def save_preset(body: PresetBody) -> dict[str, Any]:
    try:
        event = settings.save_preset(body.name, body.operator.value)
    except settings.SettingsError as exc:
        raise _settings_guard(exc) from exc
    return {"ok": True, "event": event, "settings": settings.payload(get_store())}


@router.post("/settings/presets/apply")
async def apply_preset(body: PresetBody, request: Request) -> dict[str, Any]:
    try:
        settings.check_live_lock(await request.app.state.redis.mode(), body.unlock_live)
        event = settings.apply_preset(body.name.strip().upper()[:24], body.operator.value)
    except settings.SettingsError as exc:
        raise _settings_guard(exc) from exc
    return {"ok": True, "event": event, "settings": settings.payload(get_store())}


class ImportBody(BaseModel):
    payload: dict[str, Any]
    operator: Operator = Operator.SONY
    unlock_live: bool = False


@router.post("/settings/import")
async def import_settings(body: ImportBody, request: Request) -> dict[str, Any]:
    try:
        settings.check_live_lock(await request.app.state.redis.mode(), body.unlock_live)
        event = settings.import_overrides(body.payload, body.operator.value)
    except settings.SettingsError as exc:
        raise _settings_guard(exc) from exc
    return {"ok": True, "event": event, "settings": settings.payload(get_store())}


# ---------- Mode Live — deterministic advisory layer (D-023, CLAUDE §2.8) ----------

@router.get("/live/context")
async def live_context(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    mode = await request.app.state.redis.mode()
    return {
        "context": live_mode.context_payload(engine.schema, engine._extras, mode),
        "reading": live_mode.market_reading(engine.schema, engine._extras, mode),
        "suggestions": live_mode.SUGGESTIONS,
        "cycle_seconds": settings.value("live.cycle_seconds"),
        "cycle_offwindow_seconds": settings.value("live.cycle_offwindow_seconds"),
    }


class AskBody(BaseModel):
    question: str
    operator: Operator = Operator.SONY


@router.post("/live/ask")
async def live_ask(body: AskBody, request: Request) -> dict[str, Any]:
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "question vide")
    if len(question) > 500:
        raise HTTPException(422, "question trop longue (500 caractères max)")
    engine = request.app.state.engine
    mode = await request.app.state.redis.mode()
    return live_mode.answer(question, engine.schema, engine._extras, mode)


# ---------- AI observability (Étape 10 — coûts/latences loggés, CLAUDE §7) ----------

@router.get("/ai/status")
async def ai_status() -> dict[str, Any]:
    return {"calls": get_store().ai_calls(limit=50)}


# ---------- orchestrator console (post-MVP, Étape 7) ----------

@router.get("/orchestrator")
async def orchestrator(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    return orchestrator_payload(engine.schema, engine._extras.get("rms"))
