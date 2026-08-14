/** Fenêtre détachée (D-116).
 *
 *  Le seul vrai danger du multi-fenêtre : une fenêtre désynchronisée ressemble à un marché calme.
 */
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DetachedPanelWindow } from './DetachedPanelWindow'

class _FauxChannel {
  static dernier: _FauxChannel | null = null
  private handlers: ((e: MessageEvent) => void)[] = []
  constructor(public name: string) { _FauxChannel.dernier = this }
  postMessage() {}
  addEventListener(_t: string, h: (e: MessageEvent) => void) { this.handlers.push(h) }
  removeEventListener(_t: string, h: (e: MessageEvent) => void) {
    this.handlers = this.handlers.filter((x) => x !== h)
  }
  close() {}
  emit(data: unknown) { this.handlers.forEach((h) => h({ data } as MessageEvent)) }
}

beforeEach(() => { (globalThis as Record<string, unknown>).BroadcastChannel = _FauxChannel })
afterEach(() => {
  delete (globalThis as Record<string, unknown>).BroadcastChannel
  vi.useRealTimers()
})

describe('bandeau de synchronisation', () => {
  it("une fenêtre qui vient de s'ouvrir dit « en attente », jamais « synchronisé »", () => {
    render(<DetachedPanelWindow panelId="B1" />)
    const b = screen.getByTestId('detach-sync')
    expect(b.getAttribute('data-statut')).toBe('UNKNOWN')
    expect(b.textContent).toContain('rien reçu')
  })

  it('après réception, il passe synchronisé et date la dernière mise à jour', () => {
    render(<DetachedPanelWindow panelId="B1" />)
    act(() => _FauxChannel.dernier!.emit({ payload: {}, sentAt: Date.now() }))
    const b = screen.getByTestId('detach-sync')
    expect(b.getAttribute('data-statut')).toBe('LIVE')
    expect(b.textContent).toContain('il y a 0 s')
  })

  it('un message SANS horodatage ne rend PAS la fenêtre « synchronisée »', () => {
    render(<DetachedPanelWindow panelId="B1" />)
    act(() => _FauxChannel.dernier!.emit({ payload: { a: 1 } }))
    expect(screen.getByTestId('detach-sync').getAttribute('data-statut')).toBe('UNKNOWN')
  })

  it('le bandeau est en TÊTE — ce qu\'on lit en dernier, on ne le lit pas', () => {
    const { container } = render(<DetachedPanelWindow panelId="B1" />)
    const premier = container.querySelector('[data-testid]')
    expect(premier?.getAttribute('data-testid')).toBe('detach-sync')
  })
})

describe('panneau demandé', () => {
  it('un panneau inconnu n\'affiche RIEN de substitution', () => {
    render(<DetachedPanelWindow panelId="NEXISTE_PAS" />)
    expect(screen.getByTestId('detach-inconnu').textContent).toContain('inconnu')
  })

  it('un panneau connu est rendu', () => {
    render(<DetachedPanelWindow panelId="B1" />)
    expect(screen.queryByTestId('detach-inconnu')).toBeNull()
  })
})

describe('isolation du backend', () => {
  it("n'ouvre AUCUNE connexion SSE — deux abonnements feraient diverger deux fenêtres", async () => {
    const src = (await import('./DetachedPanelWindow.tsx?raw')).default
    expect(src).not.toMatch(/connectSSE|EventSource|fetch\(/)
  })
})
