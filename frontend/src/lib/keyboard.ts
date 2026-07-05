/** Navigation clavier first-class (TASKS 3.3, PRD §Navigation) :
 *  A/B/C/D focus zone · G = GO · N = NO-GO · M cycle mode · V cycle vue ·
 *  S self-check · Échap efface le focus. Les raccourcis sont affichés en permanence
 *  dans la barre de touches (façon Bloomberg). */
import { useEffect } from 'react'
import { api } from './api'
import { MODES, useTerminal, type ViewKey } from '@/store/terminal'
import { useWorkspaces } from '@/store/workspace'
import { refreshSelfcheck } from './sse'

const VIEWS: ViewKey[] = ['TERMINAL', 'RECAP', 'LIVE', 'JOURNAL', 'ORCHESTRATEUR',
  'PROMPTS', 'PARAMS']

export function useKeyboardNav() {
  useEffect(() => {
    async function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }
      const store = useTerminal.getState()
      const key = e.key.toUpperCase()

      if (key === 'ESCAPE') {
        store.set({ focusZone: null, selfcheckOpen: false, commandOpen: false })
        return
      }
      // Barre de commande ouverte : tout va à son input (même si le focus n'est pas
      // encore posé) — aucun raccourci global ne doit fuir.
      if (store.commandOpen) return
      if (e.key === '/') {
        e.preventDefault()
        store.set({ commandOpen: !store.commandOpen })
        return
      }
      if (['A', 'B', 'C', 'D'].includes(key) && !e.metaKey && !e.ctrlKey) {
        store.set({ focusZone: key as never })
        return
      }
      if (/^[1-9]$/.test(key) && !e.metaKey && !e.ctrlKey && !e.altKey) {
        // Bascule directe d'espace de travail (lignée Eikon)
        const { workspaces, setActive } = useWorkspaces.getState()
        const target = workspaces[Number(key) - 1]
        if (target) setActive(target.id)
        return
      }
      if (key === 'G' || key === 'N') {
        const pending = store.unified_signal_output?.decision_window.open
        if (!pending) return
        e.preventDefault()
        try {
          await api.postDecision(store.operator, key === 'G' ? 'GO' : 'NO_GO')
          store.set({ lastError: null })
        } catch (err) {
          store.set({ lastError: (err as Error).message })
        }
        return
      }
      if (key === 'M') {
        const current = store.session_identity?.operational_mode ?? 'PRE_SESSION'
        const next = MODES[(MODES.indexOf(current) + 1) % MODES.length]
        try { await api.setMode(next) } catch (err) { store.set({ lastError: (err as Error).message }) }
        return
      }
      if (key === 'V') {
        const next = VIEWS[(VIEWS.indexOf(store.view) + 1) % VIEWS.length]
        store.set({ view: next })
        return
      }
      if (key === 'S') {
        store.set({ selfcheckOpen: !store.selfcheckOpen })
        void refreshSelfcheck()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

export const KEY_HINTS: { key: string; label: string }[] = [
  { key: '/', label: 'commande <GO>' },
  { key: '1-9', label: 'espace' },
  { key: 'A·B·C·D', label: 'focus zone' },
  { key: 'G', label: 'GO' },
  { key: 'N', label: 'NO-GO' },
  { key: 'S', label: 'self-check' },
  { key: 'M', label: 'mode' },
  { key: 'V', label: 'vue' },
  { key: 'ÉCHAP', label: 'annuler focus' },
]
