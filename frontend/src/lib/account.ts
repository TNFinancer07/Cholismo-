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

/** Montant en USD, jamais un faux zéro : absent → tiret neutre. */
export function usd(v: number | null | undefined, digits = 0): string {
  if (!finite(v)) return '·'
  return v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** Montant SIGNÉ (P&L du jour) — le signe est explicite, y compris pour un gain. */
export function usdSigned(v: number | null | undefined, digits = 0): string {
  if (!finite(v)) return '·'
  return (v > 0 ? '+' : v < 0 ? '−' : '') + usd(Math.abs(v), digits)
}
