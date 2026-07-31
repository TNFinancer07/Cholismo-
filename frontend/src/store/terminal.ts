/** Store frontend UNIQUE (TASKS 1.2) — les vues sont des projections de ce store,
 *  lui-même projection du ContextSchema poussé par SSE. Rien hors-schéma n'y vit,
 *  hormis l'état d'instance (opérateur, focus clavier, vue) et les projections Zone D. */
import { create } from 'zustand'
import type {
  AccountStateBlock, BlotterRow, BridgeVariables, Calibration, ContextSchema, EconCalendar, Extras,
  LiquiditySweep, LongShortValue, MacroCalendarValue, MacroRiskValue, MetaField, OperationalMode, Operator,
  OrchestratorPayload, S1State, S2State, SessionIdentity, SyncState, UnifiedSignalOutput, VolSurface,
  YieldCurveValue,
} from '@/types/schema'

export type ZoneKey = 'A' | 'B' | 'C' | 'D'
export type ViewKey = 'TERMINAL' | 'RECAP' | 'LIVE' | 'JOURNAL' | 'ORCHESTRATEUR'
  | 'PROMPTS' | 'PARAMS' | 'JBORD' | 'PNL' | 'ROBUST'

export interface ScenarioInfo {
  current: {
    name: string
    label: string
    base: Record<string, number>
    simulated_streak: number
    force_session: string | null
  }
  available: { name: string; label: string }[]
  sliders: string[]
}

interface TerminalStore {
  // blocs du schéma (mis à jour par événements SSE partiels)
  session_identity: SessionIdentity | null
  s1_state: S1State | null
  s2_state: S2State | null
  bridge_variables: BridgeVariables | null
  sync_state: SyncState | null
  unified_signal_output: UnifiedSignalOutput | null
  econ_calendar: EconCalendar | null
  liquidity_sweep: LiquiditySweep | null
  vol_surface: VolSurface | null
  macro_calendar: MetaField<MacroCalendarValue> | null
  macro_risk: MetaField<MacroRiskValue> | null
  account_state: AccountStateBlock | null
  long_short_ratio: MetaField<LongShortValue> | null
  yield_curve: MetaField<YieldCurveValue> | null
  extras: Extras | null

  // santé des canaux (fail-closed UI : canal muet => BLOQUÉ affiché)
  lastFastEventAt: number
  lastSlowEventAt: number
  clockOffset: number // server_ts - client now (secondes)

  // horloge de rendu (les âges STALE se re-rendent chaque seconde)
  nowTick: number

  // projections Zone D & panneaux REST
  decisions: BlotterRow[]
  calibration: Calibration | null
  orchestrator: OrchestratorPayload | null
  scenario: ScenarioInfo | null
  sources: Record<string, { up: boolean; fields: string[] }> | null
  selfcheckPresent: boolean

  // historiques de rendu (sparklines) — buffer client des valeurs du
  // schéma reçues par SSE ; traçable au schéma, rien d'inventé, jamais persisté
  history: Record<string, number[]>

  // état d'instance
  operator: Operator
  focusZone: ZoneKey | null
  view: ViewKey
  selfcheckOpen: boolean
  commandOpen: boolean
  lastError: string | null

  // actions
  applyBlock: (name: string, payload: unknown) => void
  markFast: (serverTs?: number) => void
  markSlow: () => void
  tick: () => void
  set: (partial: Partial<TerminalStore>) => void
}

