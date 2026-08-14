/** Détachement de panneaux (D-116).
 *
 *  Le défaut à empêcher : une fenêtre détachée qui a perdu la synchronisation ressemble
 *  exactement à un marché calme — des chiffres lisibles qui ne bougent plus, sur un moniteur
 *  regardé du coin de l'œil.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DetachChannel,
  SYNC_LABELS,
  SYNC_LOST_MS,
  SYNC_STALE_MS,
  detachedPanelId,
  syncStatus,
} from './detach'

afterEach(() => { vi.restoreAllMocks() })

// ------------------------------------------------------------------ âge de synchronisation

describe('âge de synchronisation', () => {
  it("une fenêtre qui n'a RIEN reçu n'est pas « à jour »", () => {
    expect(syncStatus(null, 1000)).toBe('UNKNOWN')
    expect(syncStatus(undefined, 1000)).toBe('UNKNOWN')
    expect(SYNC_LABELS.UNKNOWN.titre).toContain("n'est pas « à jour »")
  })

  it('bascule STALE puis LOST à mesure que le silence dure', () => {
    expect(syncStatus(1000, 1000)).toBe('LIVE')
    expect(syncStatus(1000, 1000 + SYNC_STALE_MS - 1)).toBe('LIVE')
    expect(syncStatus(1000, 1000 + SYNC_STALE_MS)).toBe('STALE')
    expect(syncStatus(1000, 1000 + SYNC_LOST_MS)).toBe('LOST')
  })

  it('SYNC PERDUE dit que les chiffres ne décrivent PLUS le marché', () => {
    expect(SYNC_LABELS.LOST.titre).toContain('ne décrivent PLUS')
    expect(SYNC_LABELS.LOST.txt).toBe('SYNC PERDUE')
  })

  it("un horodatage FUTUR ne conclut pas — deux fenêtres peuvent avoir des horloges décalées", () => {
    expect(syncStatus(2000, 1000)).toBe('UNKNOWN')
  })

  it('un horodatage non fini ne devient pas « à jour »', () => {
    expect(syncStatus(NaN, 1000)).toBe('UNKNOWN')
    expect(syncStatus(Infinity, 1000)).toBe('UNKNOWN')
  })
})

// ------------------------------------------------------------------ canal

class _FauxChannel {
  static dernier: _FauxChannel | null = null
  messages: unknown[] = []
  private handlers: ((e: MessageEvent) => void)[] = []
  constructor(public name: string) { _FauxChannel.dernier = this }
  postMessage(m: unknown) { this.messages.push(m) }
  addEventListener(_t: string, h: (e: MessageEvent) => void) { this.handlers.push(h) }
  removeEventListener(_t: string, h: (e: MessageEvent) => void) {
    this.handlers = this.handlers.filter((x) => x !== h)
  }
  close() {}
  emit(data: unknown) { this.handlers.forEach((h) => h({ data } as MessageEvent)) }
}

describe('canal de rediffusion', () => {
  it("date le message à l'ÉMISSION, pas à la réception", () => {
    ;(globalThis as Record<string, unknown>).BroadcastChannel = _FauxChannel
    const c = new DetachChannel('t')
    c.post({ a: 1 }, 12345)
    expect(_FauxChannel.dernier!.messages[0]).toEqual({ payload: { a: 1 }, sentAt: 12345 })
    delete (globalThis as Record<string, unknown>).BroadcastChannel
  })

  it('un message SANS horodatage est ignoré — il serait indatable', () => {
    ;(globalThis as Record<string, unknown>).BroadcastChannel = _FauxChannel
    const c = new DetachChannel('t')
    const recus: unknown[] = []
    c.subscribe((m) => recus.push(m))
    _FauxChannel.dernier!.emit({ payload: { a: 1 } })      // pas de sentAt
    _FauxChannel.dernier!.emit(undefined)
    expect(recus).toEqual([])
    delete (globalThis as Record<string, unknown>).BroadcastChannel
  })

  it("sans BroadcastChannel, se dégrade sans casser la fenêtre principale", () => {
    const c = new DetachChannel('t')
    expect(c.available).toBe(false)
    expect(c.post({ a: 1 })).toBe(false)
    expect(() => c.subscribe(() => {})()).not.toThrow()
    expect(() => c.close()).not.toThrow()
  })
})

// ------------------------------------------------------------------ routage

describe('identification de la fenêtre', () => {
  it('sans paramètre, la fenêtre est la principale', () => {
    expect(detachedPanelId('')).toBeNull()
    expect(detachedPanelId('?autre=1')).toBeNull()
    expect(detachedPanelId('?panel=')).toBeNull()
    expect(detachedPanelId('?panel=%20%20')).toBeNull()
  })

  it('avec un paramètre, elle rend le panneau demandé', () => {
    expect(detachedPanelId('?panel=OFG')).toBe('OFG')
    expect(detachedPanelId('?panel=C6&x=1')).toBe('C6')
  })
})
