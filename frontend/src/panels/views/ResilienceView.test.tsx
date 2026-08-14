/** Carte de sensibilité + biais du survivant (D-104).
 *
 *  Ce qui est vérifié : que l'écran ne puisse pas se lire comme une PRÉDICTION. Le disclaimer en
 *  tête, le badge par cellule (qui doit survivre à une capture d'écran hors contexte), et les
 *  deux « zéros » qui ne sont pas des zéros.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ResilienceView, classeRisque, pct } from './ResilienceView'

const SENS = {
  kind: 'sensitivity_map',
  disclaimer: 'Carte de SENSIBILITÉ : le taux réel du LSR est INCONNU.',
  axes: { slippage_ticks: [0, 1], win_rate: [0.35, 0.55] },
  cells: [
    [{ win_rate: 0.35, slippage_ticks: 0, ruin_probability: 0.25, status: 'HYPOTHESIS' },
     { win_rate: 0.55, slippage_ticks: 0, ruin_probability: 0.0, status: 'HYPOTHESIS' }],
    [{ win_rate: 0.35, slippage_ticks: 1, ruin_probability: 0.08, status: 'HYPOTHESIS' },
     { win_rate: 0.55, slippage_ticks: 1, ruin_probability: 0.001, status: 'HYPOTHESIS' }],
  ],
}

const BIAIS_OK = {
  kind: 'survivor_bias', status: 'OK', n_reconciled: 20, min_sample: 4,
  dd95_all: 58, dd95_survivors: 24, bias_r: 34, survival_rate: 0.295,
  detail: "L'écart mesure de combien on se mentirait.",
}

vi.mock('@/lib/api', () => ({ api: { analysesResilience: vi.fn() } }))
const { api } = await import('@/lib/api')

function poser(survivor_bias: unknown) {
  ;(api.analysesResilience as unknown as ReturnType<typeof vi.fn>)
    .mockResolvedValue({ sensitivity: SENS, survivor_bias })
}

beforeEach(() => vi.clearAllMocks())

describe('carte de sensibilité', () => {
  it('rend le disclaimer EN TÊTE, pas en note de bas de tableau', async () => {
    poser(BIAIS_OK)
    render(<ResilienceView />)
    const d = await screen.findByTestId('resilience-disclaimer')
    expect(d.textContent).toContain('INCONNU')
  })

  it('chaque cellule porte le badge HYPOTHÈSE — il doit survivre hors contexte', async () => {
    poser(BIAIS_OK)
    render(<ResilienceView />)
    await screen.findByTestId('resilience-disclaimer')
    expect(screen.getAllByText('HYPOTHÈSE')).toHaveLength(4)
  })

  it('classe le risque par SEUILS NOMMÉS, pas par dégradé continu', () => {
    expect(classeRisque(0.25).label).toBe('élevé')
    expect(classeRisque(0.08).label).toBe('notable')
    expect(classeRisque(0.001).label).toBe('faible')
    expect(classeRisque(NaN).label).toBe('—')
  })

  it('un pourcentage absent reste « — », jamais 0 %', () => {
    expect(pct(null)).toBe('—')
    expect(pct(undefined)).toBe('—')
    expect(pct(0)).toBe('0.0 %')
  })
})

describe('biais du survivant', () => {
  it('publie TOUJOURS les deux chiffres, jamais le seul flatteur', async () => {
    poser(BIAIS_OK)
    render(<ResilienceView />)
    expect((await screen.findByTestId('dd95-all')).textContent).toContain('58')
    expect(screen.getByTestId('dd95-surv').textContent).toContain('24')
    expect(screen.getByTestId('biais-ecart').textContent).toContain('34')
  })

  it('un échantillon insuffisant REFUSE de chiffrer', async () => {
    poser({ ...BIAIS_OK, status: 'NOT_ENOUGH_DATA', n_reconciled: 2,
            dd95_all: null, dd95_survivors: null, bias_r: null, survival_rate: null })
    render(<ResilienceView />)
    const r = await screen.findByTestId('biais-refus')
    expect(r.textContent).toContain('2/4')
    expect(screen.queryByTestId('dd95-all')).toBeNull()
  })

  it('« aucune ruine » se lit « non mesurable », jamais « biais nul »', async () => {
    poser({ ...BIAIS_OK, status: 'NO_RUIN_OBSERVED', bias_r: null, survival_rate: 1 })
    render(<ResilienceView />)
    expect((await screen.findByTestId('biais-ecart')).textContent).toContain('non mesurable')
    expect(screen.getByTestId('biais-non-mesurable').textContent).toContain('et non')
  })
})

// ------------------------------------------------------------------ routage (D-105)

describe('routage', () => {
  /* Rendre l'App entière tirerait tout le terminal (SSE, 48 panneaux) et casserait sur le mock
     partiel d'`api` — un test lourd qui prouverait surtout que le reste marche. On vérifie donc
     le CÂBLAGE à la source, comme le garde §2.1 de Tradovate : la vue est-elle atteignable ?
     Une vue non routée est du code mort, la faute relevée en D-096. */
  it('la vue est routée dans App.tsx', async () => {
    const src = (await import('@/App.tsx?raw')).default
    expect(src).toContain('ResilienceView')
    expect(src).toMatch(/view === 'RESIL'/)
  })

  it("l'identifiant de vue existe et la barre de commandes y mène", async () => {
    const store = (await import('@/store/terminal.ts?raw')).default
    const bar = (await import('@/components/CommandBar.tsx?raw')).default
    expect(store).toContain("'RESIL'")
    expect(bar).toMatch(/view\('RESIL', 'RESIL'/)
  })
})
