/** Panneau de contrôle du Replay (D-058).
 *
 *  Ce que ces tests figent, dans l'ordre d'importance :
 *  1. le bandeau REJEU est TOUJOURS là quand le replay tourne — un rejeu pris pour du direct est
 *     le pire état possible de ce terminal ;
 *  2. hors mode replay, le panneau DIT pourquoi au lieu d'afficher des boutons inertes ;
 *  3. une commande refusée montre son motif — jamais un échec muet.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReplayPanel } from './ReplayPanel'
import type { ReplayState } from '@/types/replay'

const ETAT: ReplayState = {
  resume: 'LECTURE ×5 · tick 85/366 · t+20.0s de séance · 34 ligne(s) écartée(s)',
  filepath: '/tmp/tape.csv',
  playing: true,
  speed: 5,
  position: 85,
  total: 366,
  clock: 1020,
  first_ts: 1000,
  last_ts: 1108,
  offset: 12345,
  finished: false,
  source: 'replay',
  skipped: 34,
  skipped_reasons: { 'prix illisible ou non positif': 20, 'côté inconnu': 14 },
}

const etatState = vi.fn<() => Promise<ReplayState>>()
const controlSpy = vi.fn<(cmd: unknown) => Promise<ReplayState>>()

vi.mock('@/lib/api', () => ({
  api: {
    replayState: () => etatState(),
    replayControl: (cmd: unknown) => controlSpy(cmd),
  },
}))

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  etatState.mockReset().mockResolvedValue(ETAT)
  controlSpy.mockReset().mockResolvedValue({ ...ETAT, playing: false })
})
afterEach(() => {
  vi.useRealTimers()
  cleanup()
})

describe('bandeau de rejeu', () => {
  it('affiche TOUJOURS que ce sont des prints rejoués', async () => {
    render(<ReplayPanel />)
    const bandeau = await screen.findByTestId('replay-banner')
    // Le statut ne tient jamais à la seule couleur (§3) : il y a un MOT, et il est explicite.
    expect(bandeau.textContent).toContain('REJEU')
    expect(bandeau.textContent).toContain('ENREGISTREMENT')
  })

  it('reprend le résumé du serveur, sans le reformater', async () => {
    render(<ReplayPanel />)
    // Une seule source de vérité pour ce texte : le reformater côté UI ferait diverger les deux.
    expect((await screen.findByTestId('replay-resume')).textContent).toBe(ETAT.resume)
  })

  it('montre les lignes écartées du fichier avec leurs motifs', async () => {
    render(<ReplayPanel />)
    const t = (await screen.findByTestId('replay-skipped')).textContent ?? ''
    expect(t).toContain('34 ligne(s)')
    expect(t).toContain('20× prix illisible ou non positif')
  })
})

describe('contrôle', () => {
  it('bascule lecture → pause et envoie la bonne commande', async () => {
    render(<ReplayPanel />)
    fireEvent.click(await screen.findByTestId('replay-toggle'))
    await waitFor(() => expect(controlSpy).toHaveBeenCalledWith({ action: 'pause' }))
  })

  it('bascule pause → lecture', async () => {
    etatState.mockResolvedValue({ ...ETAT, playing: false })
    render(<ReplayPanel />)
    fireEvent.click(await screen.findByTestId('replay-toggle'))
    await waitFor(() => expect(controlSpy).toHaveBeenCalledWith({ action: 'play' }))
  })

  it('change la vitesse à la volée', async () => {
    render(<ReplayPanel />)
    fireEvent.click(await screen.findByTestId('replay-speed-25'))
    await waitFor(() => expect(controlSpy).toHaveBeenCalledWith({ action: 'speed', speed: 25 }))
  })

  it('marque la vitesse courante — l’opérateur ne devine pas où il en est', async () => {
    render(<ReplayPanel />)
    const actif = await screen.findByTestId('replay-speed-5')
    expect(actif.className).toContain('amber')
    expect((await screen.findByTestId('replay-speed-1')).className).not.toContain('amber')
  })

  it('seek envoie une FRACTION, pas une position brute', async () => {
    render(<ReplayPanel />)
    fireEvent.change(await screen.findByTestId('replay-seek'), { target: { value: '50' } })
    await waitFor(() => expect(controlSpy).toHaveBeenCalledWith({ action: 'seek', fraction: 0.5 }))
  })

  it('relance depuis le début', async () => {
    render(<ReplayPanel />)
    fireEvent.click(await screen.findByTestId('replay-restart'))
    await waitFor(() => expect(controlSpy).toHaveBeenCalledWith({ action: 'restart' }))
  })

  it('désactive lecture/pause quand le fichier est TERMINÉ', async () => {
    etatState.mockResolvedValue({ ...ETAT, finished: true, playing: false })
    render(<ReplayPanel />)
    const bouton = await screen.findByTestId('replay-toggle')
    expect(bouton).toBeDisabled()
    fireEvent.click(bouton)
    expect(controlSpy).not.toHaveBeenCalled()
  })
})

describe('états dégradés', () => {
  it('hors mode replay, DIT pourquoi au lieu d’afficher des boutons inertes', async () => {
    etatState.mockRejectedValue(new Error(
      "le terminal n'est pas en mode replay — démarrer avec REPLAY_FILE=<tape.csv>"))
    render(<ReplayPanel />)
    await waitFor(() =>
      expect(screen.getByText(/pas en mode replay/)).toBeTruthy())
    expect(screen.queryByTestId('replay-toggle')).toBeNull()
    expect(screen.queryByTestId('replay-banner')).toBeNull()
  })

  it('une commande refusée montre son MOTIF, jamais un échec muet', async () => {
    controlSpy.mockRejectedValue(new Error('action « seek » sans cible'))
    render(<ReplayPanel />)
    fireEvent.click(await screen.findByTestId('replay-restart'))
    await waitFor(() =>
      expect(screen.getByTestId('replay-error').textContent).toContain('sans cible'))
  })

  it('un total INCONNU ne s’affiche pas comme zéro', async () => {
    etatState.mockResolvedValue({ ...ETAT, total: null, position: 0 })
    render(<ReplayPanel />)
    // `null` veut dire « pas encore indexé », pas « aucun tick » — les afficher pareil serait
    // la confusion absent/zéro que ce terminal refuse (§3).
    await waitFor(() => expect(screen.getByText(/POSITION 0\/\?/)).toBeTruthy())
  })
})
