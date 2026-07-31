/** Tests RTL du panneau SENT (D-053) : ce que l'OPÉRATEUR voit à l'écran.
 *  Tout est vérifié par le TEXTE et la géométrie — jamais par la couleur (§3), puisque c'est
 *  précisément la propriété qu'on veut garantir. */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { LsrSentimentPanel } from './LsrSentimentPanel'
import { useTerminal } from '@/store/terminal'
import type { LongShortInstrument, LongShortValue, MetaField } from '@/types/schema'

const inst = (o: Partial<LongShortInstrument> = {}): LongShortInstrument => ({
  symbol: 'EURUSD', long_pct: 60, short_pct: 40, ratio: 1.5,
  delta_24h_pct: 1.5, accounts: 12_000, imbalanced: false, ...o,
})

const block = (o: Partial<LongShortValue> = {}, meta: Partial<MetaField<LongShortValue>> = {}) => {
  const value: LongShortValue = {
    venue: 'retail_ssi', instruments: [inst()], dropped: 0, extreme_pct: 75, ...o,
  }
  useTerminal.getState().set({
    long_short_ratio: {
      value, last_update_ts: Date.now() / 1000, source: 'sentiment_feed',
      freshness: 'FRESH', flags: [], ...meta,
    } as MetaField<LongShortValue>,
  })
  return render(<LsrSentimentPanel />)
}

beforeEach(() => useTerminal.getState().set({ long_short_ratio: null }))

describe('jauge', () => {
  it('montre les deux côtés en TEXTE, pas seulement en couleur (§3)', () => {
    block()
    // Depuis le /devil, les chiffres sont HORS des bandes (la géométrie ne porte plus de texte) :
    // la propriété testée est la même, l'ancrage change.
    expect(screen.getByTestId('ls-pct-long-EURUSD')).toHaveTextContent('LONG 60,0')
    expect(screen.getByTestId('ls-pct-short-EURUSD')).toHaveTextContent('40,0 SHORT')
  })

  it('donne à la barre LONG une largeur égale au pourcentage', () => {
    block({ instruments: [inst({ long_pct: 82, short_pct: 18, ratio: 4.56 })] })
    expect(screen.getByTestId('ls-bar-long-EURUSD')).toHaveStyle({ width: '82%' })
  })

  it('reste lisible par un lecteur d\'écran (libellé complet)', () => {
    block()
    expect(screen.getByRole('img', { name: /60,0 % long, 40,0 % short/ })).toBeInTheDocument()
  })
})

describe('géométrie de la jauge (/devil)', () => {
  // Mesuré en navigateur AVANT correctif : à 100/0 la jauge affichait 93,7 % de long — la
  // largeur minimale des libellés placés DANS les bandes déformait la géométrie. Une bande de
  // 0 % visible est un mensonge quantitatif, dans le régime exact où le panneau sert.
  it('donne à chaque bande une largeur EXACTEMENT égale à sa part', () => {
    block({ instruments: [inst({ long_pct: 60, short_pct: 40 })] })
    expect(screen.getByTestId('ls-bar-long-EURUSD')).toHaveStyle({ width: '60%' })
    expect(screen.getByTestId('ls-bar-short-EURUSD')).toHaveStyle({ width: '40%' })
  })

  it('rend une bande de 0 % STRICTEMENT invisible', () => {
    block({ instruments: [inst({ long_pct: 100, short_pct: 0, ratio: null })] })
    expect(screen.getByTestId('ls-bar-long-EURUSD')).toHaveStyle({ width: '100%' })
    expect(screen.getByTestId('ls-bar-short-EURUSD')).toHaveStyle({ width: '0%' })
  })

  it('ne met AUCUN texte dans les bandes : la géométrie ne doit rien porter', () => {
    block({ instruments: [inst({ long_pct: 98, short_pct: 2, ratio: 49 })] })
    expect(screen.getByTestId('ls-bar-long-EURUSD').textContent).toBe('')
    expect(screen.getByTestId('ls-bar-short-EURUSD').textContent).toBe('')
  })

  it('garde les pourcentages LISIBLES hors de la jauge (§3 préservé)', () => {
    block({ instruments: [inst({ long_pct: 98, short_pct: 2, ratio: 49 })] })
    expect(screen.getByTestId('ls-pct-long-EURUSD')).toHaveTextContent('98,0')
    expect(screen.getByTestId('ls-pct-short-EURUSD')).toHaveTextContent('2,0')
  })
})