export const useTerminal = create<TerminalStore>((set) => ({
  session_identity: null,
  s1_state: null,
  s2_state: null,
  bridge_variables: null,
  econ_calendar: null,
  liquidity_sweep: null,
  vol_surface: null,
  macro_calendar: null,
  macro_risk: null,
  account_state: null,
  long_short_ratio: null,
  yield_curve: null,
  sync_state: null,
  unified_signal_output: null,
  extras: null,

  lastFastEventAt: 0,
  lastSlowEventAt: 0,
  clockOffset: 0,
  nowTick: Date.now() / 1000,

  decisions: [],
  calibration: null,
  orchestrator: null,
  scenario: null,
  sources: null,
  selfcheckPresent: false,

  history: {},

  operator: (new URLSearchParams(window.location.search).get('operator')?.toUpperCase() === 'YOUSSEF'
    ? 'YOUSSEF' : (import.meta.env.VITE_OPERATOR === 'YOUSSEF' ? 'YOUSSEF' : 'SONY')) as Operator,
  focusZone: null,
  view: 'TERMINAL',
  selfcheckOpen: false,
  commandOpen: false,
  lastError: null,

  applyBlock: (name, payload) =>
    set((state) => {
      const MAX_POINTS = 150
      const push = (history: Record<string, number[]>, key: string, v: unknown) => {
        if (typeof v !== 'number' || Number.isNaN(v)) return history
        const arr = [...(history[key] ?? []), v].slice(-MAX_POINTS)
        return { ...history, [key]: arr }
      }
      switch (name) {
        case 'session_identity': {
          const si = payload as SessionIdentity
          return { session_identity: si, clockOffset: si.server_ts - Date.now() / 1000 }
        }
        case 's1_state': {
          const s1 = payload as S1State
          let history = push(state.history, 'cvd', s1.order_flow.cvd.value)
          history = push(history, 'svs', s1.svs_score.value)
          return { s1_state: s1, history }
        }
        case 's2_state': {
          const s2 = payload as S2State
          let history = push(state.history, 'vix', s2.cascade.vix.value)
          history = push(history, 'eurusd', s2.cascade.eurusd.value)
          return { s2_state: s2, history }
        }
        case 'bridge_variables': {
          const bridge = payload as BridgeVariables
          return { bridge_variables: bridge, history: push(state.history, 'gex', bridge.gex.value) }
        }
        case 'sync_state': return { sync_state: payload as SyncState }
        case 'econ_calendar': return { econ_calendar: payload as EconCalendar }
        case 'liquidity_sweep': return { liquidity_sweep: payload as LiquiditySweep }
        case 'vol_surface': return { vol_surface: payload as VolSurface }
        case 'macro_calendar': return { macro_calendar: payload as MetaField<MacroCalendarValue> }
        case 'macro_risk': return { macro_risk: payload as MetaField<MacroRiskValue> }
        case 'account_state': return { account_state: payload as AccountStateBlock }
        case 'long_short_ratio':
          return { long_short_ratio: payload as MetaField<LongShortValue> }
        case 'yield_curve': return { yield_curve: payload as MetaField<YieldCurveValue> }
        case 'unified_signal_output': {
          const signal = payload as UnifiedSignalOutput
          return { unified_signal_output: signal, history: push(state.history, 'score', signal.score) }
        }
        case 'extras': return { extras: payload as Extras }
        default: return state
      }
    }),

  markFast: () => set({ lastFastEventAt: Date.now() / 1000 }),
  markSlow: () => set({ lastSlowEventAt: Date.now() / 1000 }),
  tick: () => set({ nowTick: Date.now() / 1000 }),
  set: (partial) => set(partial),
}))

