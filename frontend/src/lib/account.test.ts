/** Tests unitaires des dérivations d'affichage du compte (D-051) — logique PURE.
 *  Les paliers de la spec : > 60 % sain · 30–60 % réduit · < 30 % critique · ≤ 0 mort. */
import { describe, expect, it } from 'vitest'
import { BUFFER_CAUTION, BUFFER_CRITICAL, TIER_STYLE, bufferRatio, bufferTier, isLive, ticketDisplay, usd, usdSigned } from './account'
import type { AccountStateBlock } from '@/types/schema'

const base: AccountStateBlock = {
  status: 'APPROVED', is_stale: false,
  current_equity: 49_500, day_start_equity: 50_000, drawdown_floor: 47_500,
  daily_loss_limit: 1_000, buffer: 500, buffer_initial: 1_000, day_pnl: -500,
  next_ticket: { instrument: 'MES', stop_ticks: 3, contracts: 26, risk_allowed: 100, status: 'APPROVED' },
}
const acc = (o: Partial<AccountStateBlock> = {}): AccountStateBlock => ({ ...base, ...o })

describe('bufferRatio', () => {
  it('rend le ratio restant / ouverture', () => {
    expect(bufferRatio(acc())).toBe(0.5)
    expect(bufferRatio(acc({ buffer: 1_000 }))).toBe(1)
  })
  it('borne à [0,1] — un buffer négatif ne descend pas sous 0, un surplus ne dépasse pas 1', () => {
    expect(bufferRatio(acc({ buffer: -300 }))).toBe(0)
    expect(bufferRatio(acc({ buffer: 1_500 }))).toBe(1)
  })
  it('rend null quand indéterminable — jamais un 0 % trompeur', () => {
    expect(bufferRatio(null)).toBeNull()
    expect(bufferRatio(acc({ buffer: null }))).toBeNull()
    expect(bufferRatio(acc({ buffer_initial: null }))).toBeNull()
    expect(bufferRatio(acc({ buffer_initial: 0 }))).toBeNull()      // division par zéro
    expect(bufferRatio(acc({ buffer: Number.NaN }))).toBeNull()
  })
})

describe('bufferTier — paliers de la spec', () => {
  it('> 60 % → SAFE', () => {
    expect(bufferTier(acc({ buffer: 700 }))).toBe('SAFE')           // 70 %
    expect(bufferTier(acc({ buffer: 601 }))).toBe('SAFE')           // 60,1 %
  })
  it('60 % pile → CAUTION (la borne appartient au palier prudent, le doute vers le prudent)', () => {
    expect(bufferTier(acc({ buffer: 600 }))).toBe('CAUTION')
    expect(BUFFER_CAUTION).toBe(0.6)
  })
  it('30–60 % → CAUTION, 30 % pile inclus', () => {
    expect(bufferTier(acc({ buffer: 450 }))).toBe('CAUTION')
    expect(bufferTier(acc({ buffer: 300 }))).toBe('CAUTION')
    expect(BUFFER_CRITICAL).toBe(0.3)
  })
  it('< 30 % → CRITICAL (clignotant)', () => {
    expect(bufferTier(acc({ buffer: 299 }))).toBe('CRITICAL')
    expect(bufferTier(acc({ buffer: 1 }))).toBe('CRITICAL')
    expect(TIER_STYLE.CRITICAL.blink).toBe(true)
  })
  it('buffer ≤ 0 → DEAD, jamais « 0 % critique »', () => {
    expect(bufferTier(acc({ buffer: 0 }))).toBe('DEAD')
    expect(bufferTier(acc({ buffer: -250 }))).toBe('DEAD')
  })
  it('données absentes → UNKNOWN, jamais un faux vert', () => {
    expect(bufferTier(null)).toBe('UNKNOWN')
    expect(bufferTier(acc({ buffer: null }))).toBe('UNKNOWN')
    expect(bufferTier(acc({ buffer: 500, buffer_initial: null }))).toBe('UNKNOWN')
  })
  it('§3 — chaque palier porte un LIBELLÉ et une ICÔNE, pas seulement une couleur', () => {
    for (const tier of ['SAFE', 'CAUTION', 'CRITICAL', 'DEAD', 'UNKNOWN'] as const) {
      expect(TIER_STYLE[tier].label.length).toBeGreaterThan(0)
      expect(TIER_STYLE[tier].icon.length).toBeGreaterThan(0)
    }
    // ...et les libellés sont DISTINCTS (un daltonien doit pouvoir les différencier)
    const labels = Object.values(TIER_STYLE).map((s) => s.label)
    expect(new Set(labels).size).toBe(labels.length)
  })
})

describe('isLive', () => {
  it('vrai seulement si exploitable', () => {
    expect(isLive(acc())).toBe(true)
    expect(isLive(null)).toBe(false)
    expect(isLive(acc({ status: 'DISCONNECTED', is_stale: true }))).toBe(false)
    expect(isLive(acc({ is_stale: true }))).toBe(false)
  })
  it('un rejet de sizing reste LIVE — le compte est lu, c\'est la taille qui est refusée', () => {
    expect(isLive(acc({ status: 'INSUFFICIENT_BUFFER' }))).toBe(true)
  })
})

