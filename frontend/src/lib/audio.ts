/** Alertes sonores — la DÉCISION, séparée du son (D-114).
 *
 *  Ce module ne joue rien : il décide s'il y a lieu de jouer, et quoi. La partie pure est
 *  testable ; le `AudioContext` ne l'est pas, et les mêler rendrait la règle invérifiable.
 *
 *  ---
 *
 *  **Aucun son sur donnée périmée ou absente.** La règle qui prime sur toutes les autres. Un son
 *  est une affirmation : « ceci vient de se produire ». Le déclencher sur une valeur `STALE`
 *  affirmerait un événement à partir d'une mesure d'un autre instant — et l'opérateur, qui écoute
 *  précisément pour ne PAS regarder l'écran, n'aurait aucun moyen de s'en apercevoir.
 *
 *  **Un franchissement demande DEUX états connus.** Sans valeur précédente fraîche, il n'y a pas
 *  de franchissement observable — seulement une valeur. Traiter « inconnu → au-dessus » comme un
 *  franchissement produirait un son à chaque reconnexion, c'est-à-dire au pire moment.
 *
 *  **Le silence est ambigu, donc il s'annonce.** « Pas de son » peut signifier « rien ne s'est
 *  produit » ou « le son est coupé ». L'écran doit dire lequel — sans quoi un opérateur qui
 *  s'appuie sur l'oreille croirait un marché calme alors qu'il a coupé le volume.
 */

export type CueKind =
  | 'PROTECTION_REJECT'   // un verrou vient d'écarter un setup
  | 'LIQUIDITY_VACUUM'    // le carnet se vide — slippage accru probable
  | 'OF_GATE_PASSED'      // une gate décisionnelle vient d'être franchie
  | 'OF_GATE_FAILED'      // …ou de basculer au refus

export interface SoundCue {
  kind: CueKind
  /** Hertz. Grave = lourd (absorption, refus) ; aigu = rapide (accélération, franchissement).
   *  Le mappage suit l'intuition psycho-acoustique : on n'apprend pas un code arbitraire. */
  frequency: number
  durationMs: number
  label: string
}

const CUES: Record<CueKind, Omit<SoundCue, 'kind'>> = {
  PROTECTION_REJECT: { frequency: 160, durationMs: 260, label: 'setup écarté par un verrou' },
  LIQUIDITY_VACUUM: { frequency: 220, durationMs: 420, label: 'carnet qui se vide' },
  OF_GATE_FAILED: { frequency: 300, durationMs: 180, label: 'gate order flow refusée' },
  OF_GATE_PASSED: { frequency: 660, durationMs: 140, label: 'gate order flow franchie' },
}

export function cue(kind: CueKind): SoundCue {
  return { kind, ...CUES[kind] }
}

/** Ce qu'on sait d'un instant. `null` = non mesurable — jamais `false`, qui se lirait
 *  « mesuré, et négatif ». */
export interface AudioState {
  vacuum: boolean | null
  gatePassed: boolean | null
  /** Fraîcheur de la source. Tout ce qui n'est pas `FRESH` interdit le son. */
  freshness?: string | null
}

function mesurable(s: AudioState | null | undefined): s is AudioState {
  if (!s) return false
  return s.freshness === undefined || s.freshness === null || s.freshness === 'FRESH'
}

/** Sons à jouer pour la transition `prev → next`. Tableau vide = rien à dire.
 *
 *  Les deux états doivent être mesurables : sinon on ne compare pas deux instants, on compare un
 *  instant à une ignorance.
 */
export function decideCues(prev: AudioState | null | undefined,
                          next: AudioState | null | undefined): SoundCue[] {
  if (!mesurable(prev) || !mesurable(next)) return []
  const out: SoundCue[] = []
  if (prev.vacuum === false && next.vacuum === true) out.push(cue('LIQUIDITY_VACUUM'))
  if (prev.gatePassed === false && next.gatePassed === true) out.push(cue('OF_GATE_PASSED'))
  if (prev.gatePassed === true && next.gatePassed === false) out.push(cue('OF_GATE_FAILED'))
  return out
}

export type PlayResult = 'PLAYED' | 'THROTTLED' | 'UNAVAILABLE'

/** Émetteur. Isolé pour que la décision reste testable sans navigateur. */
export class SoundPlayer {
  private ctx: AudioContext | null = null
  private lastAt = new Map<CueKind, number>()

  constructor(private readonly minGapMs = 3000,
              private readonly now: () => number = () => Date.now()) {}

  /** Trois issues DISTINCTES, parce qu'un silence n'a pas une seule cause :
   *  - `PLAYED` — émis ;
   *  - `THROTTLED` — étouffé par l'anti-répétition (un même événement qui sonne cinq fois cesse
   *    d'être une information) ;
   *  - `UNAVAILABLE` — pas d'audio dans cet environnement.
   *
   *  Les confondre en un booléen empêcherait l'écran de dire à l'opérateur que son canal
   *  d'alerte est MUET — or celui qui écoute pour ne pas regarder doit le savoir. */
  play(c: SoundCue): PlayResult {
    const Ctor = (globalThis as { AudioContext?: typeof AudioContext }).AudioContext
    if (!Ctor) return 'UNAVAILABLE'
    const t = this.now()
    const last = this.lastAt.get(c.kind)
    if (last !== undefined && t - last < this.minGapMs) return 'THROTTLED'
    this.lastAt.set(c.kind, t)
    try {
      this.ctx = this.ctx ?? new Ctor()
      const osc = this.ctx.createOscillator()
      const gain = this.ctx.createGain()
      osc.frequency.value = c.frequency
      osc.type = c.frequency < 300 ? 'sine' : 'triangle'
      gain.gain.value = 0.06                       // discret : un terminal n'est pas une alarme
      osc.connect(gain).connect(this.ctx.destination)
      osc.start()
      osc.stop(this.ctx.currentTime + c.durationMs / 1000)
      return 'PLAYED'
    } catch {
      // Un son qui échoue ne doit RIEN casser — l'audio est un confort, pas un canal de décision.
      return 'UNAVAILABLE'
    }
  }
}
