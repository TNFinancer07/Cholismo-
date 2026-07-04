/** Câblage SSE — deux EventSource, un par cadence (CLAUDE §6). Les events sont partiels
 *  par bloc : event name = nom du bloc. `decision_log_dirty` déclenche un refresh des
 *  projections Zone D (le log lui-même reste event-sourced côté serveur). */
import { api, API_BASE } from './api'
import { useTerminal } from '@/store/terminal'
import type { BlotterRow, Calibration, OrchestratorPayload } from '@/types/schema'

const FAST_BLOCKS = ['session_identity', 's1_state', 'bridge_variables', 'sync_state',
  'unified_signal_output', 'extras']
const SLOW_BLOCKS = ['s2_state']

async function refreshProjections() {
  const store = useTerminal.getState()
  try {
    const [decisions, calibration, orchestrator] = await Promise.all([
      api.decisions(), api.calibration(), api.orchestrator(),
    ])
    store.set({
      decisions: decisions.decisions as unknown as BlotterRow[],
      calibration: calibration as Calibration,
      orchestrator: orchestrator as OrchestratorPayload,
    })
  } catch {
    /* le badge de canal muet couvre déjà l'indisponibilité */
  }
}

export async function refreshSelfcheck() {
  const store = useTerminal.getState()
  try {
    const res = await api.getSelfcheck(store.operator)
    store.set({ selfcheckPresent: res.present })
  } catch { /* idem */ }
}

export async function refreshScenario() {
  const store = useTerminal.getState()
  try {
    const [scenario, sources] = await Promise.all([api.scenario(), api.sources()])
    store.set({ scenario: scenario as never, sources })
  } catch { /* idem */ }
}

export function connectSSE(): () => void {
  const store = useTerminal.getState()

  const fast = new EventSource(`${API_BASE}/sse/fast`)
  for (const block of FAST_BLOCKS) {
    fast.addEventListener(block, (e: MessageEvent) => {
      useTerminal.getState().applyBlock(block, JSON.parse(e.data))
      useTerminal.getState().markFast()
    })
  }
  fast.addEventListener('decision_log_dirty', () => { void refreshProjections() })

  const slow = new EventSource(`${API_BASE}/sse/slow`)
  for (const block of SLOW_BLOCKS) {
    slow.addEventListener(block, (e: MessageEvent) => {
      useTerminal.getState().applyBlock(block, JSON.parse(e.data))
      useTerminal.getState().markSlow()
    })
  }

  const ticker = window.setInterval(() => useTerminal.getState().tick(), 1000)
  const slowPoll = window.setInterval(() => { void refreshProjections() }, 10_000)

  void refreshProjections()
  void refreshSelfcheck()
  void refreshScenario()
  void store

  return () => {
    fast.close()
    slow.close()
    window.clearInterval(ticker)
    window.clearInterval(slowPoll)
  }
}
