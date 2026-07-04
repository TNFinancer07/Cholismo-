/** Store frontend UNIQUE (TASKS 1.2) — les vues sont des projections de ce store,
 *  lui-même projection du ContextSchema poussé par SSE. Rien hors-schéma n'y vit,
 *  hormis l'état d'instance (opérateur, focus clavier, vue) et les projections Zone D. */
import { create } from 'zustand'
import type {
  BlotterRow, BridgeVariables, Calibration, ContextSchema, Extras, OperationalMode,
  Operator, OrchestratorPayload, S1State, S2State, SessionIdentity, SyncState,
  UnifiedSignalOutput,
} from '@/types/schema'

export type ZoneKey = 'A' | 'B' | 'C' | 'D'
export type ViewKey = 'TERMINAL' | 'ORCHESTRATEUR' | 'PROMPTS'

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

  // état d'instance
  operator: Operator
  focusZone: ZoneKey | null
  view: ViewKey
  selfcheckOpen: boolean
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

  operator: (new URLSearchParams(window.location.search).get('operator')?.toUpperCase() === 'YOUSSEF'
    ? 'YOUSSEF' : (import.meta.env.VITE_OPERATOR === 'YOUSSEF' ? 'YOUSSEF' : 'SONY')) as Operator,
  focusZone: null,
  view: 'TERMINAL',
  selfcheckOpen: false,
  lastError: null,

  applyBlock: (name, payload) =>
    set((state) => {
      switch (name) {
        case 'session_identity': {
          const si = payload as SessionIdentity
          return { session_identity: si, clockOffset: si.server_ts - Date.now() / 1000 }
        }
        case 's1_state': return { s1_state: payload as S1State }
        case 's2_state': return { s2_state: payload as S2State }
        case 'bridge_variables': return { bridge_variables: payload as BridgeVariables }
        case 'sync_state': return { sync_state: payload as SyncState }
        case 'unified_signal_output': return { unified_signal_output: payload as UnifiedSignalOutput }
        case 'extras': return { extras: payload as Extras }
        default: return state
      }
    }),

  markFast: () => set({ lastFastEventAt: Date.now() / 1000 }),
  markSlow: () => set({ lastSlowEventAt: Date.now() / 1000 }),
  tick: () => set({ nowTick: Date.now() / 1000 }),
  set: (partial) => set(partial),
}))

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
