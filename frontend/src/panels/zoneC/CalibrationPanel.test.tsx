/** Régression — C4 face à une projection TRONQUÉE (bug D-053).
 *  Le garde `if (!cal)` ne couvrait que l'absence TOTALE : un `{}` est truthy, donc
 *  `cal.quantitative.progress_pct` levait et le panneau disparaissait sans un mot. */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { CalibrationPanel } from './CalibrationPanel'
import { useTerminal } from '@/store/terminal'
import type { Calibration } from '@/types/schema'

const SANE = {
  quantitative: { n_trades: 3, window: 60, target: 50, progress_pct: 5, sharpe: null,
                  sharpe_displayable: false, valid: false },
  behavioral: { n_decisions: 4, n_go: 1, selfcheck_rate_pct: 100, recon_rate_pct: 50,
                timeouts: 0, valid: false },
  sharpe: { min_trades: 20 }, sizing_locked: true, sizing_pct: 50,
} as unknown as Calibration

beforeEach(() => useTerminal.getState().set({ calibration: null, projectionsBroken: false }))

describe('projection incomplète', () => {
  it.each([
    ['objet vide', {}],
    ['sans quantitative', { behavioral: SANE.behavioral }],
    ['sans behavioral', { quantitative: SANE.quantitative }],
    ['quantitative à null', { quantitative: null, behavioral: SANE.behavioral }],
    ['sous-objet sharpe manquant', { quantitative: SANE.quantitative, behavioral: SANE.behavioral }],
  ])('ne LÈVE pas et reste fail-closed : %s', (_label, payload) => {
    useTerminal.getState().set({ calibration: payload as unknown as Calibration })
    expect(() => render(<CalibrationPanel />)).not.toThrow()
    expect(screen.getByTestId('c4-unavailable')).toBeInTheDocument()
  })

  it('dit que la projection est INDISPONIBLE, sans inventer 0 %', () => {
    useTerminal.getState().set({ calibration: {} as unknown as Calibration })
    render(<CalibrationPanel />)
    const panel = screen.getByTestId('c4-unavailable')
    expect(panel).toHaveTextContent(/INDISPONIBLE/)
    expect(panel).not.toHaveTextContent('0 %')      // aucune jauge fabriquée
  })
})

describe('attente vs panne', () => {
  it('dit « chargement… » tant qu\'aucune réponse n\'est arrivée', () => {
    useTerminal.getState().set({ calibration: null, projectionsBroken: false })
    render(<CalibrationPanel />)
    expect(screen.getByText('chargement…')).toBeInTheDocument()
  })

  it('bascule sur INDISPONIBLE dès qu\'une réponse a été REJETÉE', () => {
    // Sinon « chargement… » devient éternel et masque une panne serveur réelle.
    useTerminal.getState().set({ calibration: null, projectionsBroken: true })
    render(<CalibrationPanel />)
    expect(screen.getByTestId('c4-unavailable')).toHaveTextContent('INDISPONIBLE')
    expect(screen.queryByText('chargement…')).toBeNull()
  })
})

describe('projection saine', () => {
  it('affiche les deux jauges normalement', () => {
    useTerminal.getState().set({ calibration: SANE })
    render(<CalibrationPanel />)
    expect(screen.getByText('Quantitatif')).toBeInTheDocument()
    expect(screen.getByText('Comportemental')).toBeInTheDocument()
    expect(screen.queryByTestId('c4-unavailable')).toBeNull()
  })
})
