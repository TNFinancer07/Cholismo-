/** Tests RTL du panneau C5 (D-051) : ce que l'OPÉRATEUR voit réellement à l'écran.
 *  Les paliers, les rejets et le fail-closed sont vérifiés par le TEXTE rendu — jamais par la
 *  couleur (§3), ce qui est précisément la propriété qu'on veut garantir. */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { AccountBufferPanel } from './AccountBufferPanel'
import { useTerminal } from '@/store/terminal'
import type { AccountStateBlock } from '@/types/schema'

const base: AccountStateBlock = {
  status: 'APPROVED', is_stale: false,
  current_equity: 49_500, day_start_equity: 50_000, drawdown_floor: 47_500,
  daily_loss_limit: 1_000, buffer: 500, buffer_initial: 1_000, day_pnl: -500,
  next_ticket: { instrument: 'MES', stop_ticks: 3, contracts: 26, risk_allowed: 100, status: 'APPROVED' },
}
const mount = (o: Partial<AccountStateBlock> | null = {}) => {
  useTerminal.getState().set({ account_state: o === null ? null : { ...base, ...o } })
  return render(<AccountBufferPanel />)
}

beforeEach(() => useTerminal.getState().set({ account_state: null }))

describe('bloc équité', () => {
  it('affiche l\'équité et le P&L du jour signé', () => {
    mount()
    expect(screen.getByTestId('equity')).toHaveTextContent('49,500')
    expect(screen.getByTestId('day-pnl')).toHaveTextContent('−500')
    expect(screen.getByTestId('nt8-link')).toHaveTextContent('NT8 FRAIS')
  })
  it('marque le gain avec une FLÈCHE en plus de la couleur (§3)', () => {
    mount({ current_equity: 50_600, day_pnl: 600, buffer: 1_000 })
    expect(screen.getByTestId('day-pnl')).toHaveTextContent('▲')
    expect(screen.getByTestId('day-pnl')).toHaveTextContent('+600')
  })
})

describe('jauge de buffer', () => {
  it('rend la largeur proportionnelle et le pourcentage', () => {
    mount()
    const bar = screen.getByTestId('buffer-bar')
    expect(bar).toHaveStyle({ width: '50%' })
    expect(bar).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByTestId('buffer-tier')).toHaveTextContent('MARGE RÉDUITE')
    expect(screen.getByTestId('buffer-abs')).toHaveTextContent('500 $ / 1,000 $')
  })
  it('palier sain > 60 %', () => {
    mount({ buffer: 800 })
    expect(screen.getByTestId('buffer-tier')).toHaveTextContent('MARGE SAINE')
    expect(screen.getByTestId('buffer-bar')).toHaveStyle({ width: '80%' })
  })
  it('palier critique < 30 % — clignotant ET libellé explicite', () => {
    mount({ buffer: 200 })
    expect(screen.getByTestId('buffer-tier')).toHaveTextContent('MARGE CRITIQUE')
    expect(screen.getByTestId('buffer-bar').className).toContain('animate-pulse')
  })
  it('buffer ≤ 0 → la barre est REMPLACÉE par un BLOQUÉ explicite (pas une barre vide)', () => {
    mount({ buffer: -250, status: 'INSUFFICIENT_BUFFER',
      next_ticket: { ...base.next_ticket, contracts: null, status: 'INSUFFICIENT_BUFFER' } })
    expect(screen.getByTestId('buffer-dead')).toHaveTextContent('BLOQUÉ')
    expect(screen.queryByTestId('buffer-bar')).toBeNull()
  })
  it('grandeurs absentes → palier INCONNU, jamais un faux vert', () => {
    mount({ buffer: null, buffer_initial: null })
    expect(screen.getByTestId('buffer-tier')).toHaveTextContent('INCONNU')
    expect(screen.getByTestId('buffer-abs')).toHaveTextContent('· $ / · $')
  })
})

describe('prochain ticket', () => {
  it('affiche les contrats alloués et le stop de référence', () => {
    mount()
    expect(screen.getByTestId('next-contracts')).toHaveTextContent('26 contrats')
    expect(screen.getByText(/stop réf\. 3 ticks MES/)).toBeInTheDocument()
    expect(screen.getByText(/risque 100 \$ \(1\/5\)/)).toBeInTheDocument()
  })
  it('singulier pour 1 contrat', () => {
    mount({ next_ticket: { ...base.next_ticket, contracts: 1 } })
    expect(screen.getByTestId('next-contracts')).toHaveTextContent('1 contrat')
    expect(screen.getByTestId('next-contracts')).not.toHaveTextContent('contrats')
  })
  it('rejet du sizer → badge EXPLICITE au lieu d\'une taille', () => {
    for (const [status, label] of [['INSUFFICIENT_BUFFER', 'MARGE INSUFFISANTE'],
      ['INVALID_INPUT', 'DONNÉES COMPTE INVALIDES'],
      ['SIZE_SANITY_CAP', 'TAILLE INVRAISEMBLABLE']] as const) {
      const { unmount } = mount({ status,
        next_ticket: { ...base.next_ticket, contracts: null, risk_allowed: null, status } })
      expect(screen.getByTestId('next-reject')).toHaveTextContent(label)
      expect(screen.queryByTestId('next-contracts')).toBeNull()
      unmount()
    }
  })
})

describe('fail-closed UI', () => {
  it('déconnecté → CONNECTIVITÉ NT8 REQUISE et AUCUNE grandeur affichée', () => {
    mount({ status: 'DISCONNECTED', is_stale: true, current_equity: null, day_start_equity: null,
      drawdown_floor: null, daily_loss_limit: null, buffer: null, buffer_initial: null,
      day_pnl: null, next_ticket: { ...base.next_ticket, contracts: null, status: 'DISCONNECTED' } })
    expect(screen.getByTestId('account-offline')).toHaveTextContent('CONNECTIVITÉ NT8 REQUISE')
    expect(screen.getByTestId('nt8-link')).toHaveTextContent('NT8 ABSENT')
    expect(screen.queryByTestId('equity')).toBeNull()
    expect(screen.queryByTestId('buffer-bar')).toBeNull()
    expect(screen.queryByTestId('next-contracts')).toBeNull()
  })
  it('bloc absent du store → même écran fail-closed, aucun crash', () => {
    mount(null)
    expect(screen.getByTestId('account-offline')).toHaveTextContent('CONNECTIVITÉ NT8 REQUISE')
  })
  it('une équité PÉRIMÉE n\'est jamais affichée, même si le backend l\'a envoyée', () => {
    // pathologie : is_stale true MAIS des valeurs présentes (backend incohérent) → on n'affiche rien
    mount({ is_stale: true, status: 'DISCONNECTED' })
    expect(screen.queryByText(/49,500/)).toBeNull()
  })
})
