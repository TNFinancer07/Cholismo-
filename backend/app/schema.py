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


class S1State(BaseModel):
    svs_score: MetaField = Field(default_factory=MetaField)
    order_flow: OrderFlow = Field(default_factory=OrderFlow)
    structure: Structure = Field(default_factory=Structure)
    chop: MetaField = Field(default_factory=MetaField)
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


# --- Full schema (conceptual object; transported as partial per-block SSE events) ---

class ContextSchema(BaseModel):
    session_identity: SessionIdentity = Field(default_factory=SessionIdentity)
    s1_state: S1State = Field(default_factory=S1State)
    s2_state: S2State = Field(default_factory=S2State)
    bridge_variables: BridgeVariables = Field(default_factory=BridgeVariables)
    sync_state: SyncState = Field(default_factory=SyncState)
    unified_signal_output: UnifiedSignalOutput = Field(default_factory=UnifiedSignalOutput)


FAST_BLOCKS = ("session_identity", "s1_state", "bridge_variables", "sync_state", "unified_signal_output")
SLOW_BLOCKS = ("s2_state",)
