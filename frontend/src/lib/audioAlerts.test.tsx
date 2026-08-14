/** Câblage des alertes sonores (D-115).
 *
 *  Le cœur : **le silence ne doit jamais être ambigu**. Toute la garde de fraîcheur de D-114
 *  serait vaine si l'opérateur ne pouvait pas savoir si son canal d'alerte est muet.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AudioStatusIndicator, audioSupporte, ecrireConsentement, etatAudio, lireConsentement } from './audioAlerts'

class _FauxCtx {
  currentTime = 0
  destination = {}
  createOscillator() {
    return { frequency: { value: 0 }, type: '', connect: (n: unknown) => n, start() {}, stop() {} }
  }
  createGain() { return { gain: { value: 0 }, connect: (n: unknown) => n } }
}

beforeEach(() => { localStorage.clear() })
afterEach(() => { delete (globalThis as Record<string, unknown>).AudioContext })

// ------------------------------------------------------------------ consentement

describe('consentement', () => {
  it('est MUET par défaut — un terminal ne se met pas à sonner sans qu\'on le demande', () => {
    expect(lireConsentement()).toBe(false)
  })

  it('persiste le choix — le redemander à chaque rechargement le rendrait inutilisable', () => {
    ecrireConsentement(true)
    expect(lireConsentement()).toBe(true)
    ecrireConsentement(false)
    expect(lireConsentement()).toBe(false)
  })

  it('un stockage REFUSÉ retombe sur muet, jamais sur actif', () => {
    const casse = { getItem() { throw new Error('refusé') },
                    setItem() { throw new Error('refusé') } } as unknown as Storage
    expect(lireConsentement(casse)).toBe(false)
    expect(() => ecrireConsentement(true, casse)).not.toThrow()
  })
})

// ------------------------------------------------------------------ indicateur

describe('indicateur permanent', () => {
  it('sans audio dans le navigateur, le dit — le silence n\'est pas une mesure', async () => {
    render(<AudioStatusIndicator />)
    const el = await screen.findByTestId('audio-statut')
    expect(el.getAttribute('data-statut')).toBe('UNAVAILABLE')
    expect(el.textContent).toContain('indisponible')
    expect((el as HTMLButtonElement).disabled).toBe(true)
  })

  it('coupé, il dit MUET et prévient que le silence ne signifie pas « rien ne se passe »', async () => {
    ;(globalThis as Record<string, unknown>).AudioContext = _FauxCtx
    render(<AudioStatusIndicator />)
    const el = await screen.findByTestId('audio-statut')
    expect(el.getAttribute('data-statut')).toBe('OFF')
    expect(el.getAttribute('title')).toContain('ne signifie PAS')
  })

  it('porte une icône ET un texte — la couleur ne suffit jamais (§3)', async () => {
    ;(globalThis as Record<string, unknown>).AudioContext = _FauxCtx
    render(<AudioStatusIndicator />)
    const el = await screen.findByTestId('audio-statut')
    expect(el.textContent).toMatch(/muet/)
    expect(el.querySelector('[aria-hidden]')).not.toBeNull()
  })

  it('un consentement déjà donné est repris au montage', async () => {
    ;(globalThis as Record<string, unknown>).AudioContext = _FauxCtx
    ecrireConsentement(true)
    render(<AudioStatusIndicator />)
    expect((await screen.findByTestId('audio-statut')).getAttribute('data-statut')).toBe('ON')
  })

  it('un consentement donné SANS audio disponible ne rend pas « actif »', async () => {
    ecrireConsentement(true)          // pas d'AudioContext posé
    render(<AudioStatusIndicator />)
    expect((await screen.findByTestId('audio-statut')).getAttribute('data-statut'))
      .toBe('UNAVAILABLE')
  })
})

// ------------------------------------------------------------------ projection du flux

describe('projection vers la décision sonore', () => {
  it('un vide NON MESURABLE reste null, pas false', () => {
    expect(etatAudio({}).vacuum).toBeNull()
    expect(etatAudio({ liquidity_vacuum: { vacuum: null } }).vacuum).toBeNull()
    expect(etatAudio({ liquidity_vacuum: { vacuum: false } }).vacuum).toBe(false)
  })

  it('les DEUX gates doivent être connues pour conclure', () => {
    const une = { orderflow_shadow: { b1: { verdict_inhouse: true } } }
    expect(etatAudio(une).gatePassed).toBeNull()
    const deux = { orderflow_shadow: { b1: { verdict_inhouse: true },
                                       b2: { verdict_inhouse: true } } }
    expect(etatAudio(deux).gatePassed).toBe(true)
    const mixte = { orderflow_shadow: { b1: { verdict_inhouse: true },
                                        b2: { verdict_inhouse: false } } }
    expect(etatAudio(mixte).gatePassed).toBe(false)
  })

  it('des extras absents ne lèvent pas', () => {
    expect(() => etatAudio(null)).not.toThrow()
    expect(() => etatAudio(undefined)).not.toThrow()
    expect(etatAudio(null).gatePassed).toBeNull()
  })
})

describe('support', () => {
  it('détecte l\'absence d\'AudioContext', () => {
    expect(audioSupporte()).toBe(false)
    ;(globalThis as Record<string, unknown>).AudioContext = _FauxCtx
    expect(audioSupporte()).toBe(true)
  })
})
