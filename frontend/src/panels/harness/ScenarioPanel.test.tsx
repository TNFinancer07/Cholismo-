/** Régression — panneau MOCK face à un scénario TRONQUÉ (même défaut que C4/Zone D, D-053).
 *  `scenario?.available.map` protège du `null` mais pas d'un objet partiel truthy. */
import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { ScenarioPanel } from './ScenarioPanel'
import { useTerminal, type ScenarioInfo } from '@/store/terminal'

beforeEach(() => useTerminal.getState().set({ scenario: null, sources: null }))

describe('scénario incomplet', () => {
  it.each([
    ['objet vide', {}],
    ['sans available', { current: { name: 'calme' } }],
    ['sans current', { available: [{ name: 'calme', label: 'Calme' }] }],
    ['available non-tableau', { current: { name: 'calme' }, available: {} }],
  ])('ne LÈVE pas : %s', (_label, payload) => {
    useTerminal.getState().set({ scenario: payload as unknown as ScenarioInfo })
    expect(() => render(<ScenarioPanel />)).not.toThrow()
  })

  it('ne LÈVE pas sur un `sources` non-objet', () => {
    useTerminal.getState().set({
      scenario: { current: { name: 'calme', base: {} }, available: [], sliders: [] } as unknown as ScenarioInfo,
      sources: 'cassé' as never,
    })
    expect(() => render(<ScenarioPanel />)).not.toThrow()
  })
})
