/** Verrous F6/F7 à l'écran (D-113).
 *
 *  Le panneau existe pour que l'opérateur distingue « aucun signal » de « signal ÉCARTÉ ». Ce
 *  qui est testé, c'est qu'il ne puisse jamais dire le contraire de la vérité.
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProtectionLockPanel, compteARebours, libelleMotif } from './ProtectionLockPanel'

vi.mock('@/lib/api', () => ({ api: { protection: vi.fn() } }))
const { api } = await import('@/lib/api')

const VERROUILLE = {
  consecutive_losses: 2, trades_today: 3, locked: true,
  lock_reason: 'F6_COOLDOWN_ACTIVE', seconds_remaining: 754,
  recent_rejections: [{ reason: 'F6_COOLDOWN_ACTIVE', ts: 1, setup_id: null }],
}

function poser(p: unknown) {
  ;(api.protection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(p)
}

beforeEach(() => vi.clearAllMocks())

describe('état indisponible', () => {
  it('ne dit JAMAIS « déverrouillé » quand il ne sait pas', async () => {
    ;(api.protection as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('nope'))
    render(<ProtectionLockPanel />)
    const el = await screen.findByTestId('lock-inconnu')
    expect(el.textContent).toContain('ne signifie pas')
    expect(screen.queryByTestId('lock-etat')).toBeNull()
  })
})

describe('verrou actif', () => {
  it('affiche le motif en clair, pas le code', async () => {
    poser(VERROUILLE)
    render(<ProtectionLockPanel />)
    expect((await screen.findByTestId('lock-etat')).textContent).toContain('VERROUILLÉ')
    expect(screen.getByTestId('lock-motif').textContent).toContain('2 pertes consécutives')
  })

  it('rappelle que le verrou ne se désactive pas depuis l\'écran', async () => {
    poser(VERROUILLE)
    render(<ProtectionLockPanel />)
    expect((await screen.findByTestId('lock-motif')).textContent)
      .toContain('ne se désactive pas depuis l\'écran')
  })

  it('montre le temps restant', async () => {
    poser(VERROUILLE)
    render(<ProtectionLockPanel />)
    expect((await screen.findByTestId('lock-restant')).textContent).toContain('12 min 34 s')
  })

  it('liste les setups écartés — la réponse à « pourquoi rien n\'apparaît »', async () => {
    poser(VERROUILLE)
    render(<ProtectionLockPanel />)
    expect((await screen.findByTestId('lock-refus')).textContent).toContain('2 pertes')
  })
})

describe('sans verrou', () => {
  it('le dit explicitement plutôt que de rester muet', async () => {
    poser({ ...VERROUILLE, locked: false, lock_reason: null, seconds_remaining: null,
            consecutive_losses: 0, recent_rejections: [] })
    render(<ProtectionLockPanel />)
    expect((await screen.findByTestId('lock-etat')).textContent).toContain('aucun verrou')
    expect(screen.queryByTestId('lock-motif')).toBeNull()
  })
})

describe('formatage', () => {
  it('un motif inconnu est rendu TEL QUEL plutôt qu\'effacé', () => {
    expect(libelleMotif('F9_INEDIT')).toBe('F9_INEDIT')
    expect(libelleMotif(null)).toBe('—')
  })

  it('un compte à rebours absent ou négatif reste « — », jamais « 0 s »', () => {
    expect(compteARebours(null)).toBe('—')
    expect(compteARebours(-5)).toBe('—')
    expect(compteARebours(NaN)).toBe('—')
    expect(compteARebours(45)).toBe('45 s')
  })
})
