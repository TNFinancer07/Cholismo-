/** Détachement de panneaux en fenêtres indépendantes (D-116).
 *
 *  ---
 *
 *  **Le danger propre au multi-fenêtre : une fenêtre détachée qui a perdu la synchronisation
 *  ressemble exactement à un marché calme.** Elle affiche des chiffres, ils sont lisibles, ils ne
 *  bougent plus. Sur un second moniteur regardé du coin de l'œil, rien ne le signale.
 *
 *  C'est le même défaut que la boucle morte qui ressemble à une boucle calme (D-073), transposé à
 *  l'écran. Toute fenêtre détachée porte donc l'ÂGE de sa dernière synchronisation, et bascule
 *  visiblement quand il grandit.
 *
 *  **Un seul flux SSE.** La fenêtre principale reste seule abonnée au backend et rediffuse par
 *  `BroadcastChannel`. Laisser chaque fenêtre ouvrir sa propre connexion doublerait la charge et,
 *  pire, laisserait deux fenêtres DIVERGER — deux vérités affichées côte à côte sur le même
 *  bureau.
 */

export const CHANNEL_NAME = 'cholismo.detach'
export const PANEL_PARAM = 'panel'

/** Au-delà, la fenêtre détachée cesse d'affirmer que ce qu'elle montre est courant. */
export const SYNC_STALE_MS = 3000
export const SYNC_LOST_MS = 10000

export type SyncStatus = 'LIVE' | 'STALE' | 'LOST' | 'UNKNOWN'

export interface DetachMessage {
  /** Instantané du store principal, tel quel — la fenêtre détachée ne recalcule rien. */
  payload: unknown
  /** Horodatage d'ÉMISSION. C'est lui qui datera l'affichage, pas l'heure de réception : une
   *  fenêtre qui daterait de sa propre réception se croirait à jour même sur un message vieux. */
  sentAt: number
}

/** Âge d'une synchronisation. `UNKNOWN` tant que rien n'est arrivé — jamais `LIVE` par défaut :
 *  une fenêtre qui vient de s'ouvrir n'a rien reçu, et l'affirmer serait un mensonge. */
export function syncStatus(lastAt: number | null | undefined, now: number,
                           staleMs = SYNC_STALE_MS, lostMs = SYNC_LOST_MS): SyncStatus {
  if (lastAt === null || lastAt === undefined || !Number.isFinite(lastAt)) return 'UNKNOWN'
  const age = now - lastAt
  // Un horodatage FUTUR signale une horloge incohérente entre fenêtres : on ne conclut pas.
  if (age < 0) return 'UNKNOWN'
  if (age >= lostMs) return 'LOST'
  if (age >= staleMs) return 'STALE'
  return 'LIVE'
}

export const SYNC_LABELS: Record<SyncStatus, { txt: string; cls: string; titre: string }> = {
  LIVE: { txt: 'synchronisé', cls: 'text-bias-up', titre: 'reçoit les mises à jour' },
  STALE: { txt: 'SYNC EN RETARD', cls: 'text-gold',
           titre: "aucune mise à jour récente — ce qui s'affiche peut ne plus être courant" },
  LOST: { txt: 'SYNC PERDUE', cls: 'text-bias-down',
          titre: 'plus aucune mise à jour — ces chiffres ne décrivent PLUS le marché' },
  UNKNOWN: { txt: 'en attente', cls: 'text-term-faint',
             titre: "rien n'a encore été reçu — ce n'est pas « à jour »" },
}

/** Enveloppe testable autour de `BroadcastChannel`. Absent (navigateur ancien, jsdom) → l'objet
 *  existe mais ne fait rien : le détachement se dégrade, il ne casse pas la fenêtre principale. */
export class DetachChannel {
  private ch: BroadcastChannel | null = null

  constructor(name: string = CHANNEL_NAME) {
    try {
      const Ctor = (globalThis as { BroadcastChannel?: typeof BroadcastChannel }).BroadcastChannel
      this.ch = Ctor ? new Ctor(name) : null
    } catch {
      this.ch = null
    }
  }

  get available(): boolean {
    return this.ch !== null
  }

  post(payload: unknown, now: number = Date.now()): boolean {
    if (!this.ch) return false
    try {
      this.ch.postMessage({ payload, sentAt: now } satisfies DetachMessage)
      return true
    } catch {
      // Un instantané non clonable ne doit pas tuer la boucle de rediffusion.
      return false
    }
  }

  subscribe(fn: (m: DetachMessage) => void): () => void {
    if (!this.ch) return () => {}
    const h = (e: MessageEvent) => {
      const d = e.data as DetachMessage | undefined
      if (d && typeof d.sentAt === 'number') fn(d)
    }
    this.ch.addEventListener('message', h)
    return () => this.ch?.removeEventListener('message', h)
  }

  close(): void {
    try { this.ch?.close() } catch { /* rien à faire */ }
    this.ch = null
  }
}

/** Identifiant de panneau demandé par l'URL, ou `null` si la fenêtre est la principale. */
export function detachedPanelId(search: string): string | null {
  try {
    const v = new URLSearchParams(search).get(PANEL_PARAM)
    return v && v.trim() ? v.trim() : null
  } catch {
    return null
  }
}

/** Ouvre un panneau dans une fenêtre indépendante. Rend `null` si le navigateur a bloqué la
 *  popup — l'appelant doit le DIRE, pas laisser croire que la fenêtre s'est ouverte ailleurs. */
export function openDetached(panelId: string, w = 520, h = 640): Window | null {
  try {
    const url = `${location.pathname}?${PANEL_PARAM}=${encodeURIComponent(panelId)}`
    return window.open(url, `cholismo_${panelId}`,
                       `width=${w},height=${h},menubar=no,toolbar=no`)
  } catch {
    return null
  }
}
