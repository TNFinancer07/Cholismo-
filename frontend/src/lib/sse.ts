/** Câblage SSE — deux EventSource, un par cadence (CLAUDE §6). Les events sont partiels
 *  par bloc : event name = nom du bloc. `decision_log_dirty` déclenche un refresh des
 *  projections Zone D (le log lui-même reste event-sourced côté serveur). */
import { api, API_BASE } from './api'
import { useTerminal } from '@/store/terminal'
import type { BlotterRow, Calibration, OrchestratorPayload } from '@/types/schema'

const FAST_BLOCKS = ['session_identity', 's1_state', 'bridge_variables', 'sync_state',
  'unified_signal_output', 'liquidity_sweep', 'extras']
const SLOW_BLOCKS = ['s2_state', 'econ_calendar']

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

const RECONNECT_DELAY_MS = 4_000

/** EventSource auto-résurrecté — DEUX pannes distinctes, trouvées par /devil sur EC :
 *  1. réponse non-200 (proxy Vite, backend mort) → la spec HTML ferme DÉFINITIVEMENT,
 *     jamais de retry natif → `onerror` reprend la main et recrée à délai fixe ;
 *  2. panne SILENCIEUSE : le proxy laisse la connexion PENDRE quand l'upstream meurt
 *     en cours de stream — aucun `onerror`, le navigateur se croit connecté à jamais
 *     (et les pings sse-starlette sont des commentaires, invisibles côté JS). D'où
 *     `recycle()`, appelé par un watchdog de vivacité (RUNTIME_LOOPS) quand le canal
 *     est resté muet au-delà de sa cadence : on ferme la source « connectée » et on
 *     rouvre ; si le backend est encore mort, le non-200 rapide bascule sur la panne 1.
 *  Entre-temps, les bannières « flux muet » des panneaux disent la vérité (§3). */
function resilientSource(url: string, wire: (es: EventSource) => void):
  { close: () => void; recycle: () => void } {
  let es: EventSource | null = null
  let timer: number | null = null
  let closed = false
  const open = () => {
    if (closed) return
    es = new EventSource(url)
    wire(es)
    es.onerror = () => {
      if (closed || !es) return
      es.close()                 // l'ES natif ne ré-essaiera pas sur non-200 : on reprend la main
      es = null
      if (timer === null) {
        timer = window.setTimeout(() => { timer = null; open() }, RECONNECT_DELAY_MS)
      }
    }
  }
  open()
  return {
    recycle: () => {
      if (closed || es === null) return   // boucle de retry déjà aux commandes
      es.close()
      es = null
      open()
    },
    close: () => {
      closed = true
      es?.close()
      if (timer !== null) window.clearTimeout(timer)
    },
  }
}

// Seuils de silence AVANT recyclage (au-delà des cadences §6 : fast sub-seconde,
// slow 15 s). Les badges « flux muet » (5 s / 40 s) alertent AVANT que le watchdog agisse.
const FAST_SILENT_S = 10
const SLOW_SILENT_S = 45

export function connectSSE(): () => void {
  const fast = resilientSource(`${API_BASE}/sse/fast`, (es) => {
    for (const block of FAST_BLOCKS) {
      es.addEventListener(block, (e: MessageEvent) => {
        useTerminal.getState().applyBlock(block, JSON.parse(e.data))
        useTerminal.getState().markFast()
      })
    }
    es.addEventListener('decision_log_dirty', () => { void refreshProjections() })
  })

  const slow = resilientSource(`${API_BASE}/sse/slow`, (es) => {
    for (const block of SLOW_BLOCKS) {
      es.addEventListener(block, (e: MessageEvent) => {
        useTerminal.getState().applyBlock(block, JSON.parse(e.data))
        useTerminal.getState().markSlow()
      })
    }
  })

  const ticker = window.setInterval(() => useTerminal.getState().tick(), 1000)
  const slowPoll = window.setInterval(() => { void refreshProjections() }, 10_000)
  // Watchdog de vivacité : un canal qui a DÉJÀ produit puis se tait au-delà du seuil est
  // une connexion pendue (proxy) → recycler. Jamais-connecté (== 0) reste à la boucle
  // d'erreur de resilientSource.
  const watchdog = window.setInterval(() => {
    const s = useTerminal.getState()
    const now = Date.now() / 1000
    if (s.lastFastEventAt > 0 && now - s.lastFastEventAt > FAST_SILENT_S) fast.recycle()
    if (s.lastSlowEventAt > 0 && now - s.lastSlowEventAt > SLOW_SILENT_S) slow.recycle()
  }, 5_000)

  void refreshProjections()
  void refreshSelfcheck()
  void refreshScenario()

  return () => {
    fast.close()
    slow.close()
    window.clearInterval(ticker)
    window.clearInterval(slowPoll)
    window.clearInterval(watchdog)
  }
}
