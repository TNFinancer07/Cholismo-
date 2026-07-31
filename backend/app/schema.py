"""ContextSchema v1.0 — the single source of truth (PRD §0).

One panel = one block of this schema. Every leaf field is a MetaField
{value, last_update_ts, source, freshness}. The schema is ONE object conceptually but is
pushed over cadence-segmented SSE channels as partial per-block events (CLAUDE §6).

Mirrored 1:1 by frontend/src/types/schema.ts — keep both in sync.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .meta import MetaField


# --- session_identity → ZONE 0 (statut) ---

class SessionMarker(str, Enum):
    LONDRES_OBS = "LONDRES_OBS"
    OVERLAP_NY = "OVERLAP_NY"
    HORS_SESSION = "HORS_SESSION"


class OperationalMode(str, Enum):
    PRE_SESSION = "PRE_SESSION"
    LIVE = "LIVE"
    POST_SESSION = "POST_SESSION"


class Operator(str, Enum):
    SONY = "SONY"
    YOUSSEF = "YOUSSEF"


class Phase0State(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"


class MasterState(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    DEGRADED = "DEGRADED"


class Phase0Blocker(BaseModel):
    rule: str
    label: str          # UI label (French)
    detail: str = ""
    severity: str = "CRIT"  # CRIT blocks; WARN is displayed but does not block


class SessionIdentity(BaseModel):
    clock_local: str = "America/Montreal"
    session_marker: SessionMarker = SessionMarker.HORS_SESSION
    operational_mode: OperationalMode = OperationalMode.PRE_SESSION
    operator: Operator = Operator.SONY
    phase0: Phase0State = Phase0State.BLOCKED       # deterministic engine, fail-closed default
    phase0_blockers: list[Phase0Blocker] = Field(default_factory=list)
    phase0_warnings: list[Phase0Blocker] = Field(default_factory=list)
    phase0_advisory: str = "UNAVAILABLE"            # Groq advisory — NEVER the lock (CLAUDE §2.2)
    master_state: MasterState = MasterState.NOT_READY
    server_ts: float = 0.0


# --- s1_state → B1 left (Sony, cyan) [fast] ---

class OrderFlow(BaseModel):
    cvd: MetaField = Field(default_factory=MetaField)
    absorption: MetaField = Field(default_factory=MetaField)
    aggressor_ratio: MetaField = Field(default_factory=MetaField)


class Structure(BaseModel):
    vpoc: MetaField = Field(default_factory=MetaField)
    vah: MetaField = Field(default_factory=MetaField)
    val: MetaField = Field(default_factory=MetaField)
    lvn: MetaField = Field(default_factory=MetaField)  # value: list[float]


class StrategyGate(BaseModel):
    """One gate/filter of an execution strategy. status: PASS | FAIL | ABSENT (data
    missing -> fail-closed) | MANUAL (source not wired, operator's responsibility)."""
    name: str
    status: str = "MANUAL"
    detail: str = ""


class ExecutionStrategy(BaseModel):
    """Sony execution strategy card — AUTORITÉ params from /reference/sony/* (D-021)."""
    strategy_id: str
    label: str
    version: str
    window: str
    score_threshold: str
    eligible: bool = False
    sizing_pct: Optional[float] = None    # % of calibration size after VIX/session modifiers
    gates: list[StrategyGate] = Field(default_factory=list)
    reference: str = ""


class S1Strategies(BaseModel):
    svs: ExecutionStrategy
    mean_reversion: ExecutionStrategy


class CvdLevel(BaseModel):
    """Delta agresseur net accumulé à un niveau de prix (D-029)."""
    price: float
    delta: float    # buy − sell (net) depuis le dernier reset
    buy: float
    sell: float


class CvdState(BaseModel):
    """CVD PAR NIVEAU avec réinitialisation événementielle (D-029). Accumulé sur le HOT PATH
    (déterministe, < 200 ms §7) à partir des prints OBSERVÉS du tape — jamais un ordre (§2.1).
    Reset lié aux événements Tier-1 d'`econ_calendar` : profil de delta frais par régime de
    news. `stale=True` quand le tape n'est plus FRESH → accumulation gelée, honnête (§3)."""
    levels: list[CvdLevel] = Field(default_factory=list)  # bornés, triés par prix
    total_delta: float = 0.0
    since_ts: Optional[float] = None       # début de la fenêtre d'accumulation courante
    last_reset_ts: Optional[float] = None  # dernier reset ÉVÉNEMENTIEL (None si jamais)
    reset_reason: str = ""                 # libellé de l'événement déclencheur
    stale: bool = False                    # tape non FRESH → accumulation gelée (§3)
    capped: bool = False                   # accumulateur saturé (éviction active), honnête


class S1State(BaseModel):
    svs_score: MetaField = Field(default_factory=MetaField)
    order_flow: OrderFlow = Field(default_factory=OrderFlow)
    structure: Structure = Field(default_factory=Structure)
    cvd_by_level: CvdState = Field(default_factory=CvdState)
    chop: MetaField = Field(default_factory=MetaField)
    # DOM ES 10 niveaux (D-025) — value: {"bids": [[price, size]…], "asks": [[price, size]…]},
    # bids décroissants / asks croissants. Affichage lecture seule, PAS critique Phase 0 en v1.
    order_book: MetaField = Field(default_factory=MetaField)
    # Heatmap de liquidité (D-036) — DELTA : value: {column: {ts, bids:[[p,s]…], asks:[[p,s]…]}
    # | null}. Le backend n'émet QUE la colonne courante (4 Hz) ; le frontend Canvas accumule la
    # fenêtre glissante. Lecture seule (§2.1). Fraîcheur = celle du carnet (fail-closed §3).
    liquidity_heatmap: MetaField = Field(default_factory=MetaField)
    # Tape / Time & Sales (D-026) — value: [{ts, price, size, side ∈ BUY|SELL, seq}…],
    # fenêtre glissante bornée, plus récent en tête. Prints OBSERVÉS (pas des ordres, §2.1).
    tape: MetaField = Field(default_factory=MetaField)
    # Footprint + imbalances (D-037) — value: {candles: [{start_ts, end_ts, open, high, low,
    # close, poc, total_volume, levels: [{price, bid_vol, ask_vol, imbalance ∈ ASK|BID|null}]}…],
    # tick, ratio, candle_seconds}. Agrégation Bid×Ask par niveau/bougie. Lecture seule (§2.1).
    footprint: MetaField = Field(default_factory=MetaField)
    # CVD granulaire stratifié par taille (D-038) — value: {size_threshold, series: [{ts, price,
    # retail, institutional, total}…], divergence: {kind ∈ BULLISH|BEARISH, price_change,
    # inst_change, bars} | null}. Delta agresseur net cumulé par strate de taille + divergence
    # prix↔CVD institutionnel (advisory §2.1). Lecture seule (§2.1). Fail-closed (§3).
    cvd_stratified: MetaField = Field(default_factory=MetaField)
    # Volume Profile dynamique (D-041) — DISTRIBUTION auto-calculée du volume par prix sur la
    # session (distinct des scalaires source `structure.*`). value: {tick, va_pct, total_volume,
    # poc, vah, val, levels: [{price, volume, buy?, sell?}], lvn: [prix], previous: {poc, vah, val}
    # | null}. `buy`/`sell` (split acheteur/vendeur, source `side` du tape) présents seulement si
    # fournis — jamais inventés (§3). Lecture seule (§2.1).
    volume_profile: MetaField = Field(default_factory=MetaField)
    # The two REAL Sony execution strategies (reference/sony/*), evaluated live (D-021).
    strategies: Optional[S1Strategies] = None


# --- s2_state → B1 right + ZONE A (Youssef, violet) [slow] ---

class Cascade(BaseModel):
    nq_es: MetaField = Field(default_factory=MetaField)
    vix: MetaField = Field(default_factory=MetaField)
    zn: MetaField = Field(default_factory=MetaField)
    dx: MetaField = Field(default_factory=MetaField)
    eurusd: MetaField = Field(default_factory=MetaField)
    real_rates: MetaField = Field(default_factory=MetaField)  # primary driver (PRD §A1)


class S2MacroScore(BaseModel):
    """A3 — honest, never fake (CLAUDE §8.1). value stays None until CALIBRATED."""
    value: Optional[float] = None
    calibrated: bool = False
    # Inputs shown even when not calibrated, to help calibration (PRD §A3):
    coherence: Optional[float] = None
    tilt: Optional[float] = None
    gate: Optional[float] = None


class MacroRegime(BaseModel):
    """Phase 0 Youssef — VIX kurtosis regime with hysteresis (reference/youssef/01)."""
    tier: str = "GREEN"                    # GREEN | YELLOW | ORANGE | RED
    vix: Optional[float] = None
    kurtosis: Optional[float] = None       # not fed by the mock -> None (honest)
    carry_mult: float = 1.0
    fund_mult: float = 1.0
    score_mult: float = 1.0


class BridgewaterQuadrant(BaseModel):
    """Étape 0 — quadrant from (g, pi) momentum; weights table AUTORITÉ file 1 (D-021)."""
    quadrant: Optional[str] = None
    g: Optional[float] = None
    pi: Optional[float] = None
    r: Optional[float] = None
    theta: Optional[float] = None
    confidence: Optional[float] = None
    transition_risk: str = "unknown"
    weights: dict[str, float] = Field(default_factory=dict)


class Flux1(BaseModel):
    """N3 Flux 1 — weighted tanh aggregation + D4 gate + 4 horizons (reference/youssef/03)."""
    d_scores: dict[str, Optional[float]] = Field(default_factory=dict)
    raw_score: Optional[float] = None
    score_final: Optional[float] = None
    conviction: Optional[float] = None
    direction: str = "NEUTRE"
    horizons: dict[str, Optional[float]] = Field(default_factory=dict)


class Arbitrage(BaseModel):
    """N3 Flux 2 — one of the 6 anticipation arbitrages (thresholds AUTORITÉ file 3)."""
    arb_id: int
    name: str
    source_dim: str
    horizon: str
    threshold: str
    active: Optional[bool] = None          # None = inputs missing
    delta: Optional[float] = None
    direction: Optional[str] = None
    conviction: Optional[float] = None
    note: str = ""


class S2Pipeline(BaseModel):
    regime: MacroRegime = Field(default_factory=MacroRegime)
    quadrant: BridgewaterQuadrant = Field(default_factory=BridgewaterQuadrant)
    flux1: Flux1 = Field(default_factory=Flux1)
    arbitrages: list[Arbitrage] = Field(default_factory=list)


class S2State(BaseModel):
    cascade: Cascade = Field(default_factory=Cascade)
    bridgewater_matrix: MetaField = Field(default_factory=MetaField)  # value: 5x6 signed intensities
    s2_macro_score: S2MacroScore = Field(default_factory=S2MacroScore)
    # The REAL Youssef macro pipeline (reference/youssef/01-03), formulas AUTORITÉ,
    # inputs simulated by the mock until real feeds exist (D-021).
    pipeline: Optional[S2Pipeline] = None


# --- bridge_variables → B2 [fast] ---

class BridgeVariables(BaseModel):
    gex: MetaField = Field(default_factory=MetaField)
    gex_last_compute_ts: Optional[float] = None  # -> real data AGE, never a fake countdown (PRD §B2)
    vvix: MetaField = Field(default_factory=MetaField)
    dxy: MetaField = Field(default_factory=MetaField)


# --- vol_surface → OMON (chaîne d'options) + VTS (term structure) [slow] (D-039) ---

class VolSurface(BaseModel):
    """Surface de volatilité (canal LENT) : chaîne d'options + structure par échéance. Comme la
    vitesse du moteur Greeks est INCONNUE (§8-B2), l'âge réel de la donnée pilote la fraîcheur —
    STALE honnête, jamais un chiffre inventé (§3). Lecture seule (§2.1)."""
    # value: {underlying, atm_strike, expirations: [{expiry, dte, atm_strike, rows: [{strike,
    # call, put}]}]} ; call/put = {iv, delta, gamma, vanna, charm, moneyness ∈ ITM|ATM|OTM|null}.
    options_chain: MetaField = Field(default_factory=MetaField)
    # value: {points: [{tenor, days, value}], state ∈ CONTANGO|BACKWARDATION|FLAT|null,
    # front_back_spread}. Structure de vol VIX9D/VIX/VIX3M/VIX6M.
    term_structure: MetaField = Field(default_factory=MetaField)


# --- sync_state → B3 [fast] ---

class SyncVerdict(str, Enum):
    ALIGNED = "ALIGNED"
    DIVERGENT = "DIVERGENT"
    PARTIAL = "PARTIAL"


class SyncState(BaseModel):
    verdict: SyncVerdict = SyncVerdict.PARTIAL
    detail: str = ""


# --- unified_signal_output → B4 (Router, gold) [fast] ---

class Decision(str, Enum):
    PENDING = "PENDING"
    GO = "GO"
    NO_GO = "NO_GO"


class SignalBreakdown(BaseModel):
    structure: Optional[float] = None    # /35
    order_flow: Optional[float] = None   # /25
    macro: Optional[float] = None        # /20 — None when NOT CALIBRATED (weight -> 0)
    sentiment: Optional[float] = None    # /15
    quality: Optional[float] = None      # /5


class DecisionWindow(BaseModel):
    """C3 anti-paralysis countdown — visible only while a decision is pending."""
    open: bool = False
    opened_ts: Optional[float] = None
    deadline_ts: Optional[float] = None
    instrument: Optional[str] = None


class UnifiedSignalOutput(BaseModel):
    score: Optional[float] = None
    degraded: bool = False               # true when macro not calibrated (renormalized /80)
    breakdown: SignalBreakdown = Field(default_factory=SignalBreakdown)
    decision: Decision = Decision.PENDING
    decision_window: DecisionWindow = Field(default_factory=DecisionWindow)


# --- econ_calendar → panneau EC (SYSTÉMIQUE, macro/géo) [slow] ---

class EconCalendar(BaseModel):
    """Calendrier économique/géopolitique — feed SYSTÉMIQUE (impacte la liquidité pour LES
    DEUX opérateurs : la fenêtre Tier-1 ±30 min est un filtre Phase 0 de Sony,
    reference/MANIFEST §Sony·SVS ; les publications macro pèsent aussi sur l'EUR/USD de
    Youssef). `events.value` = liste d'événements PROGRAMMÉS {ts, name, tier, region},
    tier = impact liquidité (1 fort / 2 modéré / 3 faible). Un panneau lit `events`.
    Le compte à rebours est une dérivation CLIENT du `ts` CONNU de chaque événement —
    honnête et précis, contrairement au TTL GEX de B2 (péremption inconnue, §8.2). La
    fenêtre T1 ±30 min est SURFACÉE ici, PAS (encore) câblée dans le moteur déterministe
    Phase 0 (feature séparée) : l'UI n'y prononce jamais OPEN/BLOQUÉ (§2.2)."""
    events: MetaField = Field(default_factory=MetaField)  # value: list[{ts, name, tier, region}]


# --- liquidity_sweep → panneau IA (détecteur LangGraph, advisory async, D-028) [fast] ---

class LiquiditySweepAlert(BaseModel):
    """Alerte du détecteur de Liquidity Sweep (app/graph/liquidity_sweep.py). Événement
    OBSERVÉ, jamais un ordre (§2.1). Tous les champs dérivent déterministiquement des
    entrées — aucune valeur inventée (« sans hallucination », §2.8)."""
    ts: float
    kind: str = "LIQUIDITY_SWEEP"
    direction: Optional[str] = None       # BID_SWEEP | ASK_SWEEP | None
    spread_width: Optional[float] = None  # en ticks
    delta_volume: Optional[float] = None
    trigger: str = ""                     # TAPE_BURST | WIDE_SPREAD | CROSSED_BOOK (combinés par +)
    news_context: str = ""
    reason: str = ""


class LiquiditySweep(BaseModel):
    """Bloc de sortie du détecteur — advisory ASYNC, JAMAIS un verrou hot-path (§2.8).
    `assessable` distingue « pas de sweep » (True+triggered False) de « impossible à
    évaluer » (False, données insuffisantes) : un détecteur honnête ne confond pas « tout
    va bien » et « je ne sais pas ». `recent` = feed court des dernières alertes distinctes."""
    assessable: bool = False
    triggered: bool = False
    reason: str = ""
    alert: Optional[LiquiditySweepAlert] = None
    last_compute_ts: Optional[float] = None   # âge RÉEL de la dernière évaluation (comme B2)
    recent: list[LiquiditySweepAlert] = Field(default_factory=list)


# --- account_state → Zone C HUD (« distance vers la mort », D-051) [fast] ---

class NextTicket(BaseModel):
    """Taille que porterait le PROCHAIN ticket sur un stop de RÉFÉRENCE — affichage préventif :
    l'opérateur voit sa capacité AVANT qu'une alerte tombe. `contracts` n'existe que sur
    APPROVED (jamais un 0 déguisé en taille, §3) ; sinon `status` dit POURQUOI."""
    instrument: str = ""
    stop_ticks: int = 0
    contracts: Optional[int] = None
    risk_allowed: Optional[float] = None
    status: str = "DISCONNECTED"


class AccountStateBlock(BaseModel):
    """État de compte prop-firm projeté pour l'affichage (D-047/048 → D-051). OBSERVÉ, jamais un
    ordre (§2.1). `buffer_initial` = buffer à l'OUVERTURE du jour = dénominateur de la jauge.
    FAIL-CLOSED : sans source exploitable (périmée OU déconnectée — le port D-047 ne distingue
    pas), `status=DISCONNECTED`, `is_stale=True` et TOUTES les valeurs restent None."""
    status: str = "DISCONNECTED"
    is_stale: bool = True
    current_equity: Optional[float] = None
    day_start_equity: Optional[float] = None
    drawdown_floor: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    buffer: Optional[float] = None
    buffer_initial: Optional[float] = None
    day_pnl: Optional[float] = None
    next_ticket: NextTicket = Field(default_factory=NextTicket)


# --- Full schema (conceptual object; transported as partial per-block SSE events) ---

class ContextSchema(BaseModel):
    session_identity: SessionIdentity = Field(default_factory=SessionIdentity)
    s1_state: S1State = Field(default_factory=S1State)
    s2_state: S2State = Field(default_factory=S2State)
    bridge_variables: BridgeVariables = Field(default_factory=BridgeVariables)
    sync_state: SyncState = Field(default_factory=SyncState)
    unified_signal_output: UnifiedSignalOutput = Field(default_factory=UnifiedSignalOutput)
    econ_calendar: EconCalendar = Field(default_factory=EconCalendar)
    liquidity_sweep: LiquiditySweep = Field(default_factory=LiquiditySweep)
    vol_surface: VolSurface = Field(default_factory=VolSurface)
    # Moteur Macro (D-040) — publications éco TRADABLES (distinct d'econ_calendar D-027, macro/géo
    # systémique). value: {events: [{ts, name, country, currency, impact ∈ HIGH|MED|LOW, consensus,
    # previous, actual, surprise}]}. Canal LENT. Lecture seule (§2.1).
    macro_calendar: MetaField = Field(default_factory=MetaField)
    # Risk Guard déterministe (D-040) — projection du régime (§2.2, câblé à Phase 0 MACRO_BLACKOUT).
    # value: {regime ∈ NORMAL|WARNING|EXECUTION_PAUSED, event: {name, ts, impact, country} | null,
    # seconds_until, in_window}. Canal RAPIDE (régime + countdown frais, en phase avec Phase 0).
    macro_risk: MetaField = Field(default_factory=MetaField)
    # Compte prop-firm (D-051) — Zone C HUD : équité, buffer (« distance vers la mort »), ticket
    # de référence pré-calculé. Canal RAPIDE (l'opérateur doit voir sa capacité en temps réel).
    account_state: AccountStateBlock = Field(default_factory=AccountStateBlock)
    # Positionnement Long/Short agrégé (D-053) — panneau SENT. value: {venue, extreme_pct,
    # dropped, instruments: [{symbol, long_pct, short_pct, ratio, delta_24h_pct, accounts,
    # imbalanced}]}. Canal LENT (le positionnement bouge en heures, pas en ticks). Lecture
    # seule (§2.1) : le terminal montre la donnée, il n'en déduit aucun signal contrarien.
    long_short_ratio: MetaField = Field(default_factory=MetaField)


FAST_BLOCKS = ("session_identity", "s1_state", "bridge_variables", "sync_state",
               "unified_signal_output", "liquidity_sweep", "macro_risk", "account_state")
# ⚠ Tout bloc ajouté ici DOIT l'être aussi dans `frontend/src/lib/sse.ts` (FAST_BLOCKS /
# SLOW_BLOCKS) : sans son écouteur, l'event part du backend et le frontend le jette EN SILENCE,
# panneau fail-closed sans cause visible (leçon D-051).
SLOW_BLOCKS = ("s2_state", "econ_calendar", "vol_surface", "macro_calendar", "long_short_ratio")
