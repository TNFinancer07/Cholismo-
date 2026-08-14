/** Gates d'order flow OF1-OF4 (D-099).
 *
 *  Ce qui est vérifié n'est pas « ça s'affiche » mais les trois choses qui, mal faites, feraient
 *  mentir l'écran : une mesure absente rendue comme un 0, un verdict absent lu comme « passe »,
 *  et des mesures non gatantes présentées à côté des décisionnelles sans distinction.
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { OrderFlowGatesPanel, OrderFlowMeasuresPanel, fmtMesure, verdictTexte } from './OrderFlowGatesPanel'
import { useTerminal } from '@/store/terminal'
import type { Extras, OrderFlowShadow } from '@/types/schema'

const COMPLET: OrderFlowShadow = {
  resume: 'accord : les deux sources concluent pareil',
  source: 'inhouse',
  b1: { source: true, inhouse: 0.72, verdict_source: true, verdict_inhouse: true, agree: true },
  b2: { source: 0.66, inhouse: 0.71, verdict_source: true, verdict_inhouse: true, agree: true,
        delta: 0.05 },
  b3: 0.41,
  b4: 1.28,
  missing: [],
}

function poser(shadow: OrderFlowShadow | null) {
  useTerminal.getState().set({ extras: { orderflow_shadow: shadow } as unknown as Extras })
}

beforeEach(() => useTerminal.getState().set({ extras: null }))

// ------------------------------------------------------------------ fail-closed

describe('mesure absente', () => {
  it.each([
    ['null', null],
    ['undefined', undefined],
    ['NaN', NaN],
    ['Infinity', Infinity],
  ])('%s ne devient JAMAIS un 0', (_nom, v) => {
    expect(fmtMesure(v as number | null | undefined)).toBe('—')
  })

  it('un 0 réel reste un 0 — sinon on effacerait une mesure', () => {
    expect(fmtMesure(0)).toBe('0')
  })
})

describe('verdict absent', () => {
  it('ne se lit pas « franchie »', () => {
    const v = verdictTexte(null)
    expect(v.txt).toBe('non mesurable')
    expect(v.txt).not.toContain('franchie')
  })

  it('porte une icône en plus de la couleur (§3, daltonisme)', () => {
    expect(verdictTexte(true).icone).toBe('✓')
    expect(verdictTexte(false).icone).toBe('✕')
    expect(verdictTexte(true).cls).not.toBe(verdictTexte(false).cls)
  })
})

// ------------------------------------------------------------------ OF1 / OF2

describe('panneau décisionnel', () => {
  it('sans observation, dit qu\'il n\'y en a pas', () => {
    render(<OrderFlowGatesPanel />)
    expect(screen.getByText(/aucune observation publiée/)).toBeTruthy()
  })

  it('affiche le résumé lisible du backend en tête', () => {
    poser(COMPLET)
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-resume').textContent).toContain('accord')
  })

  it('montre OF1 et OF2, jamais B1/B2 — la collision de codes est le point', () => {
    poser(COMPLET)
    const { container } = render(<OrderFlowGatesPanel />)
    expect(screen.getByText('OF1')).toBeTruthy()
    expect(screen.getByText('OF2')).toBeTruthy()
    expect(container.textContent).not.toMatch(/\bB1\b/)
  })

  it('un DÉSACCORD est affiché comme tel, pas noyé', () => {
    poser({ ...COMPLET, b1: { ...COMPLET.b1!, verdict_inhouse: false, agree: false } })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByText('DÉSACCORD')).toBeTruthy()
  })

  it('`agree` à null se lit « indécidable », pas « accord »', () => {
    poser({ ...COMPLET,
            b1: { source: null, inhouse: null, verdict_source: null, verdict_inhouse: null,
                  agree: null } })
    render(<OrderFlowGatesPanel />)
    expect(screen.getAllByText('indécidable').length).toBeGreaterThan(0)
  })

  it('survit à la branche d\'ERREUR du backend (resume + source seuls)', () => {
    poser({ resume: 'comparaison non mesurable (erreur d\'observation)', source: 'inhouse' })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-resume').textContent).toContain('non mesurable')
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('liste ce qui n\'a pas pu être mesuré', () => {
    poser({ ...COMPLET, missing: ['tape', 'carnet'] })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-missing').textContent).toContain('tape')
  })
})

// ------------------------------------------------------------------ OF3 / OF4

describe('panneau de mesures', () => {
  it('avertit qu\'elles n\'entrent dans AUCUNE décision', () => {
    poser(COMPLET)
    render(<OrderFlowMeasuresPanel />)
    expect(screen.getByTestId('of-mesures-avertissement').textContent).toMatch(/non calibrés/i)
  })

  it('affiche les valeurs mesurées', () => {
    poser(COMPLET)
    render(<OrderFlowMeasuresPanel />)
    expect(screen.getByTestId('of-b3').textContent).toBe('0.41')
    expect(screen.getByTestId('of-b4').textContent).toBe('1.28')
  })

  it('une mesure absente reste « — »', () => {
    poser({ ...COMPLET, b3: null, b4: undefined })
    render(<OrderFlowMeasuresPanel />)
    expect(screen.getByTestId('of-b3').textContent).toBe('—')
    expect(screen.getByTestId('of-b4').textContent).toBe('—')
  })

  it('ne porte AUCUN verdict — c\'est ce qui le distingue du panneau décisionnel', () => {
    poser(COMPLET)
    const { container } = render(<OrderFlowMeasuresPanel />)
    expect(container.textContent).not.toMatch(/franchie|refusée|DÉSACCORD/)
  })
})

// ------------------------------------------------------------------ seuils (D-101)

const SEUILS = {
  instrument: 'MES',
  b1: { value: 0.4, op: '>=' as const, applied: true },
  b2: { value: 0.4, op: '<=' as const, applied: true },   // ASK_SWEEP : le sens s'inverse
  b3: { value: 0.3, op: '>=' as const, applied: false },
  b4: { value: 0.3, op: '<=' as const, applied: false },
}

describe('repères de seuil', () => {
  it('affiche l\'OPÉRATEUR avec la valeur — « 0.4 » seul ne dit pas de quel côté être', () => {
    poser({ ...COMPLET, thresholds: SEUILS })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-seuil-OF1').textContent).toContain('>=')
    expect(screen.getByTestId('of-seuil-OF1').textContent).toContain('0.4')
  })

  it('rend le seuil B2 DIRECTIONNEL tel que publié, sans le recalculer', () => {
    poser({ ...COMPLET, thresholds: SEUILS })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-seuil-OF2').textContent).toContain('<=')
  })

  it('marque « réf. » les seuils NON appliqués', () => {
    poser({ ...COMPLET, thresholds: SEUILS })
    render(<OrderFlowMeasuresPanel />)
    expect(screen.getByTestId('of-seuil-OF3').textContent).toContain('réf.')
    expect(screen.getByTestId('of-seuil-OF4').textContent).toContain('réf.')
  })

  it('un seuil ABSENT reste « — », jamais un seuil supposé', () => {
    poser({ ...COMPLET, thresholds: null })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-seuil-OF1').textContent).toBe('—')
  })

  it('B2 sans direction de sweep n\'affiche AUCUN repère', () => {
    poser({ ...COMPLET, thresholds: { ...SEUILS, b2: null } })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-seuil-OF2').textContent).toBe('—')
  })

  it('aucun seuil n\'est écrit en dur dans le composant', () => {
    /* Le point de la tranche : une copie divergerait en silence à la recalibration. */
    poser({ ...COMPLET, thresholds: { ...SEUILS, b1: { value: 0.99, op: '>=', applied: true } } })
    render(<OrderFlowGatesPanel />)
    expect(screen.getByTestId('of-seuil-OF1').textContent).toContain('0.99')
  })
})