describe('formatage', () => {
  it('absent → tiret neutre, jamais un faux zéro', () => {
    expect(usd(null)).toBe('·')
    expect(usd(Number.NaN)).toBe('·')
    expect(usdSigned(undefined)).toBe('·')
  })
  it('signe explicite du P&L, y compris le gain', () => {
    expect(usdSigned(600)).toBe('+600')
    expect(usdSigned(-500)).toBe('−500')
    expect(usdSigned(0)).toBe('0')
  })
  it('séparateurs de milliers pour la lecture rapide', () => {
    expect(usd(49_500)).toBe('49,500')
  })
})

// --- /devil D-051 : cohérence du ticket, jauge indéterminable, valeurs extrêmes -------------

describe('/devil — ticketDisplay : la taille n\'est affichable que si le sizer l\'a APPROUVÉE', () => {
  it('APPROVED + contrats entiers positifs → taille', () => {
    const d = ticketDisplay(acc())
    expect(d).toEqual({ kind: 'SIZE', contracts: 26 })
  })
  it('PAYLOAD CONTRADICTOIRE — contrats présents mais statut REJETÉ → jamais la taille', () => {
    const d = ticketDisplay(acc({ status: 'INSUFFICIENT_BUFFER',
      next_ticket: { ...base.next_ticket, contracts: 26, status: 'INSUFFICIENT_BUFFER' } }))
    expect(d.kind).toBe('REJECT')
    expect(d).not.toHaveProperty('contracts', 26)
  })
  it('statut du bloc et du ticket DIVERGENTS → rejet (le plus prudent gagne)', () => {
    expect(ticketDisplay(acc({ status: 'INSUFFICIENT_BUFFER' })).kind).toBe('REJECT')
    expect(ticketDisplay(acc({
      next_ticket: { ...base.next_ticket, status: 'SIZE_SANITY_CAP' } })).kind).toBe('REJECT')
  })
  it('ticket ABSENT alors que le statut dit APPROVED → INDÉTERMINÉ, jamais une valeur inventée', () => {
    const d = ticketDisplay(acc({ next_ticket: undefined as never }))
    expect(d).toEqual({ kind: 'REJECT', label: 'INDÉTERMINÉ' })
    expect(ticketDisplay(acc({ next_ticket: null as never })))
      .toEqual({ kind: 'REJECT', label: 'INDÉTERMINÉ' })
  })
  it('contrats non entiers, nuls ou négatifs → INDÉTERMINÉ (jamais « 0 contrat » ni « 2.5 »)', () => {
    for (const bad of [0, -3, 2.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      const d = ticketDisplay(acc({ next_ticket: { ...base.next_ticket, contracts: bad } }))
      expect(d).toEqual({ kind: 'REJECT', label: 'INDÉTERMINÉ' })
    }
  })
  it('statut inconnu du backend → affiché tel quel, jamais masqué en silence', () => {
    const d = ticketDisplay(acc({ status: 'MARGIN_CALL_XYZ',
      next_ticket: { ...base.next_ticket, contracts: null, status: 'MARGIN_CALL_XYZ' } })) as
      { kind: 'REJECT'; label: string }
    expect(d.label).toBe('MARGIN_CALL_XYZ')
  })
})

describe('/devil — buffer > buffer_initial est LÉGITIME (journée profitable), pas une corruption', () => {
  it('borné à 100 % pour l\'affichage, sans casser le palier', () => {
    const profitable = acc({ current_equity: 50_600, day_pnl: 600, buffer: 1_600 })
    expect(bufferRatio(profitable)).toBe(1)
    expect(bufferTier(profitable)).toBe('SAFE')
  })
  it('buffer_initial négatif (corruption) → indéterminable, pas un ratio négatif', () => {
    expect(bufferRatio(acc({ buffer_initial: -1_000 }))).toBeNull()
    expect(bufferTier(acc({ buffer: 500, buffer_initial: -1_000 }))).toBe('UNKNOWN')
  })
})

describe('/devil — formatage des valeurs extrêmes (9-10 chiffres)', () => {
  it('compacte au-delà du seuil lisible pour ne pas déborder du panneau', () => {
    expect(usd(1_000_000_000)).toBe('1.00 G')
    expect(usd(50_000_000)).toBe('50.0 M')
    expect(usd(1_500_000)).toBe('1.50 M')
    expect(usd(999_999)).toBe('999,999')          // sous le seuil : chiffres exacts
  })
  it('compacte aussi les négatifs et garde le signe du P&L', () => {
    expect(usd(-50_000_000)).toBe('−50.0 M')
    expect(usdSigned(-1_200_000)).toBe('−1.20 M')
    expect(usdSigned(2_500_000)).toBe('+2.50 M')
  })
  it('les grandeurs non finies restent des tirets, même énormes', () => {
    expect(usd(Number.MAX_VALUE * 2)).toBe('·')   // Infinity
  })
})
