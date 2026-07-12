"""Terminal engine — the deterministic hot path (CLAUDE §7: < ~200 ms, zero synchronous LLM).

fast loop (FAST_TICK_SECONDS): datasource fast tick -> Redis -> assemble fast blocks ->
Phase 0 (deterministic) -> unified signal -> C3 window management -> partial SSE events.
slow loop (SLOW_TICK_SECONDS): datasource slow tick -> s2 block -> slow SSE events.
Macro is never re-pushed on microstructure ticks (CLAUDE §6).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from . import config, settings
from .datasource.base import MarketDataSource
from .datasource import scenarios
from .event_store import get_store
from .macro_score import compute_s2_macro_score
from .meta import Freshness, MetaField, make_meta
from .phase0 import Phase0Input, evaluate_phase0
from .projections import loss_streak
from .redis_state import RedisState
from .schema import (BridgeVariables, Cascade, ContextSchema, Decision, DecisionWindow,
                     MasterState, OperationalMode, OrderFlow, Phase0State, S1State, S2State,
                     SessionIdentity, SessionMarker, Structure, SyncState, SyncVerdict)
from .scoring import compute_unified_signal
from .sse import broadcaster
from .strategies.sony import evaluate_strategies
from .strategies.youssef import compute_pipeline, update_regime

log = logging.getLogger("cholismo.engine")

# field -> (owning source, stale_after, absent_after)
_FAST = (config.FAST_STALE_SECONDS, config.FAST_ABSENT_SECONDS)
_SLOW = (config.SLOW_STALE_SECONDS, config.SLOW_ABSENT_SECONDS)
FIELD_SPEC: dict[str, tuple[str, float, float]] = {
    "svs_score": ("sierra_chart", *_FAST), "cvd": ("sierra_chart", *_FAST),
    "absorption": ("sierra_chart", *_FAST), "aggressor_ratio": ("sierra_chart", *_FAST),
    "vpoc": ("sierra_chart", *_FAST), "vah": ("sierra_chart", *_FAST),
    "val": ("sierra_chart", *_FAST), "lvn": ("sierra_chart", *_FAST),
    "chop": ("sierra_chart", *_FAST), "order_book": ("sierra_chart", *_FAST),
    "vix": ("cboe", *_FAST), "vvix": ("cboe", *_FAST),
    "eurusd": ("fx_feed", *_SLOW), "dx": ("fx_feed", *_SLOW), "dxy": ("fx_feed", *_FAST),
    "dxy_alt": ("cme", *_FAST),
    "nq_es": ("cme", *_SLOW), "zn": ("cme", *_SLOW),
    "real_rates": ("macro_feed", *_SLOW), "bridgewater_matrix": ("macro_feed", *_SLOW),
    "gex": ("greeks_engine", config.GEX_STALE_SECONDS, config.GEX_STALE_SECONDS * 4),
    "rms": ("rms_engine", *_FAST),
    # Simulated N1/N2A outputs (Youssef pipeline inputs — slow cadence, D-021)
    **{field: ("macro_feed", *_SLOW) for field in (
        "g_momentum", "pi_momentum", "d1", "d2", "d3", "d4", "d5",
        "taylor_ois_delta", "phillips_tips_delta", "beer_z", "carry_net",
        "cycle_div_delta", "leading_turn", "rr_zscore", "spot_momentum")},
}
DXY_CONTRADICTION_TOLERANCE = 0.5  # cross-source divergence threshold (D-012)


def _validate_order_book(meta: MetaField) -> None:
    """Deterministic DOM sanity (D-025). Malformed structure -> value WITHHELD
    (fail-closed §3: invalid data is no data), flagged MALFORMED. A CROSSED book
    (best bid >= best ask) is real pathological data: shown but flagged."""
    if meta.value is None:
        return
    try:
        bids = [(float(p), float(s)) for p, s in meta.value["bids"]]
        asks = [(float(p), float(s)) for p, s in meta.value["asks"]]
        if not bids or not asks:
            raise ValueError("empty book side")
    except (TypeError, ValueError, KeyError):
        meta.value = None
        meta.freshness = Freshness.ABSENT
        meta.flags.append("MALFORMED")
        return
    if bids[0][0] >= asks[0][0]:
        meta.flags.append("CROSSED_BOOK")


class Engine:
    def __init__(self, datasource: MarketDataSource, state: RedisState):
        self.ds = datasource
        self.state = state
        self.schema = ContextSchema()
        self._tasks: list[asyncio.Task] = []
        self._extras: dict[str, Any] = {"rms": None, "streak": 0, "scenario": None}
        self._regime_tier = "GREEN"  # D4 hysteresis state (reference/youssef/01)

    # ---------- assembly helpers ----------

    async def _meta(self, field: str, raws: dict[str, Optional[dict]], now: float,
                    extra_flags: Optional[list[str]] = None) -> MetaField:
        source, stale_after, absent_after = FIELD_SPEC[field]
        raw = raws.get(field)
        if raw is None:
            return MetaField(value=None, last_update_ts=None, source=source,
                             freshness=Freshness.ABSENT)
        flags = list(raw.get("flags") or []) + list(extra_flags or [])
        return make_meta(raw["value"], raw["source"], raw["ts"], stale_after, absent_after,
                         now=now, flags=flags)

    @staticmethod
    def _session_marker(now: float, force: Optional[str] = None) -> SessionMarker:
        # The mock scenario may SIMULATE the session window (D-020) — the rule itself
        # stays deterministic; a real feed never sets `force_session`.
        if force in SessionMarker.__members__:
            return SessionMarker(force)
        # CET session windows (PLACEHOLDER D-006).
        cet = datetime.fromtimestamp(now, tz=timezone(timedelta(hours=1)))
        h = cet.hour + cet.minute / 60.0
        lo, hi = config.LONDON_OBS_CET
        if lo <= h < hi:
            return SessionMarker.LONDRES_OBS
        lo, hi = config.OVERLAP_NY_CET
        if lo <= h < hi:
            return SessionMarker.OVERLAP_NY
        return SessionMarker.HORS_SESSION

    def _sync_verdict(self) -> SyncState:
        # D-009 (PLACEHOLDER): S1 CVD direction vs S2 EUR/USD cascade bias.
        cvd = self.schema.s1_state.order_flow.cvd
        eur = self.schema.s2_state.cascade.eurusd
        if cvd.freshness == Freshness.ABSENT or eur.freshness == Freshness.ABSENT:
            return SyncState(verdict=SyncVerdict.PARTIAL, detail="Donnée S1 ou S2 absente")
        if cvd.freshness == Freshness.STALE or eur.freshness == Freshness.STALE:
            return SyncState(verdict=SyncVerdict.PARTIAL, detail="Donnée S1 ou S2 périmée")
        try:
            aligned = float(cvd.value) * (float(eur.value) - 1.085) >= 0
        except (TypeError, ValueError):
            return SyncState(verdict=SyncVerdict.PARTIAL, detail="Valeurs non comparables")
        if aligned:
            return SyncState(verdict=SyncVerdict.ALIGNED, detail="CVD S1 et biais EUR/USD accordés")
        return SyncState(verdict=SyncVerdict.DIVERGENT, detail="CVD S1 contre biais EUR/USD")

    # ---------- C3 decision window (PRD §C3, D-008) ----------

    async def _manage_decision_window(self, phase0_open: bool, score: Optional[float],
                                      now: float, mode: str) -> DecisionWindow:
        window = await self.state.decision_window()
        if window:
            if now > window["deadline_ts"]:
                # Expiry = auto NO_GO reason=timeout. NEVER a forced entry.
                await self._auto_no_go(window, now)
                await self.state.set_decision_window(None)
                await self.state.set_decision_cooldown(30)
                window = None
            else:
                return DecisionWindow(open=True, opened_ts=window["opened_ts"],
                                      deadline_ts=window["deadline_ts"],
                                      instrument=window.get("instrument"))
        # Windows only arm in LIVE mode (D-008) — pre/post-session never opens a decision.
        # Threshold read from the settings projection (PLACEHOLDER D-008 -> editable
        # with a server-side guard, D-023); cached dict lookup — no I/O in hot path.
        arm_threshold = float(settings.value("decision.arm_threshold"))
        if (mode == "LIVE" and phase0_open and score is not None
                and score >= arm_threshold
                and not await self.state.in_decision_cooldown()):
            window = {"id": str(uuid.uuid4()), "opened_ts": now,
                      "deadline_ts": now + config.ANTIPARALYSIS_SECONDS,
                      "instrument": "ES", "armed_by": "THRESHOLD"}
            await self.state.set_decision_window(window)
            return DecisionWindow(open=True, opened_ts=now,
                                  deadline_ts=window["deadline_ts"], instrument="ES")
        return DecisionWindow(open=False)

    async def _auto_no_go(self, window: dict, now: float) -> None:
        store = get_store()
        snapshot_ref = store.save_snapshot(self.schema.model_dump(mode="json"))
        store.append("DecisionEvent", {
            "operator": "SYSTEM",  # timeout is written by the system, not an operator (D-019)
            "instrument": window.get("instrument"),
            "decision": "NO_GO",
            "reason": "timeout",
            "signal_score": self.schema.unified_signal_output.score,
            "degraded": self.schema.unified_signal_output.degraded,
            "cognitive_selfcheck": None,
            "schema_snapshot_ref": snapshot_ref,
            "window_id": window.get("id"),
        }, ts=now)
        broadcaster.publish("fast", "decision_log_dirty", {"ts": now})
        log.info("C3 expired -> auto NO_GO (timeout)")

    # ---------- loops ----------

    async def _assemble_fast(self, now: float) -> None:
        redis_up = await self.state.ping()
        raws: dict[str, Optional[dict]] = {}
        if redis_up:
            raws = await self.state.read_raw_many(list(FIELD_SPEC.keys()))

        # s1_state
        order_book = await self._meta("order_book", raws, now)
        _validate_order_book(order_book)
        s1 = S1State(
            svs_score=await self._meta("svs_score", raws, now),
            order_flow=OrderFlow(
                cvd=await self._meta("cvd", raws, now),
                absorption=await self._meta("absorption", raws, now),
                aggressor_ratio=await self._meta("aggressor_ratio", raws, now)),
            structure=Structure(
                vpoc=await self._meta("vpoc", raws, now),
                vah=await self._meta("vah", raws, now),
                val=await self._meta("val", raws, now),
                lvn=await self._meta("lvn", raws, now)),
            chop=await self._meta("chop", raws, now),
            order_book=order_book,
        )
        self.schema.s1_state = s1

        # bridge_variables — GEX age is real (now - last compute), never a countdown.
        gex_flags: list[str] = []
        dxy_meta = await self._meta("dxy", raws, now)
        dxy_alt = raws.get("dxy_alt")
        if (dxy_meta.value is not None and dxy_alt and dxy_alt.get("value") is not None
                and not isinstance(dxy_alt["value"], str)):
            try:
                if abs(float(dxy_meta.value) - float(dxy_alt["value"])) > DXY_CONTRADICTION_TOLERANCE:
                    dxy_meta.flags.append("CROSS_SOURCE_DIVERGENT")
            except (TypeError, ValueError):
                pass
        gex_meta = await self._meta("gex", raws, now, extra_flags=gex_flags)
        self.schema.bridge_variables = BridgeVariables(
            gex=gex_meta,
            gex_last_compute_ts=gex_meta.last_update_ts,
            vvix=await self._meta("vvix", raws, now),
            dxy=dxy_meta,
        )

        # VIX is a Phase-0-critical field: refresh its meta on the fast path too (the
        # slow channel keeps its own cadence for SSE — nothing is re-pushed here).
        self.schema.s2_state.cascade.vix = await self._meta("vix", raws, now)
        vix_value = (float(self.schema.s2_state.cascade.vix.value)
                     if self.schema.s2_state.cascade.vix.value is not None else None)

        # D4 regime hysteresis is "always-on" (reference/youssef/01) — updated each fast
        # tick; the full pipeline block is (re)published on the slow channel.
        self._regime_tier = update_regime(self._regime_tier, vix_value, None)

        # Sony execution strategies — SVS + Mean Reversion eligibility (reference/sony/*)
        s1.strategies = evaluate_strategies(s1, vix_value,
                                            self.schema.session_identity.session_marker, now)

        # sync + unified signal
        self.schema.sync_state = self._sync_verdict()
        signal = compute_unified_signal(self.schema.s1_state, self.schema.s2_state,
                                        self.schema.bridge_variables)

        # extras used by Phase 0 / panels
        rms_meta = await self._meta("rms", raws, now)
        rms_value = None if rms_meta.value is None else float(rms_meta.value)
        scenario = scenarios.resolve(await self.state.scenario() if redis_up else None)
        store = get_store()
        streak = max(loss_streak(store), scenario["simulated_streak"])  # D-017
        streak_acked = await self.state.streak_audit_acked(streak) if redis_up else False

        # Phase 0 — deterministic, fail-closed
        heartbeat_age = await self.state.heartbeat_age() if redis_up else None
        phase0_state, blockers, warnings = evaluate_phase0(
            Phase0Input(schema=self.schema, streak=streak, streak_audit_acked=streak_acked,
                        redis_up=redis_up, engine_heartbeat_age=heartbeat_age, now=now),
            rms=rms_value,
        )

        # C3 decision window + decision status
        mode = await self.state.mode() if redis_up else "PRE_SESSION"
        window = await self._manage_decision_window(
            phase0_state == Phase0State.OPEN, signal.score, now, mode)
        signal.decision_window = window
        last_decision = await self._last_window_decision()
        signal.decision = Decision.PENDING if window.open else last_decision
        self.schema.unified_signal_output = signal

        # session_identity
        degraded_master = (signal.degraded
                           or any(m.freshness != Freshness.FRESH for m in
                                  (s1.svs_score, s1.chop, self.schema.bridge_variables.gex)))
        self.schema.session_identity = SessionIdentity(
            session_marker=self._session_marker(now, scenario.get("force_session")),
            operational_mode=OperationalMode(mode),
            operator=self.schema.session_identity.operator,
            phase0=phase0_state,
            phase0_blockers=blockers,
            phase0_warnings=warnings,
            phase0_advisory=self.schema.session_identity.phase0_advisory,
            master_state=(MasterState.NOT_READY if phase0_state == Phase0State.BLOCKED
                          else MasterState.DEGRADED if degraded_master else MasterState.READY),
            server_ts=now,
        )

        self._extras = {"rms": rms_value, "rms_meta": rms_meta.model_dump(mode="json"),
                        "streak": streak, "streak_acked": streak_acked,
                        "scenario": {"name": scenario["name"], "label": scenario["label"]}}

        if redis_up:
            await self.state.beat()

        dump = self.schema.model_dump(mode="json")
        for block in ("session_identity", "s1_state", "bridge_variables",
                      "sync_state", "unified_signal_output"):
            broadcaster.publish("fast", block, dump[block])
        broadcaster.publish("fast", "extras", self._extras)

    async def _last_window_decision(self) -> Decision:
        events = get_store().events("DecisionEvent")
        if not events:
            return Decision.PENDING
        return Decision(events[-1]["decision"])

    async def _assemble_slow(self, now: float) -> None:
        raws = await self.state.read_raw_many(
            ["nq_es", "vix", "zn", "dx", "eurusd", "real_rates", "bridgewater_matrix",
             "g_momentum", "pi_momentum", "d1", "d2", "d3", "d4", "d5",
             "taylor_ois_delta", "phillips_tips_delta", "beer_z", "carry_net",
             "cycle_div_delta", "leading_turn", "rr_zscore", "spot_momentum"])
        cascade = Cascade(
            nq_es=await self._meta("nq_es", raws, now),
            vix=await self._meta("vix", raws, now),
            zn=await self._meta("zn", raws, now),
            dx=await self._meta("dx", raws, now),
            eurusd=await self._meta("eurusd", raws, now),
            real_rates=await self._meta("real_rates", raws, now),
        )
        matrix_meta = await self._meta("bridgewater_matrix", raws, now)
        cascade_values = {k: (getattr(cascade, k).value if getattr(cascade, k).value is not None else None)
                          for k in ("nq_es", "vix", "zn", "dx", "eurusd")}
        macro = compute_s2_macro_score(
            cascade_values,
            matrix_meta.value if isinstance(matrix_meta.value, list) else None,
            cascade.real_rates.value if isinstance(cascade.real_rates.value, (int, float)) else None,
        )
        # Youssef pipeline (reference/youssef/*) — canonical formulas over simulated inputs.
        pipeline = compute_pipeline(self._regime_tier, raws)
        self.schema.s2_state = S2State(cascade=cascade, bridgewater_matrix=matrix_meta,
                                       s2_macro_score=macro, pipeline=pipeline)
        broadcaster.publish("slow", "s2_state", self.schema.model_dump(mode="json")["s2_state"])

    async def _fast_loop(self) -> None:
        while True:
            started = time.time()
            try:
                await self.ds.tick_fast(self.state)
                await self._assemble_fast(time.time())
            except Exception:
                log.exception("fast loop tick failed (fail-closed: schema keeps aging)")
            elapsed = time.time() - started
            await asyncio.sleep(max(0.02, config.FAST_TICK_SECONDS - elapsed))

    async def _slow_loop(self) -> None:
        while True:
            started = time.time()
            try:
                await self.ds.tick_slow(self.state)
                await self._assemble_slow(time.time())
            except Exception:
                log.exception("slow loop tick failed")
            # Cadence, pas pause : compenser la durée du tick (même pattern que la
            # _fast_loop) sinon l'intervalle réel dérive de cadence+tick (RUNTIME_LOOPS
            # Loop D). Plancher anti busy-wait ; un tick plus lent que la cadence saute
            # simplement au suivant — pas d'empilement (backpressure).
            elapsed = time.time() - started
            await asyncio.sleep(max(0.05, config.SLOW_TICK_SECONDS - elapsed))

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._fast_loop()),
                       asyncio.create_task(self._slow_loop())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # snapshot for GET /state
    def snapshot(self) -> dict[str, Any]:
        return {"schema": self.schema.model_dump(mode="json"), "extras": self._extras}
