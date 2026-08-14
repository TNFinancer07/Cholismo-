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

// Heatmap de liquidité (D-036, DELTA) — le backend émet UNE colonne par tick, le frontend
// accumule la fenêtre glissante et calcule la normalisation couleur.
export interface HeatmapColumn {
  ts: number
  bids: [number, number][]
  asks: [number, number][]
}
export interface HeatmapValue {
  column: HeatmapColumn | null   // colonne courante (null si carnet non FRESH / vide)
}

/** Tape / Time & Sales (D-026) — prints observés, plus récent en tête. */
export interface TapePrint {
  ts: number
  price: number
  size: number
  side: 'BUY' | 'SELL'
  seq: number
}

/** CVD par niveau (D-029) — delta agresseur net accumulé par prix, reset événementiel. */
export interface CvdLevel {
  price: number
  delta: number   // buy − sell
  buy: number
  sell: number
}

export interface CvdState {
  levels: CvdLevel[]          // bornés, triés par prix
  total_delta: number
  since_ts: number | null
  last_reset_ts: number | null
  reset_reason: string
  stale: boolean
  capped: boolean
}

// Footprint + imbalances (D-037) — agrégation Bid×Ask par niveau/bougie, rendue en Canvas.
export interface FootprintLevel {
  price: number
  bid_vol: number
  ask_vol: number
  delta: number                   // ask_vol − bid_vol : agresseur net du niveau (D-042)
  imbalance: 'ASK' | 'BID' | null
  // Liquidité AU REPOS du carnet L2 (D-042) — présente UNIQUEMENT sur la bougie en formation et
  // seulement si `book_state === 'LIVE'` : absente = pas de donnée, jamais « zéro mur ».
  bid_liq?: number
  ask_liq?: number
}
/** État du carnet L2 pour cette bougie : `LIVE` = instantané courant appliqué à la bougie en
 *  formation ; `ABSENT` = bougie passée, ou carnet gelé/corrompu (fail-closed §3). */
export type BookState = 'LIVE' | 'ABSENT'
export interface FootprintCandle {
  start_ts: number; end_ts: number
  open: number; high: number; low: number; close: number
  poc: number | null
  total_volume: number
  delta: number                   // agresseur net de la bougie = Σ delta des niveaux (D-042)
  n_prints: number
  book_state: BookState
  levels: FootprintLevel[]        // trié prix décroissant
}
export interface FootprintValue {
  candles: FootprintCandle[]
  tick: number
  ratio: number
  candle_seconds: number
  ticks_per_candle: number        // > 0 = bougies TICK-BASED ; 0 = bucket temporel (D-042)
}

// CVD granulaire stratifié par taille (D-038)
export interface CvdStratPoint {
  ts: number
  price: number
  retail: number         // CVD cumulé strate retail (size < seuil)
  institutional: number  // CVD cumulé strate institutionnelle (size >= seuil)
  total: number
}
export interface CvdDivergence {
  kind: 'BULLISH' | 'BEARISH'
  price_change: number
  inst_change: number
  bars: number
}
export interface CvdStratifiedValue {
  size_threshold: number
  series: CvdStratPoint[]
  divergence: CvdDivergence | null
}

// Volume Profile dynamique (D-041) — buy/sell présents seulement si la source les fournit (§3)
export interface VolumeLevel { price: number; volume: number; buy?: number; sell?: number }
export interface VolumeProfileValue {
  tick: number
  va_pct: number
  total_volume: number
  poc: number | null
  vah: number | null
  val: number | null
  levels: VolumeLevel[]
  lvn: number[]
  previous: { poc: number | null; vah: number | null; val: number | null } | null
}

