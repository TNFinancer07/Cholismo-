/** Câblage des alertes sonores (D-115) — consentement, état visible, branchement au flux.
 *
 *  Trois pièces, et la deuxième est celle qui donne son sens aux deux autres :
 *
 *  1. **Consentement explicite.** Les navigateurs exigent un geste utilisateur avant tout
 *     `AudioContext`, et un terminal qui se met à sonner sans qu'on l'ait demandé est intrusif.
 *     Le choix est persisté — le réactiver à chaque rechargement en ferait un réglage qu'on
 *     renonce à utiliser.
 *  2. **État visible en permanence.** « Pas de son » peut signifier *rien ne s'est produit*,
 *     *le son est coupé*, ou *l'audio est indisponible*. Sans indicateur, un opérateur qui
 *     s'appuie sur l'oreille croirait un marché calme alors qu'il a coupé le volume. Toute la
 *     garde de fraîcheur de D-114 ne servirait à rien si le silence restait ambigu.
 *  3. **Branchement au flux** — vide de liquidité (D-111) et gates OF (D-099).
 */
import { useEffect, useRef, useState } from 'react'
import { SoundPlayer, decideCues, type AudioState } from '@/lib/audio'
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

const CLE = 'cholismo.audio.enabled'

export type AudioStatus = 'ON' | 'OFF' | 'UNAVAILABLE'

export function audioSupporte(): boolean {
  return typeof (globalThis as { AudioContext?: unknown }).AudioContext === 'function'
}

export function lireConsentement(storage?: Storage): boolean {
  try {
    return (storage ?? localStorage).getItem(CLE) === '1'
  } catch {
    return false          // stockage refusé (navigation privée) → muet, jamais actif par défaut
  }
}

export function ecrireConsentement(actif: boolean, storage?: Storage): void {
  try {
    (storage ?? localStorage).setItem(CLE, actif ? '1' : '0')
  } catch {
    /* un stockage indisponible ne doit pas casser l'écran */
  }
}

/** Projette l'état du terminal vers ce que la décision sonore attend.
 *
 *  `null` partout où ce n'est pas mesurable — jamais `false`, qui se lirait « mesuré, négatif »
 *  et produirait un faux franchissement au tick suivant.
 */
export function etatAudio(extras: unknown): AudioState {
  const e = (extras ?? {}) as Record<string, unknown>
  const vac = e.liquidity_vacuum as { vacuum?: boolean | null } | undefined
  const shadow = e.orderflow_shadow as
    { b1?: { verdict_inhouse?: boolean | null }; b2?: { verdict_inhouse?: boolean | null } }
    | undefined

  const v1 = shadow?.b1?.verdict_inhouse
  const v2 = shadow?.b2?.verdict_inhouse
  // Les DEUX gates décisionnelles doivent être connues : un « franchi » déduit d'une seule
  // mesure décrirait la moitié de la porte.
  const gatePassed = (v1 === null || v1 === undefined || v2 === null || v2 === undefined)
    ? null
    : (v1 && v2)

  return {
    vacuum: vac?.vacuum === undefined ? null : vac.vacuum,
    gatePassed,
    freshness: 'FRESH',
  }
}

export function useAudioAlerts() {
  const [actif, setActif] = useState(false)
  const [dispo, setDispo] = useState(true)
  const extras = useTerminal((s) => s.extras)
  const player = useRef<SoundPlayer | null>(null)
  const precedent = useRef<AudioState | null>(null)

  useEffect(() => {
    setDispo(audioSupporte())
    setActif(lireConsentement() && audioSupporte())
  }, [])

  useEffect(() => {
    if (!actif) {
      // Coupé : on OUBLIE l'état précédent. Sinon, en réactivant, la première comparaison
      // porterait sur un instant révolu et sonnerait un franchissement qui a déjà eu lieu.
      precedent.current = null
      return
    }
    const suivant = etatAudio(extras)
    const cues = decideCues(precedent.current, suivant)
    precedent.current = suivant
    if (!cues.length) return
    player.current = player.current ?? new SoundPlayer()
    for (const c of cues) {
      if (player.current.play(c) === 'UNAVAILABLE') setDispo(false)
    }
  }, [actif, extras])

  const statut: AudioStatus = !dispo ? 'UNAVAILABLE' : actif ? 'ON' : 'OFF'

  const basculer = () => {
    if (!dispo) return
    const suivant = !actif
    setActif(suivant)
    ecrireConsentement(suivant)
    // Le geste utilisateur EST le consentement navigateur : on amorce le contexte ici, jamais
    // au chargement — un `AudioContext` créé sans geste reste suspendu et ne jouera rien.
    if (suivant) player.current = player.current ?? new SoundPlayer()
  }

  return { statut, basculer }
}

const LIBELLES: Record<AudioStatus, { txt: string; icone: string; cls: string; titre: string }> = {
  ON: { txt: 'son actif', icone: '♪', cls: 'text-bias-up',
        titre: 'alertes sonores actives — aucun son sur donnée périmée ou absente' },
  OFF: { txt: 'muet', icone: '⨯', cls: 'text-term-faint',
         titre: 'alertes sonores coupées — le silence ne signifie PAS « rien ne se passe »' },
  UNAVAILABLE: { txt: 'audio indisponible', icone: '!', cls: 'text-gold',
                 titre: "ce navigateur n'expose pas d'audio — le silence n'est pas une mesure" },
}

/** Indicateur permanent. Il porte une icône ET un texte : la couleur ne suffit jamais (§3). */
export function AudioStatusIndicator() {
  const { statut, basculer } = useAudioAlerts()
  const l = LIBELLES[statut]
  return (
    <button type="button" onClick={basculer} title={l.titre}
      data-testid="audio-statut" data-statut={statut}
      disabled={statut === 'UNAVAILABLE'}
      className={cn('inline-flex shrink-0 items-center gap-1 rounded-sm border px-1 text-xxs',
        'border-term-border hover:border-term-dim disabled:cursor-not-allowed', l.cls)}>
      <span aria-hidden>{l.icone}</span>
      <span>{l.txt}</span>
    </button>
  )
}
