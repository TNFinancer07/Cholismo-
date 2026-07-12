/** Miroir TypeScript du ContextSchema v1.0 (backend/app/schema.py) — garder synchronisés.
 *  Un panneau = un bloc. Chaque champ feuille porte un MetaField (PRD §0). */

export type Freshness = 'FRESH' | 'STALE' | 'ABSENT'

export interface MetaField<T = unknown> {
  value: T | null
  last_update_ts: number | null
  source: string
  freshness: Freshness
  flags: string[]
}

// --- session_identity → ZONE 0 ---

export type SessionMarker = 'LONDRES_OBS' | 'OVERLAP_NY' | 'HORS_SESSION'
export type OperationalMode = 'PRE_SESSION' | 'LIVE' | 'POST_SESSION'
export type Operator = 'SONY' | 'YOUSSEF'
export type Phase0State = 'OPEN' | 'BLOCKED'
export type MasterState = 'READY' | 'NOT_READY' | 'DEGRADED'

export interface Phase0Blocker {
  rule: string
  label: string
  detail: string
  severity: 'CRIT' | 'WARN'
}

export interface SessionIdentity {
  clock_local: string
  session_marker: SessionMarker
  operational_mode: OperationalMode
  operator: Operator
  phase0: Phase0State
  phase0_blockers: Phase0Blocker[]
  phase0_warnings: Phase0Blocker[]
  phase0_advisory: string
  master_state: MasterState
  server_ts: number
}

// --- s1_state → B1 gauche (Sony, rouge framboise) [rapide] ---

export interface OrderFlow {
  cvd: MetaField<number>
  absorption: MetaField<boolean>
  aggressor_ratio: MetaField<number>
}

export interface Structure {
  vpoc: MetaField<number>
  vah: MetaField<number>
  val: MetaField<number>
  lvn: MetaField<number[]>
}

export interface StrategyGate {
  name: string
  status: 'PASS' | 'FAIL' | 'ABSENT' | 'MANUAL'
  detail: string
}

export interface ExecutionStrategy {
  strategy_id: string
  label: string
  version: string
  window: string
  score_threshold: string
  eligible: boolean
  sizing_pct: number | null
  gates: StrategyGate[]
  reference: string
}

export interface S1Strategies {
  svs: ExecutionStrategy
  mean_reversion: ExecutionStrategy
}

/** DOM ES (D-025) — bids décroissants / asks croissants, [prix, taille]. */
export interface OrderBookValue {
  bids: [number, number][]
  asks: [number, number][]
}

export interface S1State {
  svs_score: MetaField<number>
  order_flow: OrderFlow
  structure: Structure
  chop: MetaField<number>
  order_book: MetaField<OrderBookValue>
  strategies: S1Strategies | null
}

// --- s2_state → B1 droite + ZONE A (Youssef, jaune citron) [lent] ---

export interface Cascade {
  nq_es: MetaField<number>
  vix: MetaField<number>
  zn: MetaField<number>
  dx: MetaField<number>
  eurusd: MetaField<number>
  real_rates: MetaField<number>
}

export interface S2MacroScore {
  value: number | null
  calibrated: boolean
  coherence: number | null
  tilt: number | null
  gate: number | null
}

export interface MacroRegime {
  tier: 'GREEN' | 'YELLOW' | 'ORANGE' | 'RED'
  vix: number | null
  kurtosis: number | null
  carry_mult: number
  fund_mult: number
  score_mult: number
}

export interface BridgewaterQuadrant {
  quadrant: string | null
  g: number | null
  pi: number | null
  r: number | null
  theta: number | null
  confidence: number | null
  transition_risk: string
  weights: Record<string, number>
}

export interface Flux1 {
  d_scores: Record<string, number | null>
  raw_score: number | null
  score_final: number | null
  conviction: number | null
  direction: 'LONG' | 'SHORT' | 'NEUTRE'
  horizons: Record<string, number | null>
}

export interface Arbitrage {
  arb_id: number
  name: string
  source_dim: string
  horizon: string
  threshold: string
  active: boolean | null
  delta: number | null
  direction: string | null
  conviction: number | null
  note: string
}

export interface S2Pipeline {
  regime: MacroRegime
  quadrant: BridgewaterQuadrant
  flux1: Flux1
  arbitrages: Arbitrage[]
}

export interface S2State {
  cascade: Cascade
  bridgewater_matrix: MetaField<number[][]>
  s2_macro_score: S2MacroScore
  pipeline: S2Pipeline | null
}

// --- bridge_variables → B2 [rapide] ---

export interface BridgeVariables {
  gex: MetaField<number>
  gex_last_compute_ts: number | null
  vvix: MetaField<number>
  dxy: MetaField<number>
}

// --- sync_state → B3 [rapide] ---

export type SyncVerdict = 'ALIGNED' | 'DIVERGENT' | 'PARTIAL'

export interface SyncState {
  verdict: SyncVerdict
  detail: string
}

// --- unified_signal_output → B4 (Router, or) [rapide] ---

export type DecisionValue = 'PENDING' | 'GO' | 'NO_GO'

export interface SignalBreakdown {
  structure: number | null
  order_flow: number | null
  macro: number | null
  sentiment: number | null
  quality: number | null
}

export interface DecisionWindow {
  open: boolean
  opened_ts: number | null
  deadline_ts: number | null
  instrument: string | null
}

export interface UnifiedSignalOutput {
  score: number | null
  degraded: boolean
  breakdown: SignalBreakdown
  decision: DecisionValue
  decision_window: DecisionWindow
}

