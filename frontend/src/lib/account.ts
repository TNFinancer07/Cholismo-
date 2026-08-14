/** Dérivations d'affichage du bloc `account_state` (Zone C HUD, D-051) — PURES et testées.
 *
 *  Le backend fournit les grandeurs (équité, buffer, buffer_initial, ticket de référence) ;
 *  ce module en dérive ce que l'ŒIL doit lire : ratio de jauge, palier de sévérité, libellés.
 *  Aucune valeur n'est FABRIQUÉE : une grandeur absente reste absente (§3), et chaque palier
 *  porte un TEXTE + une ICÔNE en plus de sa couleur (§3 : jamais la couleur seule). */
import type { AccountStateBlock } from '@/types/schema'

export type BufferTier = 'SAFE' | 'CAUTION' | 'CRITICAL' | 'DEAD' | 'UNKNOWN'

/** Paliers de la spec : > 60 % sûr · 30–60 % prudence · < 30 % critique (clignotant) ·
 *  ≤ 0 buffer = MORT (bloqué). Données absentes → UNKNOWN, jamais un faux vert. */
export const BUFFER_CAUTION = 0.6
export const BUFFER_CRITICAL = 0.3

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** Ratio buffer restant / buffer à l'ouverture, borné [0,1]. `null` si indéterminable
 *  (grandeur absente, ouverture ≤ 0) — l'appelant affiche alors « inconnu », pas 0 %. */
export function bufferRatio(a: AccountStateBlock | null | undefined): number | null {
  if (a == null || !finite(a.buffer) || !finite(a.buffer_initial)) return null
  if (a.buffer_initial <= 0) return null
  return Math.max(0, Math.min(1, a.buffer / a.buffer_initial))
}

/** Palier de sévérité — DEAD dès que le buffer est à zéro ou négatif (le ratio n'y suffit pas :
 *  un buffer négatif borné à 0 donnerait « 0 % critique » au lieu de « mort »). */
export function bufferTier(a: AccountStateBlock | null | undefined): BufferTier {
  if (a == null || !finite(a.buffer)) return 'UNKNOWN'
  if (a.buffer <= 0) return 'DEAD'
  const r = bufferRatio(a)
  if (r == null) return 'UNKNOWN'
  if (r > BUFFER_CAUTION) return 'SAFE'
  if (r >= BUFFER_CRITICAL) return 'CAUTION'
  return 'CRITICAL'
}

export interface TierStyle {
  /** Libellé TEXTE — porte le sens sans la couleur (§3). */
  label: string
  icon: string
  bar: string
  text: string
  /** Clignotement réservé au palier critique (la spec : « rouge clignotant < 30 % »). */
  blink: boolean
}

export const TIER_STYLE: Record<BufferTier, TierStyle> = {
  SAFE: { label: 'MARGE SAINE', icon: '●', bar: 'bg-risk-green', text: 'text-risk-green', blink: false },
  CAUTION: { label: 'MARGE RÉDUITE', icon: '▲', bar: 'bg-risk-yellow', text: 'text-risk-yellow', blink: false },
  CRITICAL: { label: 'MARGE CRITIQUE', icon: '⚠', bar: 'bg-risk-red', text: 'text-risk-red', blink: true },
  DEAD: { label: 'BLOQUÉ', icon: '⛔', bar: 'bg-risk-red', text: 'text-risk-red', blink: false },
  UNKNOWN: { label: 'INCONNU', icon: '?', bar: 'bg-stale', text: 'text-stale', blink: false },
}

/** Le compte est-il exploitable ? `DISCONNECTED`/`is_stale` → l'UI demande la connectivité NT8
 *  et n'affiche AUCUNE grandeur (fail-closed §3). */
export function isLive(a: AccountStateBlock | null | undefined): boolean {
  return a != null && a.status !== 'DISCONNECTED' && a.is_stale === false
}

/** Libellés FR des statuts de rejet du RiskSizer — chacun dit quoi faire, pas juste « erreur ». */
export const STATUS_LABEL: Record<string, string> = {
  APPROVED: 'DIMENSIONNÉ',
  INSUFFICIENT_BUFFER: 'MARGE INSUFFISANTE',
  INVALID_INPUT: 'DONNÉES COMPTE INVALIDES',
  SIZE_SANITY_CAP: 'TAILLE INVRAISEMBLABLE',
  DISCONNECTED: 'CONNECTIVITÉ NT8 REQUISE',
}

/** Au-delà du million, les chiffres exacts DÉBORDENT du panneau (/devil) : on compacte plutôt
 *  que de tronquer — « 1.00 G » reste lisible et vrai, « 1,000,00… » serait un mensonge. */
const MILLION = 1_000_000
const GIGA = 1_000_000_000

/** Montant en USD, jamais un faux zéro : absent/non fini → tiret neutre. Compacté au-delà du
 *  million pour tenir dans la largeur du panneau (§ lisibilité > décoration). */
export function usd(v: number | null | undefined, digits = 0): string {
  if (!finite(v)) return '·'
  const abs = Math.abs(v)
  const sign = v < 0 ? '−' : ''
  if (abs >= GIGA) return `${sign}${(abs / GIGA).toFixed(2)} G`
  if (abs >= MILLION) return `${sign}${(abs / MILLION).toFixed(2).slice(0, 4)} M`
  return sign + abs.toLocaleString('en-US', { minimumFractionDigits: digits,
    maximumFractionDigits: digits })
}

/** Montant SIGNÉ (P&L du jour) — le signe est explicite, y compris pour un gain. */
export function usdSigned(v: number | null | undefined, digits = 0): string {
  if (!finite(v)) return '·'
  return (v > 0 ? '+' : '') + usd(v, digits)
}

export type TicketDisplay =
  | { kind: 'SIZE'; contracts: number }
  | { kind: 'REJECT'; label: string }

/** Ce que le bloc « prochain ticket » doit AFFICHER — la garde la plus importante du panneau.
 *
 *  Une taille ne s'affiche QUE si le sizer l'a APPROUVÉE **des deux côtés** (statut du bloc ET
 *  statut du ticket) et que les contrats sont un entier > 0. Sans cette double condition, un
 *  payload CONTRADICTOIRE (`contracts: 26` + `status: INSUFFICIENT_BUFFER`, trouvé au /devil)
 *  afficherait une taille que le RiskSizer a refusée — le pire mensonge possible ici.
 *  Ticket absent, contrats non entiers/nuls/négatifs → `INDÉTERMINÉ` : on n'invente rien (§3).
 *  Un statut inconnu du backend est affiché TEL QUEL, jamais masqué en silence. */
export function ticketDisplay(a: AccountStateBlock | null | undefined): TicketDisplay {
  const t = a?.next_ticket
  if (a == null || t == null) return { kind: 'REJECT', label: 'INDÉTERMINÉ' }
  const approved = a.status === 'APPROVED' && t.status === 'APPROVED'
  const n = t.contracts
  if (approved && typeof n === 'number' && Number.isInteger(n) && n > 0) {
    return { kind: 'SIZE', contracts: n }
  }
  if (!approved) {
    const worst = a.status !== 'APPROVED' ? a.status : t.status
    return { kind: 'REJECT', label: STATUS_LABEL[worst] ?? worst }
  }
  return { kind: 'REJECT', label: 'INDÉTERMINÉ' }   // APPROVED mais taille inexploitable
}
