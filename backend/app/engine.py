"""Terminal engine — the deterministic hot path (CLAUDE §7: < ~200 ms, zero synchronous LLM).

fast loop (FAST_TICK_SECONDS): datasource fast tick -> Redis -> assemble fast blocks ->
Phase 0 (deterministic) -> unified signal -> C3 window management -> partial SSE events.
slow loop (SLOW_TICK_SECONDS): datasource slow tick -> s2 block -> slow SSE events.
Macro is never re-pushed on microstructure ticks (CLAUDE §6).
"""
from __future__ import annotations

import asyncio
import contextlib
import heapq
import logging
import math
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

from . import config, lsr_tuning, settings
from .datasource.base import MarketDataSource
from .datasource import scenarios
from .event_store import get_store
from .cvd_stratified import build_cvd_stratified
from .footprint import build_footprint
from .volume_profile import build_volume_profile
from .graph.liquidity_sweep import SWEEP_GRAPH, build_sweep_inputs
from .account_provider import AccountDataProvider
from .lsr_engine import build_lsr_inputs, evaluate_lsr
from .macro_news import MacroNewsProvider
from .risk_sizer import AccountState, account_view, size_plan
from .trade_manifest import manifest_from_lsr_plan
from .heatmap import latest_column
from .macro_risk import build_macro_calendar, compute_macro_risk
from .orderflow.bridge import book_history_push, orderflow_shadow, snapshot_for_lsr
from .rates import build_yield_curve
from .sentiment import build_long_short
from .macro_score import compute_s2_macro_score
from .meta import Freshness, MetaField, make_meta
from .phase0 import Phase0Input, evaluate_phase0
from .projections import loss_streak
from .redis_state import RedisState
from .options_chain import build_options_chain, build_term_structure
from .schema import (AccountStateBlock, BridgeVariables, Cascade, ContextSchema, CvdLevel,
                     CvdState, Decision,
                     DecisionWindow, EconCalendar, LiquiditySweep, LiquiditySweepAlert,
                     MasterState, OperationalMode, OrderFlow, Phase0State, S1State, S2State,
                     SessionIdentity, SessionMarker, Structure, SyncState, SyncVerdict, VolSurface)
from .scoring import compute_unified_signal
from .sse import broadcaster
from .strategies.sony import evaluate_strategies
from .strategies.youssef import compute_pipeline, update_regime

log = logging.getLogger("cholismo.engine")

# field -> (owning source, stale_after, absent_after)
_FAST = (config.FAST_STALE_SECONDS, config.FAST_ABSENT_SECONDS)
_SLOW = (config.SLOW_STALE_SECONDS, config.SLOW_ABSENT_SECONDS)
FIELD_SPEC: dict[str, tuple[str, float, float]] = {
    "svs_score": (config.MICROSTRUCTURE_SOURCE, *_FAST), "cvd": (config.MICROSTRUCTURE_SOURCE, *_FAST),
    "absorption": (config.MICROSTRUCTURE_SOURCE, *_FAST), "aggressor_ratio": (config.MICROSTRUCTURE_SOURCE, *_FAST),
    "vpoc": (config.MICROSTRUCTURE_SOURCE, *_FAST), "vah": (config.MICROSTRUCTURE_SOURCE, *_FAST),
    "val": (config.MICROSTRUCTURE_SOURCE, *_FAST), "lvn": (config.MICROSTRUCTURE_SOURCE, *_FAST),
    "chop": (config.MICROSTRUCTURE_SOURCE, *_FAST), "order_book": (config.MICROSTRUCTURE_SOURCE, *_FAST),
    "tape": (config.MICROSTRUCTURE_SOURCE, *_FAST),
    "session_prev": (config.MICROSTRUCTURE_SOURCE, *_FAST),  # niveaux POC/VAH/VAL de la veille (source, D-041)
    "vix": ("cboe", *_FAST), "vvix": ("cboe", *_FAST),
    "eurusd": ("fx_feed", *_SLOW), "dx": ("fx_feed", *_SLOW), "dxy": ("fx_feed", *_FAST),
    "dxy_alt": ("cme", *_FAST),
    "nq_es": ("cme", *_SLOW), "zn": ("cme", *_SLOW),
    "real_rates": ("macro_feed", *_SLOW), "bridgewater_matrix": ("macro_feed", *_SLOW),
    "gex": ("greeks_engine", config.GEX_STALE_SECONDS, config.GEX_STALE_SECONDS * 4),
    "rms": ("rms_engine", *_FAST),
    "econ_calendar": ("econ_feed", *_SLOW),  # systemic macro/geo schedule (D-027)
    "macro_releases": ("econ_feed", *_SLOW),  # tradable economic releases (D-040)
    "long_short": ("sentiment_feed", *_SLOW),  # positionnement Long/Short agrégé (D-053)
    "yields": ("rates_feed", *_SLOW),          # taux bruts US/DE → courbe + spreads (D-053)
    # Surface de volatilité (D-039) — chaîne d'options (Greeks engine, vitesse inconnue §8-B2 →
    # GEX_STALE) + structure de vol VIX (CBOE, cadence lente).
    "options_chain": ("greeks_engine", config.GEX_STALE_SECONDS, config.GEX_STALE_SECONDS * 4),
    "vol_term_structure": ("cboe", *_SLOW),
    # Simulated N1/N2A outputs (Youssef pipeline inputs — slow cadence, D-021)
    **{field: ("macro_feed", *_SLOW) for field in (
        "g_momentum", "pi_momentum", "d1", "d2", "d3", "d4", "d5",
        "taylor_ois_delta", "phillips_tips_delta", "beer_z", "carry_net",
        "cycle_div_delta", "leading_turn", "rr_zscore", "spot_momentum")},
}
DXY_CONTRADICTION_TOLERANCE = 0.5  # cross-source divergence threshold (D-012)


