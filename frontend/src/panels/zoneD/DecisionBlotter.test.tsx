/** Régression — Zone D face à une projection TRONQUÉE (bug D-053).
 *  `decisions.decisions` valant `undefined`, le store recevait `undefined` là où son type promet
 *  un tableau : `decisions.length` levait et le blotter — la vue du Decision Log — disparaissait. */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { DecisionBlotter } from './DecisionBlotter'
import { useTerminal } from '@/store/terminal'
import type { BlotterRow } from '@/types/schema'

const ROW = {
  id: 'evt-1', ts: 1_700_000_000, operator: 'SONY', instrument: 'ES', decision: 'GO',
  score: 72, reason: 'sweep', selfcheck: true, outcome: null, recon: null,
} as unknown as BlotterRow

beforeEach(() => useTerminal.getState().set({ decisions: [], projectionsBroken: false }))

describe('projection incomplète', () => {
  it.each([
    ['undefined', undefined],
    ['null', null],
    ['objet au lieu d\'un tableau', {}],
    ['chaîne', 'cassé'],
  ])('ne LÈVE pas quand `decisions` vaut %s', (_label, payload) => {
    useTerminal.getState().set({ decisions: payload as unknown as BlotterRow[] })
    expect(() => render(<DecisionBlotter />)).not.toThrow()
    // Fail-closed HONNÊTE : « projection indisponible » et non « log vide » — confondre les deux
    // ferait croire à un journal vide alors qu'il ne l'est pas.
    expect(screen.getByTestId('blotter-unavailable')).toHaveTextContent('PROJECTION INDISPONIBLE')
    expect(screen.queryByText(/aucun event/)).toBeNull()
  })
})

describe('projection rejetée à la frontière', () => {
  it('ne prétend pas que le log est VIDE quand la projection est cassée', () => {
    useTerminal.getState().set({ decisions: [], projectionsBroken: true })
    render(<DecisionBlotter />)
    expect(screen.getByTestId('blotter-unavailable')).toBeInTheDocument()
    expect(screen.queryByText(/aucun event/)).toBeNull()
  })

  it('garde les lignes DÉJÀ reçues : append-only, elles restent vraies', () => {
    useTerminal.getState().set({ decisions: [ROW], projectionsBroken: true })
    render(<DecisionBlotter />)
    expect(screen.getByText('ES')).toBeInTheDocument()
    expect(screen.queryByTestId('blotter-unavailable')).toBeNull()
  })
})

describe('projection saine', () => {
  it('affiche les lignes du log', () => {
    useTerminal.getState().set({ decisions: [ROW] })
    render(<DecisionBlotter />)
    expect(screen.getByText('ES')).toBeInTheDocument()
    expect(screen.queryByText(/aucun event/)).toBeNull()
  })
})
