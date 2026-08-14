/** Alertes sonores (D-114).
 *
 *  Un son est une AFFIRMATION : « ceci vient de se produire ». Ce qui est testé, c'est qu'on ne
 *  puisse jamais l'affirmer à tort — l'opérateur écoute précisément pour ne pas regarder l'écran.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { SoundPlayer, cue, decideCues } from './audio'

const FRAIS = { vacuum: false, gatePassed: false, freshness: 'FRESH' }

describe('garde de fraîcheur', () => {
  it('AUCUN son sur une donnée périmée', () => {
    const perime = { vacuum: true, gatePassed: true, freshness: 'STALE' }
    expect(decideCues(FRAIS, perime)).toEqual([])
    expect(decideCues(perime, { ...FRAIS, vacuum: true })).toEqual([])
  })

  it('AUCUN son sur une donnée absente', () => {
    const absent = { vacuum: true, gatePassed: true, freshness: 'ABSENT' }
    expect(decideCues(FRAIS, absent)).toEqual([])
  })

  it('AUCUN son sans état précédent — un franchissement demande DEUX états connus', () => {
    expect(decideCues(null, { ...FRAIS, vacuum: true })).toEqual([])
    expect(decideCues(undefined, { ...FRAIS, gatePassed: true })).toEqual([])
  })
})

describe('non mesurable ≠ négatif', () => {
  it('`null` ne déclenche rien, ni comme départ ni comme arrivée', () => {
    expect(decideCues({ ...FRAIS, vacuum: null }, { ...FRAIS, vacuum: true })).toEqual([])
    expect(decideCues({ ...FRAIS, vacuum: false }, { ...FRAIS, vacuum: null })).toEqual([])
  })

  it("une reconnexion ne doit PAS sonner : inconnu → vrai n'est pas un franchissement", () => {
    expect(decideCues({ vacuum: null, gatePassed: null, freshness: 'FRESH' },
                      { vacuum: true, gatePassed: true, freshness: 'FRESH' })).toEqual([])
  })
})

describe('transitions réelles', () => {
  it('le carnet qui se vide sonne une fois, au franchissement', () => {
    const c = decideCues(FRAIS, { ...FRAIS, vacuum: true })
    expect(c.map((x) => x.kind)).toEqual(['LIQUIDITY_VACUUM'])
    // Rester dans l'état ne re-sonne pas : un état n'est pas un événement.
    expect(decideCues({ ...FRAIS, vacuum: true }, { ...FRAIS, vacuum: true })).toEqual([])
  })

  it('une gate franchie et une gate refusée ont des sons DISTINCTS', () => {
    const passe = decideCues(FRAIS, { ...FRAIS, gatePassed: true })[0]
    const refuse = decideCues({ ...FRAIS, gatePassed: true }, FRAIS)[0]
    expect(passe.kind).toBe('OF_GATE_PASSED')
    expect(refuse.kind).toBe('OF_GATE_FAILED')
    expect(passe.frequency).not.toBe(refuse.frequency)
  })

  it('le grave porte le LOURD, l\'aigu porte le RAPIDE', () => {
    /* Mappage psycho-acoustique : on n'apprend pas un code arbitraire. */
    expect(cue('PROTECTION_REJECT').frequency).toBeLessThan(cue('OF_GATE_PASSED').frequency)
    expect(cue('LIQUIDITY_VACUUM').frequency).toBeLessThan(cue('OF_GATE_PASSED').frequency)
  })
})

class _FauxOsc {
  frequency = { value: 0 }
  type = ''
  connect(n: unknown) { return n }
  start() {}
  stop() {}
}
class _FauxCtx {
  currentTime = 0
  destination = {}
  createOscillator() { return new _FauxOsc() }
  createGain() { return { gain: { value: 0 }, connect: (n: unknown) => n } }
}

describe('anti-répétition', () => {
  beforeEach(() => {
    ;(globalThis as Record<string, unknown>).AudioContext = _FauxCtx
  })
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).AudioContext
  })

  it('un même événement ne sonne pas cinq fois de suite', () => {
    let t = 0
    const p = new SoundPlayer(3000, () => t)
    const c = cue('LIQUIDITY_VACUUM')
    expect(p.play(c)).toBe('PLAYED')
    t = 500
    expect(p.play(c)).toBe('THROTTLED')
    t = 4000
    expect(p.play(c)).toBe('PLAYED')
  })

  it('deux événements DIFFÉRENTS ne s\'étouffent pas mutuellement', () => {
    let t = 0
    const p = new SoundPlayer(3000, () => t)
    expect(p.play(cue('LIQUIDITY_VACUUM'))).toBe('PLAYED')
    expect(p.play(cue('PROTECTION_REJECT'))).toBe('PLAYED')
  })
})

describe('audio indisponible', () => {
  it("se DISTINGUE d'un étouffement — le silence n'a pas une seule cause", () => {
    const p = new SoundPlayer(0, () => 0)
    expect(p.play(cue('OF_GATE_PASSED'))).toBe('UNAVAILABLE')
  })

  it('ne lève jamais — le son est un confort, pas un canal de décision', () => {
    const p = new SoundPlayer(0, () => 0)
    expect(() => p.play(cue('OF_GATE_PASSED'))).not.toThrow()
  })
})