describe('pedigree de la donnée (/devil)', () => {
  it('montre les drapeaux de pathologie même sur un bloc FRESH', () => {
    block({}, { flags: ['LATE_FEED'] })
    expect(screen.getByLabelText('Flux en retard')).toBeInTheDocument()
  })

  it('affiche la venue : sans elle, impossible de trancher une donnée douteuse', () => {
    block({ venue: 'retail_ssi' })
    expect(screen.getByTestId('ls-venue')).toHaveTextContent('retail_ssi')
  })
})

describe('honnêteté des valeurs', () => {
  it('affiche N/D quand le ratio est indéterminable, jamais « ∞ »', () => {
    block({ instruments: [inst({ long_pct: 100, short_pct: 0, ratio: null })] })
    expect(screen.getByTestId('ls-ratio-EURUSD')).toHaveTextContent('N/D')
    expect(screen.queryByText('∞')).toBeNull()
    // …mais les pourcentages, eux, restent affichés : ce SONT des données réelles.
    expect(screen.getByTestId('ls-pct-long-EURUSD')).toHaveTextContent('100,0')
  })

  it('remplace une variation 24 h absente par un tiret, pas par 0', () => {
    block({ instruments: [inst({ delta_24h_pct: null })] })
    const row = screen.getByTestId('ls-row-EURUSD')
    expect(row).toHaveTextContent('—')
    expect(row).not.toHaveTextContent('0,0 pt')
  })

  it('marque le sens de la variation par une FLÈCHE en plus de la couleur (§3)', () => {
    block({ instruments: [inst({ delta_24h_pct: -3.2 })] })
    expect(screen.getByTestId('ls-row-EURUSD')).toHaveTextContent('▼ 3,2 pt')
  })

  it('rend visibles les lignes écartées par le moteur', () => {
    block({ dropped: 2 })
    expect(screen.getByTestId('ls-dropped')).toHaveTextContent('2 lignes écartées')
  })

  it('ne montre rien quand aucune ligne n\'a été écartée', () => {
    block({ dropped: 0 })
    expect(screen.queryByTestId('ls-dropped')).toBeNull()
  })
})

describe('déséquilibre', () => {
  it('badge TEXTE au-delà du seuil, pas une simple teinte', () => {
    block({ instruments: [inst({ long_pct: 88, short_pct: 12, imbalanced: true })] })
    expect(screen.getByTestId('ls-imbalance-EURUSD')).toHaveTextContent('DÉSÉQUILIBRE')
  })

  it('aucun badge en positionnement équilibré', () => {
    block()
    expect(screen.queryByTestId('ls-imbalance-EURUSD')).toBeNull()
  })

  it('rappelle le seuil affiché pour que le badge soit interprétable', () => {
    block({ extreme_pct: 75 })
    expect(screen.getByText(/déséquilibre ≥ 75 %/)).toBeInTheDocument()
  })
})

describe('fail-closed (§3)', () => {
  it('affiche PAS DE DONNÉES quand le bloc est absent', () => {
    useTerminal.getState().set({ long_short_ratio: null })
    render(<LsrSentimentPanel />)
    expect(screen.getByTestId('ls-offline')).toHaveTextContent('PAS DE DONNÉES')
  })

  it('affiche PAS DE DONNÉES quand la fraîcheur est ABSENT, même si une valeur traîne', () => {
    block({}, { freshness: 'ABSENT' })
    expect(screen.getByTestId('ls-offline')).toBeInTheDocument()
    expect(screen.queryByTestId('ls-row-EURUSD')).toBeNull()
  })

  it('ne montre PAS une liste vide comme un panneau connecté', () => {
    block({ instruments: [] })
    expect(screen.getByTestId('ls-offline')).toBeInTheDocument()
  })

  it('signale explicitement un positionnement PÉRIMÉ sans le masquer', () => {
    block({}, { freshness: 'STALE', last_update_ts: Date.now() / 1000 - 120 })
    expect(screen.getByTestId('ls-stale')).toHaveTextContent('PÉRIMÉ')
    expect(screen.getByTestId('ls-row-EURUSD')).toBeInTheDocument()   // la donnée reste lisible
  })
})
