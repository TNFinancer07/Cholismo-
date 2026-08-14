/** Régression — projection REST TRONQUÉE (bug trouvé pendant D-053).
 *
 *  Repro : un backend qui redémarre répond 200 avec un corps partiel (`{}`). `refreshProjections`
 *  castait ce corps (`as Calibration`, `as unknown as BlotterRow[]`) et le poussait dans le store.
 *  Le cast TypeScript est EFFACÉ à l'exécution : rien ne vérifie. Le store se retrouvait alors à
 *  violer son propre type, et tout consommateur qui fait confiance au type LEVAIT
 *  (`cal.quantitative.progress_pct`, `decisions.length`) — panneau blanc, pas de message.
 *
 *  Règle figée ici : une projection inexploitable est une projection ABSENTE. On ne stocke pas de
 *  forme fausse, et on n'écrase pas non plus une donnée saine par du vide (§3 — jamais de valeur
 *  inventée, jamais de perte silencieuse).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useTerminal } from '@/store/terminal'
import type { BlotterRow, Calibration, OrchestratorPayload } from '@/types/schema'

const api = { decisions: vi.fn(), calibration: vi.fn(), orchestrator: vi.fn() }
vi.mock('@/lib/api', () => ({
  api: {
    decisions: (...a: unknown[]) => api.decisions(...a),
    calibration: (...a: unknown[]) => api.calibration(...a),
    orchestrator: (...a: unknown[]) => api.orchestrator(...a),
  },
  API_BASE: '',
}))

const SANE_CAL = {
  quantitative: { n_trades: 3, window: 60, target: 50, progress_pct: 5, sharpe: null,
                  sharpe_displayable: false, valid: false },
  behavioral: { n_decisions: 4, n_go: 1, selfcheck_rate_pct: 100, recon_rate_pct: 50,
                timeouts: 0, valid: false },
  sharpe: { min_trades: 20 }, sizing_locked: true, sizing_pct: 50,
} as unknown as Calibration
const SANE_ROWS = [{ id: 'e1' }] as unknown as BlotterRow[]
const SANE_ORCH = { sources: {} } as unknown as OrchestratorPayload

async function refresh() {
  const mod = await import('./sse')
  await (mod as unknown as { refreshProjectionsForTest: () => Promise<void> })
    .refreshProjectionsForTest()
}

beforeEach(() => {
  vi.clearAllMocks()
  useTerminal.getState().set({ calibration: null, decisions: [], orchestrator: null,
                              projectionsBroken: false })
})

describe('projection tronquée', () => {
  it('ne pousse PAS une calibration sans ses sous-objets dans le store', async () => {
    api.decisions.mockResolvedValue({ decisions: [] })
    api.calibration.mockResolvedValue({})            // 200 OK, corps partiel
    api.orchestrator.mockResolvedValue(SANE_ORCH)
    await refresh()
    expect(useTerminal.getState().calibration).toBeNull()
    expect(useTerminal.getState().projectionsBroken).toBe(true)   // la panne est SIGNALÉE
  })

  it('ne pousse PAS un `decisions` non-tableau dans le store', async () => {
    api.decisions.mockResolvedValue({})              // pas de clé `decisions`
    api.calibration.mockResolvedValue(SANE_CAL)
    api.orchestrator.mockResolvedValue(SANE_ORCH)
    await refresh()
    expect(Array.isArray(useTerminal.getState().decisions)).toBe(true)
  })

  it('n\'ÉCRASE pas une projection saine par une réponse cassée', async () => {
    api.decisions.mockResolvedValue({ decisions: SANE_ROWS })
    api.calibration.mockResolvedValue(SANE_CAL)
    api.orchestrator.mockResolvedValue(SANE_ORCH)
    await refresh()
    expect(useTerminal.getState().calibration).not.toBeNull()

    api.calibration.mockResolvedValue({ quantitative: null })   // le backend repart
    await refresh()
    // Perdre une donnée saine à cause d'une réponse cassée serait une régression d'affichage
    // (jauges qui clignotent vers « chargement… ») : on conserve la dernière projection valide.
    expect(useTerminal.getState().calibration).toEqual(SANE_CAL)
    expect(useTerminal.getState().decisions).toEqual(SANE_ROWS)
  })

  it('accepte une projection COMPLÈTE (le garde ne bloque pas le cas nominal)', async () => {
    api.decisions.mockResolvedValue({ decisions: SANE_ROWS })
    api.calibration.mockResolvedValue(SANE_CAL)
    api.orchestrator.mockResolvedValue(SANE_ORCH)
    await refresh()
    const s = useTerminal.getState()
    expect(s.calibration).toEqual(SANE_CAL)
    expect(s.decisions).toEqual(SANE_ROWS)
    expect(s.orchestrator).toEqual(SANE_ORCH)
    expect(s.projectionsBroken).toBe(false)      // le drapeau retombe quand tout revient
  })

  it('survit à un corps qui n\'est même pas un objet', async () => {
    api.decisions.mockResolvedValue('cassé')
    api.calibration.mockResolvedValue(42)
    api.orchestrator.mockResolvedValue(null)
    await expect(refresh()).resolves.not.toThrow()
    expect(useTerminal.getState().calibration).toBeNull()
  })
})

describe('scénario tronqué (même défaut, autre chemin)', () => {
  it('rejette une forme sans `available` ou sans `current`', async () => {
    const { asScenario } = await import('./projections')
    for (const bad of [{}, { current: {} }, { available: [] }, { current: null, available: [] },
                       { current: {}, available: 'x' }, null, 42, []]) {
      expect(asScenario(bad)).toBeNull()
    }
    expect(asScenario({ current: { name: 'calme' }, available: [] })).not.toBeNull()
  })
})