export interface S1State {
  svs_score: MetaField<number>
  order_flow: OrderFlow
  structure: Structure
  cvd_by_level: CvdState
  chop: MetaField<number>
  order_book: MetaField<OrderBookValue>
  liquidity_heatmap: MetaField<HeatmapValue>
  tape: MetaField<TapePrint[]>
  footprint: MetaField<FootprintValue>
  cvd_stratified: MetaField<CvdStratifiedValue>
  volume_profile: MetaField<VolumeProfileValue>
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

// --- vol_surface → OMON (chaîne d'options) + VTS (term structure) [lent] (D-039) ---

export type Moneyness = 'ITM' | 'ATM' | 'OTM' | null
/** Provenance des Grecques d'une patte (D-044) — jamais implicite : un calcul ne doit pas passer
 *  pour une donnée de marché, ni l'inverse (§3).
 *  `INVERTED` : IV inversée depuis le PRIX de marché (Newton-Raphson), toutes les Grecques calculées ;
 *  `SOURCE_IV` : Grecques calculées à l'IV fournie par la source (pas de prix exploitable) ;
 *  `RELAY` : ni prix ni IV utilisables → valeurs source relayées, le reste à `null`. */
export type GreeksSource = 'INVERTED' | 'SOURCE_IV' | 'RELAY'
export interface OptionLeg {
  iv: number | null
  delta: number | null
  gamma: number | null
  theta: number | null            // par AN (afficher /365 pour un « par jour »)
  vega: number | null             // pour σ + 1.0 (afficher /100 pour « par point de vol »)
  vanna: number | null
  charm: number | null
  moneyness: Moneyness
  greeks_source: GreeksSource
}
export interface OptionRow { strike: number; call: OptionLeg; put: OptionLeg }
export interface OptionExpiry {
  expiry: string | null
  dte: number | null
  atm_strike: number | null
  rows: OptionRow[]
}
export interface OptionsChainValue {
  underlying: number | null
  atm_strike: number | null
  expirations: OptionExpiry[]
}
export type TermState = 'CONTANGO' | 'BACKWARDATION' | 'FLAT' | null
export interface TermPoint { tenor: string | null; days: number; value: number }
export interface TermStructureValue {
  points: TermPoint[]
  state: TermState
  front_back_spread: number | null
}
export interface VolSurface {
  options_chain: MetaField<OptionsChainValue>
  term_structure: MetaField<TermStructureValue>
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

// --- econ_calendar → panneau EC (SYSTÉMIQUE, macro/géo) [lent] ---

/** Événement macro/géo programmé. `ts` = heure prévue CONNUE → compte à rebours honnête
 *  (dérivation client, contraste B2 §8.2). `tier` = impact liquidité (1 fort / 2 modéré /
 *  3 faible). */
export interface EconEvent {
  ts: number
  name: string
  tier: 1 | 2 | 3
  region: string
}

export interface EconCalendar {
  events: MetaField<EconEvent[]>
}

// --- macro_calendar → panneau MCAL + macro_risk → badge Zone 0 (D-040) ---

export type Impact = 'HIGH' | 'MED' | 'LOW'
export interface MacroRelease {
  ts: number
  name: string
  country: string | null
  currency: string | null
  impact: Impact
  consensus: number | null
  previous: number | null
  actual: number | null
  surprise: number | null
}
export interface MacroCalendarValue { events: MacroRelease[] }
export type MacroRiskRegime = 'NORMAL' | 'WARNING' | 'EXECUTION_PAUSED'
export interface MacroRiskEvent { name: string | null; ts: number; impact: Impact | null; country: string | null }
export interface MacroRiskValue {
  regime: MacroRiskRegime
  event: MacroRiskEvent | null
  seconds_until: number | null
  in_window: boolean
}

// --- liquidity_sweep → panneau IA (détecteur LangGraph déterministe, D-028) [rapide] ---

export interface LiquiditySweepAlert {
  ts: number
  kind: string
  direction: 'BID_SWEEP' | 'ASK_SWEEP' | null
  spread_width: number | null
  delta_volume: number | null
  trigger: string          // TAPE_BURST | WIDE_SPREAD | CROSSED_BOOK (combinés par +)
  news_context: string
  reason: string
}

export interface LiquiditySweep {
  assessable: boolean      // data_ok — sinon « impossible à évaluer », fail-closed honnête
  triggered: boolean
  reason: string
  alert: LiquiditySweepAlert | null
  last_compute_ts: number | null
  recent: LiquiditySweepAlert[]
}

// --- long_short_ratio → panneau SENT (positionnement agrégé, D-053) [lent] ---
// ⚠ « LSR » dans ce terminal = Liquidity Sweep Reversal (moteur). Ici c'est le Long/Short Ratio
// d'une venue de positionnement : mnémonique opérateur SENT, jamais LSR (collision de lecture).

export interface LongShortInstrument {
  symbol: string
  long_pct: number
  short_pct: number
  /** long/short. `null` quand plus personne n'est short — jamais « ∞ » ni un nombre géant. */
  ratio: number | null
  delta_24h_pct: number | null
  accounts: number | null
  /** ≥ seuil d'un côté : FAIT observable, aucune lecture contrarienne déduite (§2.1). */
  imbalanced: boolean
}

export interface LongShortValue {
  venue: string
  instruments: LongShortInstrument[]
  /** Lignes écartées par le moteur (somme ≠ 100, doublon, symbole vide) — affiché, pas caché. */
  dropped: number
  extreme_pct: number
}

// --- yield_curve → panneau YLD (courbe des taux & différentiels, D-053) [lent] ---

export interface YieldTenor {
  code: string
  label: string
  value_pct: number
  /** Variation en points de base. `null` = pas de mesure — jamais 0, qui signifie « inchangé ». */
  change_bp: number | null
}

export interface YieldSpread {
  code: string
  label: string
  /** Écart en POINTS DE BASE, signé. Dérivé des ténors : jamais alimenté séparément. */
  value_bp: number
  long: string
  short: string
  /** `null` hors pente : « inversé » n'a pas de sens sur un différentiel inter-pays. */
  inverted: boolean | null
}

export interface YieldCurveValue {
  tenors: YieldTenor[]
  /** Un spread n'existe QUE si ses deux pattes sont présentes (sinon il disparaît, §3). */
  spreads: YieldSpread[]
}

export interface ContextSchema {
  session_identity: SessionIdentity
  s1_state: S1State
  s2_state: S2State
  bridge_variables: BridgeVariables
  sync_state: SyncState
  unified_signal_output: UnifiedSignalOutput
  econ_calendar: EconCalendar
  liquidity_sweep: LiquiditySweep
  vol_surface: VolSurface
  macro_calendar: MetaField<MacroCalendarValue>
  macro_risk: MetaField<MacroRiskValue>
  long_short_ratio: MetaField<LongShortValue>
  yield_curve: MetaField<YieldCurveValue>
}

// --- hors-schéma : extras opérationnels poussés sur le canal rapide ---

// --- account_state → ZONE C HUD (« distance vers la mort », D-051) [fast] ---

export interface NextTicket {
  instrument: string
  stop_ticks: number
  /** N'existe QUE sur APPROVED — jamais un 0 déguisé en taille (§3). */
  contracts: number | null
  risk_allowed: number | null
  status: string
}

export interface AccountStateBlock {
  /** APPROVED | INSUFFICIENT_BUFFER | INVALID_INPUT | SIZE_SANITY_CAP | DISCONNECTED */
  status: string
  is_stale: boolean
  current_equity: number | null
  day_start_equity: number | null
  drawdown_floor: number | null
  daily_loss_limit: number | null
  /** Distance vers la mort : min(equity − floor, equity − (day_start − DLL)). */
  buffer: number | null
  /** Buffer à l'OUVERTURE du jour — dénominateur de la jauge (D-051). */
  buffer_initial: number | null
  day_pnl: number | null
  next_ticket: NextTicket
}

/** Comparaison proxy ↔ mesure maison des gates d'order flow LSR (D-056 / D-099).
 *  Nommées `OF1`-`OF4` À L'ÉCRAN pour ne pas entrer en collision avec le code de POSITION
 *  `B1` des panneaux React — le backend les nomme encore `b1`-`b4`, d'où le décalage assumé
 *  entre la clé de transport et le libellé affiché.
 *  OF1/OF2 portent un VERDICT (décisionnelles) ; OF3/OF4 sont MESURÉES et explicitement
 *  non gatantes (seuils non calibrés) — la distinction est faite par le backend, l'écran la
 *  garde. Absent = mesure non publiée, JAMAIS un zéro (§3). */
export interface OrderFlowGate {
  source: number | boolean | null
  inhouse: number | boolean | null
  verdict_source: boolean | null
  verdict_inhouse: boolean | null
  agree: boolean | null
  /** OF2 seulement : écart absolu entre les deux mesures. */
  delta?: number | null
}

/** Seuil EFFECTIF d'une gate (D-101) — publié par le backend, jamais écrit en dur ici :
 *  une copie divergerait en silence à la première recalibration.
 *  `op` compte autant que `value` — B2 compare `>=` sur un BID_SWEEP et `<=` sur un ASK_SWEEP.
 *  `applied: false` = seuil de RÉFÉRENCE d'une mesure non gatante (OF3/OF4). */
export interface OrderFlowThreshold {
  value: number
  op: '>=' | '<='
  applied: boolean
}

export interface OrderFlowThresholds {
  instrument: string
  b1: OrderFlowThreshold | null
  /** `null` sans direction de sweep : il n'y a alors pas de seuil à montrer. */
  b2: OrderFlowThreshold | null
  b3: OrderFlowThreshold | null
  b4: OrderFlowThreshold | null
}

export interface OrderFlowShadow {
  /** Ligne lisible en tête — accord, désaccord (et sur quoi), ou non mesurable. */
  resume: string
  source: string
  /** Absents sur la branche d'erreur du backend : l'observation a échoué, rien n'est mesuré. */
  b1?: OrderFlowGate
  b2?: OrderFlowGate
  /** MESURÉES, jamais gatantes dans cette tranche. */
  b3?: number | null
  b4?: number | null
  /** Absents si l'instrument n'est pas calibré — aucun repère à placer, pas un zéro. */
  thresholds?: OrderFlowThresholds | null
  missing?: string[]
}

export interface Extras {
  rms: number | null
  rms_meta?: MetaField<number>
  streak: number
  streak_acked: boolean
  scenario: { name: string; label: string } | null
  /** Porte F0 macro (D-050) : NORMAL | WARNING | HARD_LOCK | SAFETY_UNKNOWN ;
   *  null/absent = couche news non câblée (pas de porte). */
  news_state?: string | null
  orderflow_shadow?: OrderFlowShadow | null
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
