/** Tests RTL du panneau YLD (D-053) : ce que l'OPÉRATEUR lit à l'écran.
 *  Vérifié par le TEXTE et les unités, jamais par la couleur (§3). */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { YieldDifferentialsPanel } from './YieldDifferentialsPanel'
import { useTerminal } from '@/store/terminal'
import type { MetaField, YieldCurveValue, YieldSpread, YieldTenor } from '@/types/schema'

const tenor = (o: Partial<YieldTenor> = {}): YieldTenor => ({
  code: 'US10Y', label: 'US 10 ans', value_pct: 4.05, change_bp: -3.5, ...o,
})
const spread = (o: Partial<YieldSpread> = {}): YieldSpread => ({
  code: 'US10Y-US02Y', label: 'Pente US 10a−2a', value_bp: -20,
  long: 'US10Y', short: 'US02Y', inverted: true, ...o,
})

const mount = (o: Partial<YieldCurveValue> = {}, meta: Partial<MetaField<YieldCurveValue>> = {}) => {
  const value: YieldCurveValue = { tenors: [tenor()], spreads: [spread()], ...o }
  useTerminal.getState().set({
    yield_curve: {
      value, last_update_ts: Date.now() / 1000, source: 'rates_feed',
      freshness: 'FRESH', flags: [], ...meta,
    } as MetaField<YieldCurveValue>,
  })
  return render(<YieldDifferentialsPanel />)
}

// Canal lent déjà vivant par défaut (cf. panneau SENT) : l'absence testée est une vraie absence.
beforeEach(() => useTerminal.getState().set({
  yield_curve: null, lastSlowEventAt: Date.now() / 1000,
}))

describe('lecture des taux', () => {
  it('affiche le taux avec son unité et son libellé', () => {
    mount()
    const row = screen.getByTestId('yld-tenor-US10Y')
    expect(row).toHaveTextContent('US10Y')
    expect(row).toHaveTextContent('4,050')
    expect(row).toHaveTextContent('%')
  })

  it('marque le sens de la variation par une FLÈCHE et l\'unité bp (§3)', () => {
    mount()
    expect(screen.getByTestId('yld-tenor-US10Y')).toHaveTextContent('▼ 3,5 bp')
  })

  it('distingue « inchangé » (0 bp) d\'une variation ABSENTE (tiret)', () => {
    mount({ tenors: [tenor({ change_bp: 0 }), tenor({ code: 'US02Y', change_bp: null })] })
    expect(screen.getByTestId('yld-tenor-US10Y')).toHaveTextContent('= 0,0 bp')
    const missing = screen.getByTestId('yld-tenor-US02Y')
    expect(missing).toHaveTextContent('—')
    expect(missing).not.toHaveTextContent('0,0 bp')
  })

  it('accepte un taux négatif réel (Bund) sans le masquer', () => {
    mount({ tenors: [tenor({ code: 'DE10Y', value_pct: -0.55 })] })
    expect(screen.getByTestId('yld-tenor-DE10Y')).toHaveTextContent('-0,550')
  })
})

describe('différentiels', () => {
  it('affiche le spread SIGNÉ en points de base', () => {
    mount()
    expect(screen.getByTestId('yld-spread-US10Y-US02Y')).toHaveTextContent('−20,0')
    expect(screen.getByTestId('yld-spread-US10Y-US02Y')).toHaveTextContent('bp')
  })

  it('signe explicitement un écart positif', () => {
    mount({ spreads: [spread({ code: 'US10Y-DE10Y', value_bp: 170, inverted: null })] })
    expect(screen.getByTestId('yld-spread-US10Y-DE10Y')).toHaveTextContent('+170,0')
  })

  it('badge TEXTE « INVERSÉE » en plus de la couleur (§3)', () => {
    mount()
    expect(screen.getByTestId('yld-inverted-US10Y-US02Y')).toHaveTextContent('INVERSÉE')
  })

  it('n\'étiquette JAMAIS un différentiel inter-pays comme inversé', () => {
    mount({ spreads: [spread({ code: 'US10Y-DE10Y', value_bp: -35, inverted: null })] })
    expect(screen.queryByTestId('yld-inverted-US10Y-DE10Y')).toBeNull()
    expect(screen.getByTestId('yld-spread-US10Y-DE10Y')).toHaveTextContent('−35,0')
  })

  it('aucun badge sur une pente positive', () => {
    mount({ spreads: [spread({ value_bp: 42, inverted: false })] })
    expect(screen.queryByTestId('yld-inverted-US10Y-US02Y')).toBeNull()
  })
})

describe('pedigree de la donnée (/devil)', () => {
  it('affiche la SOURCE des taux : une erreur d\'unité ne se tranche pas sans elle', () => {
    mount()
    expect(screen.getByTestId('yld-source')).toHaveTextContent('rates_feed')
  })

  it('montre les drapeaux de pathologie même sur un bloc FRESH', () => {
    mount({}, { flags: ['CLOCK_DESYNC'] })
    expect(screen.getByLabelText(/Désynchronisation/)).toBeInTheDocument()
  })
})

describe('fail-closed (§3)', () => {
  it('dit explicitement qu\'aucun différentiel n\'est calculable au lieu d\'un blanc', () => {
    mount({ spreads: [] })
    expect(screen.getByTestId('yld-no-spread')).toHaveTextContent('AUCUN DIFFÉRENTIEL CALCULABLE')
    expect(screen.getByTestId('yld-tenor-US10Y')).toBeInTheDocument()   // les taux restent lisibles
  })

  it('affiche PAS DE DONNÉES quand le bloc est absent ET le canal vivant', () => {
    useTerminal.getState().set({ yield_curve: null, lastSlowEventAt: Date.now() / 1000 })
    render(<YieldDifferentialsPanel />)
    expect(screen.getByTestId('yld-offline')).toHaveTextContent('PAS DE DONNÉES')
  })

  it('distingue l\'ATTENTE du premier tick lent d\'une vraie absence (/polish)', () => {
    useTerminal.getState().set({ yield_curve: null, lastSlowEventAt: 0 })
    render(<YieldDifferentialsPanel />)
    expect(screen.getByTestId('yld-offline')).toHaveTextContent('EN ATTENTE DU CANAL LENT')
  })

  it('affiche PAS DE DONNÉES sur fraîcheur ABSENT, même si une valeur traîne', () => {
    mount({}, { freshness: 'ABSENT' })
    expect(screen.getByTestId('yld-offline')).toBeInTheDocument()
    expect(screen.queryByTestId('yld-tenor-US10Y')).toBeNull()
  })

  it('ne montre pas une courbe vide comme un panneau connecté', () => {
    mount({ tenors: [], spreads: [] })
    expect(screen.getByTestId('yld-offline')).toBeInTheDocument()
  })

  it('signale une courbe PÉRIMÉE sans la masquer', () => {
    mount({}, { freshness: 'STALE', last_update_ts: Date.now() / 1000 - 300 })
    expect(screen.getByTestId('yld-stale')).toHaveTextContent('PÉRIMÉ')
    expect(screen.getByTestId('yld-tenor-US10Y')).toBeInTheDocument()
  })
})