BOOK_DEPTH = 10   # displayed levels per side (D-025)
TAPE_WINDOW = 40  # displayed prints, most recent first (D-026)
CAL_WINDOW = 12         # displayed scheduled events, soonest first (D-027)
CAL_PAST_GRACE = 30 * 60  # keep recent past (symmetric T1 blackout window); older dropped
CVD_MAX_LEVELS = 24     # displayed price levels (most active), sorted by price (D-029)
CVD_MAX_TRACKED = 512   # accumulator soft cap — bounds hot-path sort cost (D-029)


def _validate_tape(meta: MetaField) -> None:
    """Deterministic Time & Sales normalization (D-026, hardened by /devil).

    PER-PRINT robustness: each print is validated in isolation — a finite positive
    price/size and a valid side; a structurally broken print (missing key, non-numeric)
    is DROPPED ALONE, never discards the whole window (garbage is not data, §3). Prints
    are DEDUPED by seq (seq is a unique print id; a duplicate would collide React keys) —
    last occurrence wins. `seq` is the ordering key on purpose: `ts` can be clock-desynced
    (a real pathology), seq is the source's monotonic append id. Bounded to the
    TAPE_WINDOW most recent via heapq (O(n log k), a burst can't blow the hot path §7).
    No usable print left -> value WITHHELD (ABSENT + MALFORMED)."""
    if meta.value is None:
        return
    if not isinstance(meta.value, list):
        meta.value = None
        meta.freshness = Freshness.ABSENT
        meta.flags.append("MALFORMED")
        return
    by_seq: dict[int, dict] = {}
    for p in meta.value:
        try:
            price, size, seq = float(p["price"]), float(p["size"]), int(p["seq"])
            side = p["side"]
        except (TypeError, ValueError, KeyError):
            continue  # drop this print alone, keep the rest
        if math.isfinite(price) and math.isfinite(size) and price > 0 and size > 0 \
                and side in ("BUY", "SELL"):
            by_seq[seq] = {"ts": p.get("ts"), "price": price, "size": size,
                           "side": side, "seq": seq}
    if not by_seq:
        meta.value = None
        meta.freshness = Freshness.ABSENT
        meta.flags.append("MALFORMED")
        return
    meta.value = heapq.nlargest(TAPE_WINDOW, by_seq.values(), key=lambda p: p["seq"])


def _validate_order_book(meta: MetaField) -> None:
    """Deterministic DOM normalization (D-025, hardened by /devil).

    Malformed structure or ANY non-finite / non-positive level -> value WITHHELD
    (fail-closed §3: garbage is not data), flagged MALFORMED. Valid books are
    CANONICALIZED, never invented: duplicate prices aggregated (same level, sizes
    summed), sides sorted (bids desc / asks asc — a real feed may send unsorted),
    depth capped to the BOOK_DEPTH best levels (display contract; also stops
    SSE/DOM flooding from extreme feeds). A CROSSED book (best bid >= best ask)
    is real pathological data: shown + flagged."""
    if meta.value is None:
        return

    def canonical_side(levels, descending: bool) -> list[list[float]]:
        aggregated: dict[float, float] = {}
        for price, size in levels:
            price, size = float(price), float(size)
            if not (math.isfinite(price) and math.isfinite(size)) or price <= 0 or size <= 0:
                raise ValueError("invalid level")
            aggregated[price] = aggregated.get(price, 0.0) + size
        if not aggregated:
            raise ValueError("empty book side")
        ordered = sorted(aggregated.items(), reverse=descending)
        return [[price, size] for price, size in ordered[:BOOK_DEPTH]]

    try:
        bids = canonical_side(meta.value["bids"], descending=True)
        asks = canonical_side(meta.value["asks"], descending=False)
    except (TypeError, ValueError, KeyError):
        meta.value = None
        meta.freshness = Freshness.ABSENT
        meta.flags.append("MALFORMED")
        return
    meta.value = {"bids": bids, "asks": asks}
    if bids[0][0] >= asks[0][0]:
        meta.flags.append("CROSSED_BOOK")


def _validate_econ_calendar(meta: MetaField, now: float) -> None:
    """Deterministic economic-calendar normalization (D-027, hardened by /devil).

    PER-EVENT robustness (Tape /devil lesson carried forward): each event is validated
    alone — a FINITE scheduled `ts`, a `tier` in {1,2,3}, a non-empty `name`; a broken
    event (missing key, non-numeric ts, bad tier) is DROPPED ALONE, never discards the
    calendar (garbage is not data, §3). Events are DEDUPED by (ts, name, region) so React
    keys stay unique. The far past (beyond CAL_PAST_GRACE, the symmetric T1 blackout) is
    dropped BEFORE the cap — a naive "CAL_WINDOW oldest" cap would let elapsed events
    starve an imminent Tier-1 out of the window (found by /devil). Then sorted
    CHRONOLOGICALLY (soonest first — it is a schedule) and bounded to CAL_WINDOW.
    Two DISTINCT empty outcomes, kept honest: no VALID event at all -> value WITHHELD
    (ABSENT + MALFORMED, the feed is garbage); valid events but all elapsed -> value []
    kept FRESH (the feed lives, nothing relevant — the panel says so, no fake outage).
    The `ts` is a KNOWN scheduled time, so the client countdown is honest & precise
    (contrast the B2 GEX unknown-expiry case, §8.2). Never an order (§2.1)."""
    if meta.value is None:
        return
    if not isinstance(meta.value, list):
        meta.value = None
        meta.freshness = Freshness.ABSENT
        meta.flags.append("MALFORMED")
        return
    by_key: dict[tuple, dict] = {}
    for e in meta.value:
        try:
            ts = float(e["ts"])
            tier = int(e["tier"])
            name = str(e["name"]).strip()
            region = str(e.get("region", "")).strip()
        except (TypeError, ValueError, KeyError):
            continue  # drop this event alone, keep the rest
        if math.isfinite(ts) and tier in (1, 2, 3) and name:
            by_key[(round(ts, 3), name, region)] = {"ts": ts, "name": name,
                                                    "tier": tier, "region": region}
    if not by_key:
        meta.value = None
        meta.freshness = Freshness.ABSENT
        meta.flags.append("MALFORMED")
        return
    relevant = [e for e in by_key.values() if e["ts"] > now - CAL_PAST_GRACE]
    meta.value = sorted(relevant, key=lambda e: e["ts"])[:CAL_WINDOW]