export interface ContextSchema {
  session_identity: SessionIdentity
  s1_state: S1State
  s2_state: S2State
  bridge_variables: BridgeVariables
  sync_state: SyncState
  unified_signal_output: UnifiedSignalOutput
}

// --- hors-schéma : extras opérationnels poussés sur le canal rapide ---

export interface Extras {
  rms: number | null
  rms_meta?: MetaField<number>
  streak: number
  streak_acked: boolean
  scenario: { name: string; label: string } | null
}

// --- Zone D : projection du blotter (event-sourced) ---

export interface BlotterOutcome {
  outcome: 'WIN' | 'LOSS' | 'SCRATCH'
  error_type: 'A' | 'B' | 'C' | null
  r_multiple: number | null
  ts: number
}

export interface BlotterRecon {
  matched: boolean
  fill_source: string
  ts: number
}

export interface BlotterRow {
  id: string
  ts: number
  operator: string
  instrument: string | null
  decision: 'GO' | 'NO_GO'
  signal_score: number | null
  degraded: boolean
  reason: string | null
  cognitive_selfcheck: boolean
  schema_snapshot_ref: string | null
  outcome: BlotterOutcome | null
  recon: BlotterRecon | null
}

export interface Calibration {
  quantitative: {
    n_trades: number
    window: number
    target: number
    progress_pct: number
    sharpe: number | null
    sharpe_displayable: boolean
    valid: boolean
  }
  behavioral: {
    n_decisions: number
    n_go: number
    selfcheck_rate_pct: number | null
    recon_rate_pct: number | null
    timeouts: number
    streak_audit_acked: boolean
    valid: boolean
  }
  sizing_locked: boolean
  sizing_pct: number
  sharpe: { n: number; sharpe: number | null; displayable: boolean; min_trades: number }
  streak: number
}

export interface OrchestratorPayload {
  sources: Record<string, { level: 'VERT' | 'JAUNE' | 'ROUGE'; detail: string }>
  risk_level: 'VERT' | 'JAUNE' | 'ROUGE'
  action: 'NONE' | 'REQUEST_ACK' | 'BLOCK_ENTRY' | 'SUSPEND_TRADING'
  requires_human_ack: boolean
}

// ---------- RECAP — cockpit de session (miroir de GET /recap, D-023) ----------

export interface RecapWindowState {
  state: 'AVANT' | 'OUVERTE' | 'FERMÉE'
  opens_in_s: number | null
  closes_in_s: number | null
}

export interface RecapModule {
  id: string
  label: string
  state: string
  reason: string
  gates?: { name: string; status: string; detail: string }[]
  sizing_pct?: number | null
}

export interface RecapPayload {
  granularity: string
  granularities: string[]
  generated_ts: number
  r_unit_usd: number
  pnl: {
    n_trades: number
    r_total: number
    usd: number
    wins: number
    losses: number
    win_rate_pct: number | null
    expectancy_r: number | null
    drawdown_r: number
    equity_curve: number[]
  }
  risk: {
    max_r: number
    max_drawdown_r_day: number
    consumed_r: number
    remaining_r: number
    consumed_pct: number | null
    avg_loss_r: number | null
    risk_clock_trades_left: number | null
    lockout: { active: boolean; consecutive_losses: number; until_ts: number | null; rule: string }
  }
  weather: { level: 'VERT' | 'JAUNE' | 'ROUGE'; action: string; reasons: string[] }
  windows: { svs: RecapWindowState; mean_reversion: RecapWindowState }
  strategy_split: { strategy_id: string; label: string; accent: string; n_trades: number; r_total: number }[]
  modules: RecapModule[]
  agents: { provider: string; state: string; detail: string; age_s: number | null; latency_ms: number | null }[]
  signal_degraded: boolean
  gex_absent: boolean
}

// ---------- Paramètres 2 étages (miroir de GET /settings, D-023) ----------

export interface SettingScopeValue { value: unknown; tier: 'default' | 'global' | 'override' }

export interface SettingParam {
  key: string
  domain: 'signal' | 'risk' | 'alerts' | 'ai' | 'live'
  label: string
  control: 'number' | 'bool' | 'choice'
  unit: string
  default: unknown
  minimum: number | null
  maximum: number | null
  choices: string[]
  locked: boolean
  authority: string
  reduce_only: boolean
  guard_below: number | null
  scoped: boolean
  scopes: Record<string, SettingScopeValue>
}

export interface SettingsPayload {
  parameters: SettingParam[]
  specific_scopes: string[]
  overrides_count: number
  presets: { name: string; ts: number }[]
}

export interface SettingHistoryEvent {
  seq: number
  ts: number
  action: string
  key: string | null
  scope: string | null
  value: unknown
  operator: string | null
  name: string | null
}

// ---------- Mode Live (miroir de GET /live/context + POST /live/ask, D-023) ----------

export interface LiveReading { level: 'VERT' | 'AMBRE' | 'ROUGE'; title: string; message: string }

export interface LiveContextPayload {
  context: {
    timestamp: number
    session_window: 'svs' | 'mean_reversion' | 'off_window'
    market: { cvd: number | null; chop: number | null }
    macro: { vix: number | null; gex: number | null }
    active_scores: { svs: number | null; unified: number | null; degraded: boolean }
    rms_state: { level: number | null }
    phase0: { blocked: boolean; blockers: string[] }
    absent_fields: string[]
  }
  reading: LiveReading
  suggestions: string[]
  cycle_seconds: number
  cycle_offwindow_seconds: number
}

export interface LiveAnswer {
  answer: string
  glossary: string | null
  advisory: boolean
  engine: string
  ts: number
}