// Affordance de test DEV-only (élaguée en prod par Vite : `import.meta.env.DEV` = false) :
// injecte un `cvd_by_level` fabriqué dans le s1_state courant sans toucher aux autres champs,
// pour exercer les branches de rendu difficiles à provoquer en live (maxAbs=0, capped) — /devil.
if (import.meta.env.DEV && typeof window !== 'undefined') {
  ;(window as unknown as { __setCvd?: (cvd: unknown) => void }).__setCvd = (cvd) => {
    const s = useTerminal.getState()
    if (s.s1_state) s.set({ s1_state: { ...s.s1_state, cvd_by_level: cvd as never } })
  }
  // /devil D-036 : force un `liquidity_heatmap` pathologique (vide, croisé, NaN, massif) pour
  // vérifier que le rendu Canvas ne crashe jamais.
  ;(window as unknown as { __setHeatmap?: (hm: unknown) => void }).__setHeatmap = (hm) => {
    const s = useTerminal.getState()
    if (s.s1_state) s.set({ s1_state: { ...s.s1_state, liquidity_heatmap: hm as never } })
  }
  // /devil D-037 : force un `footprint` pathologique (prix NaN, volume gigantesque, niveau
  // unique, plage aberrante, tick 0/NaN) pour vérifier que le Canvas ne crashe jamais.
  ;(window as unknown as { __setFootprint?: (fp: unknown) => void }).__setFootprint = (fp) => {
    const s = useTerminal.getState()
    if (s.s1_state) s.set({ s1_state: { ...s.s1_state, footprint: fp as never } })
  }
  // /devil D-038 : force un `cvd_stratified` pathologique (série vide, valeurs non-finies,
  // divergence, point unique) pour vérifier que le rendu Canvas ne crashe jamais.
  ;(window as unknown as { __setCvdStrat?: (cs: unknown) => void }).__setCvdStrat = (cvd) => {
    const s = useTerminal.getState()
    if (s.s1_state) s.set({ s1_state: { ...s.s1_state, cvd_stratified: cvd as never } })
  }
  // /devil D-041 : force un `volume_profile` pathologique (niveaux non-finis, VA vide, prix
  // aberrant, previous null) pour vérifier que le rendu Canvas ne crashe jamais.
  ;(window as unknown as { __setVolProfile?: (vp: unknown) => void }).__setVolProfile = (vp) => {
    const s = useTerminal.getState()
    if (s.s1_state) s.set({ s1_state: { ...s.s1_state, volume_profile: vp as never } })
  }
  // /devil D-039 : force un `vol_surface` pathologique (chaîne vide, IV/greeks non-finis,
  // moneyness null, term structure inversée) pour vérifier que le rendu Canvas/grille ne crashe jamais.
  ;(window as unknown as { __setVolSurface?: (vs: unknown) => void }).__setVolSurface = (vs) => {
    const s = useTerminal.getState()
    s.set({ vol_surface: vs as never })
  }
  // D-051 : force un `account_state` (marge critique, buffer mort, déconnecté) — ces états sont
  // difficiles à provoquer en démo (le mock est toujours un compte sain à l'ouverture).
  ;(window as unknown as { __setAccount?: (a: unknown) => void }).__setAccount = (a) => {
    useTerminal.getState().set({ account_state: a as never })
  }
  // /devil D-053 : force `long_short_ratio` / `yield_curve` — les positions extrêmes (100/0,
  // 98/2) et les courbes à une patte sont rares en démo, et c'est là que la GÉOMÉTRIE d'une
  // jauge peut mentir (une bande de 0 % qui reste visible n'est visible qu'en vrai navigateur).
  ;(window as unknown as { __setLongShort?: (v: unknown) => void }).__setLongShort = (v) => {
    useTerminal.getState().set({ long_short_ratio: v as never })
  }
  ;(window as unknown as { __setYields?: (v: unknown) => void }).__setYields = (v) => {
    useTerminal.getState().set({ yield_curve: v as never })
  }
  // D-045 : lit la vue active — permet aux essais de PROUVER qu'aucune touche ne fuit vers les
  // raccourcis globaux pendant qu'une alerte TradeManifest est affichée (V ne change pas la vue).
  ;(window as unknown as { __terminalView?: () => string }).__terminalView = () =>
    useTerminal.getState().view
  // /devil D-040 : force `macro_calendar` / `macro_risk` pathologiques (events non-finis, régime
  // inconnu, event null, seconds_until NaN) pour vérifier que le panneau/badge ne crashe jamais.
  ;(window as unknown as { __setMacro?: (c: unknown, r: unknown) => void }).__setMacro = (cal, risk) => {
    const s = useTerminal.getState()
    s.set({ macro_calendar: cal as never, macro_risk: risk as never })
  }
}

/** Temps serveur estimé (pour countdown C3 et âges de donnée). */
export function serverNow(state: Pick<TerminalStore, 'nowTick' | 'clockOffset'>): number {
  return state.nowTick + state.clockOffset
}

/** Fail-closed côté UI : si le canal rapide est muet > 5 s, l'affichage Phase 0 retombe
 *  sur BLOQUÉ (moteur muet) — l'UI ne peut jamais « inventer » un OUVERT (CLAUDE §2.2). */
export function effectivePhase0(state: {
  session_identity: SessionIdentity | null
  lastFastEventAt: number
  nowTick: number
}): { phase0: 'OPEN' | 'BLOCKED'; engineMute: boolean } {
  const mute = state.lastFastEventAt === 0 || state.nowTick - state.lastFastEventAt > 5
  if (mute || !state.session_identity) return { phase0: 'BLOCKED', engineMute: true }
  return { phase0: state.session_identity.phase0, engineMute: false }
}

export const MODES: OperationalMode[] = ['PRE_SESSION', 'LIVE', 'POST_SESSION']