class Engine:
    def __init__(self, datasource: MarketDataSource, state: RedisState,
                 account_provider: Optional["AccountDataProvider"] = None,
                 news_provider: Optional["MacroNewsProvider"] = None,
                 on_arm: Optional[Callable[[Any], Any]] = None):
        self.ds = datasource
        self.state = state
        # L4 `gates.eval` (D-080) : notifié à CHAQUE manifeste émis — le point d'armement du
        # détecteur de sweep. `None` = pas de journalisation O1-O5, et rien d'autre ne change :
        # les balises sont consultatives, leur absence ne retient aucun trade (§2.1).
        self._on_arm = on_arm
        # Source de compte (D-047) : None = pas de source → AUCUNE émission de manifeste
        # (« on ne trade jamais à l'aveugle », fail-closed §3).
        self.account_provider = account_provider
        # Calendrier macro (D-050) : None = porte F0 absente (stack démo) ; câblé → l'état
        # news entre dans LsrInputs et HARD_LOCK/SAFETY_UNKNOWN verrouillent l'évaluation.
        self.news_provider = news_provider
        self.schema = ContextSchema()
        self._tasks: list[asyncio.Task] = []
        self._extras: dict[str, Any] = {"rms": None, "streak": 0, "scenario": None}
        # Détecteur Sweep (D-028) : feed court + clé du dernier événement (anti-inondation).
        self._sweep_recent: deque = deque(maxlen=config.SWEEP_RECENT_MAX)
        self._sweep_last_key: Optional[str] = None
        # Pipeline LSR (D-046) : clé de la dernière alerte AYANT ÉMIS un manifeste (une émission
        # max par sweep distinct) + horodatage de la dernière émission (fenêtre anti-FOMO F7 :
        # sous un détecteur qui alterne BID/ASK en continu, la clé seule laisserait spammer).
        self._lsr_emitted_key: Optional[str] = None
        self._lsr_last_emit_ts: float = 0.0
        # Historique de carnet L2 (D-056) : le schéma ne porte que le carnet COURANT, or le
        # rechargement d'un mur est par nature une mesure DANS LE TEMPS. Tampon borné — sans
        # plafond, six heures à 4 Hz garderaient 86 400 carnets en mémoire.
        self._book_history: list[dict] = []
        # Horodatage STABLE de l'événement sweep courant (D-056 /devil). `alert.ts` est régénéré
        # à CHAQUE évaluation d'une condition persistante (D-046) : le passer au calculateur
        # rendait `span_after ≈ 0` en permanence, donc **B4 structurellement incalculable**, et
        # bornait la fenêtre B1 à un instant qui glisse. On garde le PREMIER passage de
        # l'événement (identité `trigger|direction`, la même qu'au dédoublonnage).
        self._sweep_event_key: Optional[str] = None
        self._sweep_event_ts: Optional[float] = None
        # Comparaison ombre (D-056) : elle vit dans SON attribut, pas dans `_extras` — ce dernier
        # est RECONSTRUIT à chaque tick rapide (4 Hz) alors que l'ombre s'écrit sur la cadence
        # sweep (1 Hz). Écrite directement dans `_extras`, elle n'était visible que 25 % des
        # ticks (mesuré) : un consommateur la verrait clignoter, donc « non mesurée » (/polish).
        self._orderflow_shadow: dict = {}
        # CVD par niveau (D-029) : accumulateur prix -> [buy, sell], seq déjà traité,
        # clé de l'événement du dernier reset, bornes de la fenêtre courante.
        self._cvd_levels: dict[float, list[float]] = {}
        self._cvd_last_seq: int = 0
        self._cvd_reset_key: Optional[str] = None
        self._cvd_reset_ts: Optional[float] = None
        self._cvd_reset_reason: str = ""
        self._cvd_since_ts: Optional[float] = None
        self._fp_prints: deque = deque(maxlen=config.FOOTPRINT_MAX_PRINTS)  # buffer prints footprint (D-037)
        self._fp_last_seq: int = 0
        self._cs_prints: deque = deque(maxlen=config.CVD_STRAT_MAX_PRINTS)  # buffer prints CVD stratifié (D-038)
        self._cs_last_seq: int = 0
        self._vp_levels: dict[int, float] = {}   # Volume Profile : k(prix) → volume accumulé (D-041)
        self._vp_buy: dict[int, float] = {}      # k(prix) → volume ACHETEUR accumulé (side=BUY du tape)
        self._vp_last_seq: int = 0
        self._vp_prev: Optional[dict] = None     # snapshot POC/VAH/VAL de la session précédente
        self._vp_session_day: Optional[int] = None
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

    def _build_cvd(self, tape: MetaField, now: float) -> CvdState:
        """CVD PAR NIVEAU accumulé sur le HOT PATH (déterministe, < 200 ms §7, D-029).

        Reset ÉVÉNEMENTIEL : dès qu'un événement Tier-1 d'`econ_calendar` franchit `now`
        (`now >= ts`) et diffère de celui du dernier reset, l'accumulateur repart à zéro →
        profil de delta frais par régime de news. Puis les prints NEUFS du tape (seq > dernier
        traité) ajoutent leur delta agresseur par prix ; `seq` (id d'ajout de la source)
        empêche tout double comptage entre ticks. Tape non FRESH → accumulation GELÉE +
        `stale=True` (jamais un niveau inventé, §3). Borné à `CVD_MAX_TRACKED` prix (coût de
        tri) et `CVD_MAX_LEVELS` affichés (les plus actifs). Ordre OBSERVÉ, jamais un ordre
        (§2.1)."""
        if self._cvd_since_ts is None:
            self._cvd_since_ts = now

        # --- reset événementiel lié à econ_calendar ---
        cal = self.schema.econ_calendar.events
        if cal.freshness == Freshness.FRESH and isinstance(cal.value, list):
            crossed = [e for e in cal.value if e.get("tier") == 1
                       and isinstance(e.get("ts"), (int, float)) and e["ts"] <= now]
            if crossed:
                latest = max(crossed, key=lambda e: e["ts"])
                key = f"{latest['ts']}|{latest.get('name', '')}"
                if key != self._cvd_reset_key:
                    self._cvd_levels.clear()
                    self._cvd_reset_key = key
                    self._cvd_reset_ts = now
                    self._cvd_reset_reason = str(latest.get("name", ""))
                    self._cvd_since_ts = now

        # --- accumulation des prints NEUFS (seq > dernier traité), tape déjà validé (D-026) ---
        stale = tape.freshness != Freshness.FRESH
        if not stale and isinstance(tape.value, list) and tape.value:
            # Durci /devil : RÉGRESSION de seq (redémarrage source, seq repart bas) → le max
            # de la fenêtre passe SOUS last_seq. Sans détection, le garde `seq <= last_seq`
            # ignore tout print futur → GEL SILENCIEUX. On re-baseline (last_seq = 0) pour
            # reprendre. Un simple traînard (max de fenêtre >= last_seq) n'est PAS une
            # régression : il reste ignoré (déjà passé).
            seqs = [p["seq"] for p in tape.value if isinstance(p.get("seq"), int)]
            if seqs and max(seqs) < self._cvd_last_seq:
                self._cvd_last_seq = 0
            max_seq = self._cvd_last_seq
            for p in tape.value:
                seq = p.get("seq")
                if not isinstance(seq, int) or seq <= self._cvd_last_seq:
                    continue
                price, size, side = p["price"], p["size"], p["side"]
                lvl = self._cvd_levels.get(price)
                if lvl is None:
                    if len(self._cvd_levels) >= CVD_MAX_TRACKED:
                        # Durci /devil : accumulateur plein → ÉVICTION du niveau le moins
                        # actif (au lieu de bloquer les nouveaux) → garde les plus pertinents
                        # près du marché, jamais un verrou silencieux des vrais niveaux.
                        victim = min(self._cvd_levels, key=lambda pr: sum(self._cvd_levels[pr]))
                        del self._cvd_levels[victim]
                    lvl = self._cvd_levels[price] = [0.0, 0.0]
                lvl[0 if side == "BUY" else 1] += size
                max_seq = max(max_seq, seq)
            self._cvd_last_seq = max_seq

        # --- projection : bornée aux plus actifs, triée par prix ---
        items = list(self._cvd_levels.items())
        total = sum(b - s for _, (b, s) in items)
        top = heapq.nlargest(CVD_MAX_LEVELS, items, key=lambda kv: kv[1][0] + kv[1][1])
        levels = [CvdLevel(price=pr, buy=b, sell=s, delta=b - s)
                  for pr, (b, s) in sorted(top, key=lambda kv: kv[0])]
        return CvdState(levels=levels, total_delta=total, since_ts=self._cvd_since_ts,
                        last_reset_ts=self._cvd_reset_ts, reset_reason=self._cvd_reset_reason,
                        stale=stale, capped=len(self._cvd_levels) >= CVD_MAX_TRACKED)

    def _build_footprint(self, tape: MetaField, order_book: MetaField, now: float) -> MetaField:
        """Footprint + imbalances (D-037) : accumule les prints NEUFS du tape (seq-dédup, comme
        le CVD) dans un buffer borné, puis en construit les bougies (agrégation Bid×Ask par
        niveau, POC, imbalances diagonales) — pur via `build_footprint`. Tape non FRESH → pas
        d'accumulation, fraîcheur propagée (fail-closed §3). Hot path : O(prints), borné."""
        if tape.freshness == Freshness.FRESH and isinstance(tape.value, list) and tape.value:
            seqs = [p["seq"] for p in tape.value if isinstance(p.get("seq"), int)]
            if seqs and max(seqs) < self._fp_last_seq:   # régression de seq (redémarrage source)
                self._fp_last_seq = 0
            new_max = self._fp_last_seq
            for p in tape.value:
                seq = p.get("seq")
                if not isinstance(seq, int) or seq <= self._fp_last_seq:
                    continue
                self._fp_prints.append({"ts": p.get("ts"), "price": p.get("price"),
                                        "size": p.get("size"), "side": p.get("side")})
                new_max = max(new_max, seq)
            self._fp_last_seq = new_max

        # Carnet L2 (D-042) : passé UNIQUEMENT s'il est FRESH — un carnet périmé/absent ne doit
        # jamais devenir un mur de liquidité affiché comme réel (§3). Le moteur ne l'applique
        # qu'à la bougie en formation (pas de rétro-attribution aux bougies passées).
        book = order_book.value if order_book.freshness == Freshness.FRESH else None
        candles = build_footprint(
            list(self._fp_prints), config.FOOTPRINT_CANDLE_SECONDS, config.PRICE_TICK,
            config.FOOTPRINT_IMBALANCE_RATIO, config.FOOTPRINT_MIN_IMBALANCE_VOL,
            config.FOOTPRINT_CANDLES, ticks_per_candle=config.FOOTPRINT_TICKS_PER_CANDLE,
            book=book)
        value = {"candles": candles, "tick": config.PRICE_TICK,
                 "ratio": config.FOOTPRINT_IMBALANCE_RATIO,
                 "candle_seconds": config.FOOTPRINT_CANDLE_SECONDS,
                 "ticks_per_candle": config.FOOTPRINT_TICKS_PER_CANDLE}
        return MetaField(value=value, last_update_ts=tape.last_update_ts, source=tape.source,
                         freshness=tape.freshness, flags=tape.flags)

    def _build_cvd_stratified(self, tape: MetaField) -> MetaField:
        """CVD granulaire stratifié par taille (D-038) : accumule les prints NEUFS du tape
        (seq-dédup + re-baseline sur régression, comme le footprint) dans un buffer borné, puis
        `build_cvd_stratified` construit la série cumulée par strate + la divergence — pur.
        Tape non FRESH → pas d'accumulation, fraîcheur propagée (fail-closed §3). Hot path : O(prints)."""
        if tape.freshness == Freshness.FRESH and isinstance(tape.value, list) and tape.value:
            seqs = [p["seq"] for p in tape.value if isinstance(p.get("seq"), int)]
            if seqs and max(seqs) < self._cs_last_seq:   # régression de seq (redémarrage source)
                self._cs_last_seq = 0
            new_max = self._cs_last_seq
            for p in tape.value:
                seq = p.get("seq")
                if not isinstance(seq, int) or seq <= self._cs_last_seq:
                    continue
                self._cs_prints.append({"ts": p.get("ts"), "price": p.get("price"),
                                        "size": p.get("size"), "side": p.get("side")})
                new_max = max(new_max, seq)
            self._cs_last_seq = new_max

        value = build_cvd_stratified(
            list(self._cs_prints), config.CVD_SIZE_THRESHOLD, config.CVD_STRAT_BUCKET_SECONDS,
            config.CVD_STRAT_MAX_POINTS, config.CVD_STRAT_DIV_LOOKBACK,
            config.CVD_STRAT_DIV_MIN_PRICE, config.CVD_STRAT_DIV_MIN_DELTA)
        return MetaField(value=value, last_update_ts=tape.last_update_ts, source=tape.source,
                         freshness=tape.freshness, flags=tape.flags)

    def _build_volume_profile(self, tape: MetaField, session_prev: MetaField, now: float) -> MetaField:
        """Volume Profile (D-041) : accumule le volume par NIVEAU de prix sur la SESSION (dict
        borné par le nombre de niveaux, pas de prints — comme le CVD par niveau D-029), puis
        `build_volume_profile` calcule POC/VA/VAH/VAL/LVN. Au changement de journée : snapshot
        POC/VAH/VAL → `previous` puis reset (projection de la veille). `previous` retombe sur les
        niveaux fournis par la source si aucun snapshot propre. Fail-closed (§3) : tape non FRESH →
        pas d'accumulation, fraîcheur propagée."""
        day = int(now // 86400)
        if self._vp_session_day is None:
            self._vp_session_day = day
        if day != self._vp_session_day and self._vp_levels:   # nouvelle session → snapshot + reset
            prof = build_volume_profile({k * config.PRICE_TICK: v for k, v in self._vp_levels.items()},
                                        config.PRICE_TICK, config.VP_VA_PCT, config.VP_LVN_RATIO,
                                        config.VP_MAX_LEVELS)
            self._vp_prev = {"poc": prof["poc"], "vah": prof["vah"], "val": prof["val"]}
            self._vp_levels = {}
            self._vp_buy = {}
            self._vp_last_seq = 0
            self._vp_session_day = day

        if tape.freshness == Freshness.FRESH and isinstance(tape.value, list) and tape.value:
            seqs = [p["seq"] for p in tape.value if isinstance(p.get("seq"), int)]
            if seqs and max(seqs) < self._vp_last_seq:        # régression de seq (redémarrage source)
                self._vp_last_seq = 0
            new_max = self._vp_last_seq
            for p in tape.value:
                seq, price, size = p.get("seq"), p.get("price"), p.get("size")
                if not isinstance(seq, int) or seq <= self._vp_last_seq:
                    continue
                if isinstance(price, (int, float)) and math.isfinite(price) \
                        and isinstance(size, (int, float)) and math.isfinite(size) and size > 0:
                    k = round(float(price) / config.PRICE_TICK)
                    self._vp_levels[k] = self._vp_levels.get(k, 0.0) + float(size)
                    if p.get("side") == "BUY":                # split acheteur source-backed (§3)
                        self._vp_buy[k] = self._vp_buy.get(k, 0.0) + float(size)
                new_max = max(new_max, seq)
            self._vp_last_seq = new_max

        value = build_volume_profile({k * config.PRICE_TICK: v for k, v in self._vp_levels.items()},
                                     config.PRICE_TICK, config.VP_VA_PCT, config.VP_LVN_RATIO,
                                     config.VP_MAX_LEVELS,
                                     buy_by_price={k * config.PRICE_TICK: v for k, v in self._vp_buy.items()})
        # previous : snapshot propre (session précédente) sinon niveaux fournis par la source
        prev = self._vp_prev
        if prev is None and isinstance(session_prev.value, dict):
            sv = session_prev.value
            prev = {"poc": sv.get("poc"), "vah": sv.get("vah"), "val": sv.get("val")}
        value["previous"] = prev
        return MetaField(value=value, last_update_ts=tape.last_update_ts, source=tape.source,
                         freshness=tape.freshness, flags=tape.flags)

    # ---------- loops ----------

    async def _assemble_fast(self, now: float) -> None:
        redis_up = await self.state.ping()
        raws: dict[str, Optional[dict]] = {}
        if redis_up:
            raws = await self.state.read_raw_many(list(FIELD_SPEC.keys()))

        # s1_state
        order_book = await self._meta("order_book", raws, now)
        _validate_order_book(order_book)
        book_history_push(self._book_history, order_book, now)   # D-056 — FRESH seulement
        tape = await self._meta("tape", raws, now)
        _validate_tape(tape)
        # Heatmap LOB (D-036) : diffusion en DELTA — n'émet QUE la colonne courante (le frontend
        # accumule la fenêtre). Payload ~60× plus léger. Fail-closed : carnet non FRESH → None (§3).
        liquidity_heatmap = MetaField(
            value={"column": latest_column(order_book, now, config.HEATMAP_LEVELS)},
            last_update_ts=order_book.last_update_ts, source=order_book.source,
            freshness=order_book.freshness, flags=order_book.flags)
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
            cvd_by_level=self._build_cvd(tape, now),  # accumulation par niveau, hot path (D-029)
            chop=await self._meta("chop", raws, now),
            order_book=order_book,
            liquidity_heatmap=liquidity_heatmap,
            tape=tape,
            footprint=self._build_footprint(tape, order_book, now),  # D-037/042 : Bid×Ask + delta + L2
            cvd_stratified=self._build_cvd_stratified(tape),  # D-038 : CVD par strate de taille + divergence
            volume_profile=self._build_volume_profile(     # D-041 : profil volumétrique + VA/POC/LVN
                tape, await self._meta("session_prev", raws, now), now),
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

        # Macro Risk Guard (D-040) — projection RAPIDE du régime, MÊME calcul déterministe que la
        # règle Phase 0 MACRO_BLACKOUT (verrou unique §2.2). Calendrier depuis le dernier tick lent.
        cal = self.schema.macro_calendar.value
        mc_events = cal.get("events") if isinstance(cal, dict) else None
        self.schema.macro_risk = MetaField(
            value=compute_macro_risk(mc_events if isinstance(mc_events, list) else [], now,
                                     config.MACRO_PAUSE_WINDOW_S, config.MACRO_WARN_WINDOW_S),
            last_update_ts=now, source="macro_engine", freshness=Freshness.FRESH)

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
                        "scenario": {"name": scenario["name"], "label": scenario["label"]},
                        # Recomposée ici, à l'endroit UNIQUE où `_extras` se construit.
                        "orderflow_shadow": self._orderflow_shadow}

        if redis_up:
            await self.state.beat()

        # Porte F0 VISIBLE (D-050 polish) : l'opérateur voit l'état news en Zone 0 — jamais un
        # verrou invisible. `get_state` est PUR et O(petit) : dans le budget hot path (§7).
        # None = couche non câblée (pas de porte) ; provider cassé = SAFETY_UNKNOWN (aveugle).
        if self.news_provider is not None:
            try:
                self._extras["news_state"] = self.news_provider.get_state(now).value
            except Exception:
                self._extras["news_state"] = "SAFETY_UNKNOWN"
        else:
            self._extras["news_state"] = None

        # account_state (D-051) : la « distance vers la mort » VISIBLE en Zone C. `account_view`
        # est PURE et O(1) — dans le budget hot path (§7). Provider absent/cassé/périmé →
        # DISCONNECTED sans aucune valeur affichable (§3), jamais une équité inventée.
        account_now: Optional[AccountState] = None
        if self.account_provider is not None:
            try:
                candidate = self.account_provider.current(now)
                account_now = candidate if isinstance(candidate, AccountState) else None
            except Exception:
                account_now = None
        self.schema.account_state = AccountStateBlock(
            **account_view(account_now, vix=self._vix_pour_sizing()))

        dump = self.schema.model_dump(mode="json")
        for block in ("session_identity", "s1_state", "bridge_variables",
                      "sync_state", "unified_signal_output", "macro_risk", "account_state"):
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
             "econ_calendar", "macro_releases", "options_chain", "vol_term_structure",
             "g_momentum", "pi_momentum", "d1", "d2", "d3", "d4", "d5",
             "taylor_ois_delta", "phillips_tips_delta", "beer_z", "carry_net",
             "cycle_div_delta", "leading_turn", "rr_zscore", "spot_momentum", "long_short", "yields"])
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
        econ = await self._meta("econ_calendar", raws, now)
        _validate_econ_calendar(econ, now)
        self.schema.econ_calendar = EconCalendar(events=econ)
        self.schema.vol_surface = await self._build_vol_surface(raws, now)  # D-039
        # Macro : publications éco TRADABLES normalisées (D-040) ; fraîcheur propagée du raw (§3).
        mr = await self._meta("macro_releases", raws, now)
        self.schema.macro_calendar = MetaField(
            value=build_macro_calendar(mr.value if isinstance(mr.value, list) else [], now,
                                       config.MACRO_PAST_GRACE_S, config.MACRO_MAX_EVENTS),
            last_update_ts=mr.last_update_ts, source=mr.source, freshness=mr.freshness, flags=mr.flags)
        # Positionnement Long/Short (D-053) — la FRAÎCHEUR reste celle du brut ; seule la valeur
        # est normalisée. Un lot inexploitable rend None → le bloc devient ABSENT plutôt que
        # « connecté mais vide » (§3), et le panneau affiche PAS DE DONNÉES.
        # Courbe des taux (D-053) — mêmes règles : fraîcheur portée par le brut, valeur
        # normalisée, et AUCUN spread calculé sur un ténor manquant (app/rates.py).
        yc = await self._meta("yields", raws, now)
        self.schema.yield_curve = MetaField(
            value=build_yield_curve(yc.value), last_update_ts=yc.last_update_ts,
            source=yc.source, freshness=yc.freshness, flags=yc.flags)
        ls = await self._meta("long_short", raws, now)
        self.schema.long_short_ratio = MetaField(
            value=build_long_short(ls.value), last_update_ts=ls.last_update_ts,
            source=ls.source, freshness=ls.freshness, flags=ls.flags)
        dump = self.schema.model_dump(mode="json")
        broadcaster.publish("slow", "s2_state", dump["s2_state"])
        broadcaster.publish("slow", "econ_calendar", dump["econ_calendar"])
        broadcaster.publish("slow", "vol_surface", dump["vol_surface"])
        broadcaster.publish("slow", "long_short_ratio", dump["long_short_ratio"])
        broadcaster.publish("slow", "yield_curve", dump["yield_curve"])
        broadcaster.publish("slow", "macro_calendar", dump["macro_calendar"])

    async def _build_vol_surface(self, raws: dict, now: float) -> VolSurface:
        """Surface de volatilité (D-039) : la chaîne d'options brute (Greeks engine) est classée
        par `build_options_chain` (moneyness, tri, bornage) ; la structure de vol (CBOE) par
        `build_term_structure` (ordre + état). Fraîcheur propagée du raw → STALE honnête si le
        moteur Greeks ralentit (§8-B2). Fail-closed : raw absent → structure vide (§3)."""
        oc = await self._meta("options_chain", raws, now)
        raw_oc = oc.value if isinstance(oc.value, dict) else {}
        chain = build_options_chain(
            raw_oc.get("expirations") if isinstance(raw_oc.get("expirations"), list) else [],
            raw_oc.get("underlying"), config.OPTIONS_ATM_BAND,
            config.OPTIONS_MAX_EXPIRATIONS, config.OPTIONS_MAX_STRIKES,
            r=config.RISK_FREE_RATE)          # D-044 : IV inversée + Grecques calculées
        options_chain = MetaField(value=chain, last_update_ts=oc.last_update_ts,
                                  source=oc.source, freshness=oc.freshness, flags=oc.flags)
        vt = await self._meta("vol_term_structure", raws, now)
        raw_vt = vt.value if isinstance(vt.value, dict) else {}
        ts = build_term_structure(
            raw_vt.get("points") if isinstance(raw_vt.get("points"), list) else [],
            config.VOL_TERM_FLAT_EPS)
        term_structure = MetaField(value=ts, last_update_ts=vt.last_update_ts,
                                   source=vt.source, freshness=vt.freshness, flags=vt.flags)
        return VolSurface(options_chain=options_chain, term_structure=term_structure)

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

    async def _assemble_sweep(self, now: float) -> None:
        """Détection Liquidity Sweep (D-028) — advisory, HORS hot path (§2.8). Lecture du
        schéma SYNCHRONE (snapshot cohérent, aucun await intermédiaire → pas de torn read
        vs _assemble_fast), puis invocation du graphe OFFLOADÉE (`to_thread`) : la boucle
        d'événements — donc le tick fast < 200 ms — n'est JAMAIS bloquée. Le détecteur est
        déterministe (pas de LLM), mais reste async par contrat. Le feed `recent` est
        dédupliqué par clé (trigger|direction) : une condition persistante n'inonde pas ;
        un sweep qui se lève puis re-déclenche = un nouvel événement. Émet une ALERTE
        observée, jamais un ordre (§2.1)."""
        state = build_sweep_inputs(self.schema, now)
        result = await asyncio.to_thread(
            SWEEP_GRAPH.invoke, state, {"configurable": {"thread_id": "sweep"}})
        triggered = bool(result.get("triggered"))
        alert_dict = result.get("alert") if triggered else None
        key = (f"{alert_dict['trigger']}|{alert_dict.get('direction')}"
               if alert_dict else None)
        if key and key != self._sweep_last_key:
            self._sweep_recent.appendleft(alert_dict)
        self._sweep_last_key = key   # None quand non déclenché → prochain sweep = neuf
        self.schema.liquidity_sweep = LiquiditySweep(
            assessable=bool(result.get("data_ok")),
            triggered=triggered,
            reason=result.get("reason", ""),
            alert=LiquiditySweepAlert(**alert_dict) if alert_dict else None,
            last_compute_ts=now,
            recent=[LiquiditySweepAlert(**a) for a in self._sweep_recent])
        broadcaster.publish("fast", "liquidity_sweep",
                            self.schema.liquidity_sweep.model_dump(mode="json"))

    def _maybe_emit_lsr(self, now: float) -> None:
        """Pipeline LSR (D-046) : sweep → evaluate_lsr → TradeManifest → SSE. Pur, déterministe
        et borné (sub-ms) — il tourne sur la cadence SWEEP (hors hot path §2.8), jamais dans la
        boucle fast. Rejet = SILENCE (§3) ; approbation = UNE émission par alerte distincte,
        revérifiée par la garde D-045, publiée SANS cache de replay (événement éphémère — un
        abonné neuf ne doit jamais recevoir un ticket d'avant sa connexion). Aucun ordre (§2.1) :
        le manifeste est une proposition affichée, l'humain tranche."""
        sw = self.schema.liquidity_sweep
        alert = sw.alert if sw.triggered else None
        # Mesures MAISON (D-055) calculées à chaque tick sweep, QUEL QUE SOIT LE MODE : c'est la
        # preuve qu'on accumule avant d'oser basculer la source de vérité du chemin d'émission.
        # Hors hot path (cadence sweep, ~3 ms mesurés) et sans effet sur la décision en mode
        # "source" — le défaut reste le comportement historique.
        if alert is not None and alert.direction is not None:
            event_key = f"{alert.trigger}|{alert.direction}"
            if event_key != self._sweep_event_key:
                # Événement NEUF (y compris un simple changement de direction) : la mesure
                # redémarre ici. Continuer sur l'ancienne fenêtre décrirait le mur précédent.
                self._sweep_event_key, self._sweep_event_ts = event_key, now
        else:
            self._sweep_event_key, self._sweep_event_ts = None, None
        snapshot = snapshot_for_lsr(
            self.schema, self._book_history, now=now,
            sweep_ts=self._sweep_event_ts,
            sweep_direction=alert.direction if alert else None)
        self._orderflow_shadow = orderflow_shadow(self.schema, snapshot)
        self._extras["orderflow_shadow"] = self._orderflow_shadow
        if not sw.triggered:
            # Condition levée → le PROCHAIN sweep est un événement NEUF (même sémantique que
            # `_sweep_last_key`, D-028). Sans ce reset, un trigger|direction identique plus tard
            # dans la session resterait dédupliqué à tort.
            self._lsr_emitted_key = None
            return
        if alert is None or alert.direction is None:
            return                                    # inorientable → pas de réversion
        # Identité de l'ÉVÉNEMENT, pas du tick : `alert.ts` est régénéré à chaque évaluation
        # d'une condition persistante — même composition de clé que D-028 (trigger|direction).
        key = f"{alert.trigger}|{alert.direction}"
        if key == self._lsr_emitted_key:
            return                                    # condition persistante = UN seul manifeste
        # F7-like — fenêtre anti-FOMO : sous un détecteur qui bascule BID/ASK en continu (vu au
        # /devil live sur le mock), la clé change à chaque bascule ; sans cette borne, chaque
        # alternance ré-émettrait. Une émission max par fenêtre, quel que soit l'événement.
        if now - self._lsr_last_emit_ts < config.LSR_REARM_COOLDOWN_S:
            return
        # Porte F0 (D-050) : l'état news est calculé ICI (get_state est pur, zéro I/O) et entre
        # dans LsrInputs — un provider cassé vaut un état AVEUGLE (fail-closed), jamais un crash.
        news_state: Optional[str] = None
        if self.news_provider is not None:
            try:
                news_state = self.news_provider.get_state(now).value
            except Exception:
                news_state = "SAFETY_UNKNOWN"
        plan = evaluate_lsr(build_lsr_inputs(self.schema, now, news_state=news_state,
                                             orderflow=snapshot))
        if plan is None:
            return                                    # gates rouges / F0 → silence
        # COUCHE COMPTE (D-047) : on ne trade JAMAIS à l'aveugle. Pas de source, source
        # déconnectée/périmée, ou RiskSizer en rejet (F8, corruption, plafond) → silence.
        if self.account_provider is None:
            return
        # Le PORT dit « rendre None » — mais un provider réel cassé peut LEVER (socket morte en
        # pleine lecture) ou rendre un mauvais type : coupure = rejet naturel = SILENCE, jamais
        # un log.exception par tick de flapping (hygiène D-046), jamais un AttributeError.
        try:
            account = self.account_provider.current(now)
        except Exception:
            account = None
        if not isinstance(account, AccountState):
            return                                    # équité fossile/absente/corrompue ≠ équité (§3)
        plan = size_plan(plan, account, vix=self._vix_pour_sizing())
        if plan is None:
            return                  # F8, ou VIX suspendu/aveugle : pas de taille à émettre
        manifest = manifest_from_lsr_plan(plan, now_ms=int(now * 1000))
        if manifest is None:
            return                                    # la frontière D-045 a le dernier mot
        broadcaster.publish("fast", "trade_manifest", manifest.model_dump(), replay=False)
        self._lsr_emitted_key = key
        self._lsr_last_emit_ts = now
        # L4 `gates.eval` (D-080) : l'armement est le point d'appel UNIQUE des balises O1-O5.
        # Appelé APRÈS l'émission, donc structurellement incapable de la retenir — mode G2,
        # consultatif, point final. Le callback est borné et isolé par la boucle L4 ; ici on
        # garantit seulement qu'il ne peut pas faire tomber le tick d'émission.
        if self._on_arm is not None:
            try:
                self._on_arm(manifest)
            except Exception:
                log.exception("L4 gates.eval a échoué sur l'armement %s "
                              "(consultatif : le manifeste reste émis)", manifest.id)
        # HYGIÈNE DES LOGS (D-046 /polish) : le moteur évalue en continu — un rejet naturel ne
        # logge RIEN (silence structurel : evaluate_lsr est pur, aucun logger dedans). Seule
        # l'ÉMISSION, événement rare et significatif, mérite son unique ligne INFO.
        log.info("LSR manifest émis : %s %s — entrée %s · stop %s · TP %s · %s contrat(s) [%s]",
                 manifest.direction, manifest.instrument, manifest.entry.price,
                 manifest.risk.stopLoss, manifest.risk.takeProfit,
                 manifest.risk.positionSize, manifest.id)

    async def _sweep_loop(self) -> None:
        while True:
            started = time.time()
            try:
                await self._assemble_sweep(time.time())
                self._maybe_emit_lsr(time.time())
            except Exception:
                log.exception("sweep loop tick failed (fail-closed: no alert emitted)")
            elapsed = time.time() - started
            await asyncio.sleep(max(0.1, config.SWEEP_TICK_SECONDS - elapsed))

    def _vix_pour_sizing(self) -> Optional[float]:
        """VIX **FRESH** du schéma pour le modificateur de sizing (D-070), ou `None`.

        Un VIX périmé n'est pas un VIX (§3) : il vaut ici « je ne vois pas la volatilité », et
        `vix_multiplier` en fait 0 — donc le sizer suspend. C'est volontairement plus sévère
        qu'un blocage à 30 : on ne dimensionne pas sur un régime qu'on ne mesure plus."""
        meta = getattr(self.schema.s2_state.cascade, "vix", None)
        if meta is None or meta.freshness != Freshness.FRESH:
            return None
        value = meta.value
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else None

    async def start(self) -> None:
        # Un `LSR_INSTRUMENT` hors de la table de calibration (D-069) rend `evaluate_lsr`
        # DÉFINITIVEMENT muet — fail-closed correct, mais silencieux : une faute de frappe dans
        # l'environnement ressemblerait exactement à « aucun setup aujourd'hui ». Le dire une
        # fois au démarrage est la différence entre un moteur calme et un moteur mort.
        if lsr_tuning.tuning(config.LSR_INSTRUMENT) is None:
            log.error("LSR_INSTRUMENT=%r n'est pas calibré (connus : %s) — le moteur LSR "
                      "n'émettra AUCUN manifeste tant que ce n'est pas corrigé",
                      config.LSR_INSTRUMENT, ", ".join(sorted(lsr_tuning.PER_INSTRUMENT)))
        self._tasks = [asyncio.create_task(self._fast_loop()),
                       asyncio.create_task(self._slow_loop()),
                       asyncio.create_task(self._sweep_loop())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # snapshot for GET /state
    def snapshot(self) -> dict[str, Any]:
        return {"schema": self.schema.model_dump(mode="json"), "extras": self._extras}
