/** Store de l'alerte TradeManifest (D-045 tranche 2) — HORS ContextSchema (contrat-pont LSR,
 *  exception documentée D-045), donc hors du store terminal.
 *
 *  **Dérive d'horloge — la règle.** Le frontend ne compare JAMAIS le `timestamp` backend à son
 *  propre `Date.now()` : deux machines, deux horloges, la dérive rendrait le TTL faux dans les
 *  deux sens (ticket mort-né ou zombie). Le compte à rebours démarre à la RÉCEPTION de
 *  l'événement, sur `performance.now()` — horloge MONOTONE locale, insensible aux sauts NTP.
 *  Le `timestamp` backend reste une donnée d'affichage, pas une base de calcul.
 *
 *  **Lock UI.** `lock()` ne transitionne qu'ARMED → LOCKED, une seule fois — c'est la garde
 *  STRUCTURELLE contre le double envoi : quoi que fasse le clavier, il n'existe qu'une
 *  transition. Une fois LOCKED, l'alerte est figée jusqu'à la fin du TTL.
 *
 *  FAIL-CLOSED (§3) :
 *  - manifeste malformé (champ manquant, prix non fini, direction inconnue, TTL ≤ 0, géométrie
 *    incohérente) → IGNORÉ silencieusement — jamais un ticket dégradé à l'écran ;
 *  - un manifeste reçu pendant qu'une alerte est affichée → STRICT DROP, pas de file LIFO/FIFO
 *    (anti-substitution ; en microstructure on ne trade pas le passé — setup raté = on attend
 *    le prochain) ;
 *  - MORT-NÉ : un manifeste dont le transit réseau a déjà consommé le TTL (âge corrigé de
 *    l'offset d'horloge mesuré ≥ TTL) est jeté AVANT tout rendu — 0 frame affichée ;
 *  - GEL DE THREAD : `lock()` re-vérifie l'échéance au moment de l'action — une touche restée
 *    en file pendant un gel du thread principal ne peut pas valider un ticket mort ;
 *  - §2.1 : valider ENREGISTRE la décision (event store append-only, avec temps de réaction),
 *    rien ici ne parle à un courtier. */
import { create } from 'zustand'
import { api } from '@/lib/api'
import { useTerminal } from '@/store/terminal'
import type { TradeManifest } from '@/types/trade_manifest'

export type AlertStatus = 'ARMED' | 'LOCKED'

export interface ManifestAlert {
  manifest: TradeManifest
  /** `performance.now()` à la réception SSE — seule base du compte à rebours (jamais l'horloge backend). */
  receivedAtMs: number
  status: AlertStatus
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** Garde de réception : le backend garantit déjà tout ça (D-045), mais la frontière re-vérifie —
 *  on ne fait pas confiance à l'amont (même règle que côté Python). */
export function isValidManifest(raw: unknown): raw is TradeManifest {
  if (typeof raw !== 'object' || raw === null) return false
  const m = raw as Record<string, unknown>
  const entry = m.entry as Record<string, unknown> | null | undefined
  const risk = m.risk as Record<string, unknown> | null | undefined
  if (typeof entry !== 'object' || entry === null) return false
  if (typeof risk !== 'object' || risk === null) return false
  if (typeof m.id !== 'string' || m.id.length === 0) return false
  if (typeof m.instrument !== 'string' || m.instrument.length === 0) return false
  if (m.direction !== 'BUY' && m.direction !== 'SELL') return false
  if (typeof m.reason !== 'string') return false
  if (!finite(m.timestamp)) return false
  if (entry.type !== 'LIMIT' && entry.type !== 'MARKET') return false
  if (!finite(entry.price)) return false
  if (!finite(risk.stopLoss) || !finite(risk.takeProfit)) return false
  if (!(typeof risk.positionSize === 'number' && Number.isInteger(risk.positionSize) && risk.positionSize > 0)) return false
  if (!finite(m.timeToLiveMs) || m.timeToLiveMs <= 0) return false
  // géométrie : le stop protège, l'objectif est devant — sinon le ticket ment
  const e = entry.price, sl = risk.stopLoss, tp = risk.takeProfit
  return m.direction === 'BUY' ? sl < e && e < tp : tp < e && e < sl
}

export type ManifestOutcome = 'ACK' | 'REJECT_USER' | 'TIMEOUT'

/** Journalise l'issue dans l'event store (append-only, D-045) — tir SANS attente : l'UI ne bloque
 *  jamais sur le réseau. `reaction_time_ms` (affichage → action humaine) est la mesure VITALE de
 *  la performance d'exécution post-session ; TIMEOUT n'en porte jamais (aucune action humaine,
 *  on n'invente pas une latence §3). Échec réseau → `lastError` (visible), jamais silencieux. */
function journalize(m: TradeManifest, outcome: ManifestOutcome, reactionMs: number | null): void {
  api.postManifestOutcome({
    manifest_id: m.id, instrument: m.instrument, direction: m.direction,
    outcome, reaction_time_ms: reactionMs, time_to_live_ms: m.timeToLiveMs,
    operator: useTerminal.getState().operator,
  }).catch((err: Error) => {
    useTerminal.getState().set({ lastError: `journal manifeste : ${err.message}` })
  })
}

interface ManifestStore {
  alert: ManifestAlert | null
  /** Traçabilité post-démontage + gardes observables dans les essais. */
  lastLockedId: string | null
  lockCount: number
  lastOutcome: ManifestOutcome | null
  push: (raw: unknown) => void
  lock: () => void
  resolve: (outcome: 'REJECT_USER' | 'TIMEOUT') => void
  clear: () => void
}

/** Âge apparent du manifeste à la réception, corrigé de l'offset d'horloge MESURÉ
 *  (`clockOffset` = server_ts − client_ts, entretenu par session_identity sur le canal rapide).
 *  Ce n'est PAS une comparaison naïve backend vs Date.now() : l'offset neutralise la dérive
 *  entre machines ; ce qui reste est le temps de TRANSIT réseau. */
function transitAgeMs(m: TradeManifest): number {
  return Date.now() + useTerminal.getState().clockOffset * 1000 - m.timestamp
}

const expired = (a: ManifestAlert): boolean =>
  performance.now() - a.receivedAtMs >= a.manifest.timeToLiveMs

export const useManifest = create<ManifestStore>((set, get) => ({
  alert: null,
  lastLockedId: null,
  lockCount: 0,
  lastOutcome: null,
  push: (raw) => {
    if (get().alert !== null) return          // STRICT DROP — pas de file : on ne trade pas le passé
    if (!isValidManifest(raw)) return         // fail-closed — rien plutôt qu'un ticket dégradé
    // MORT-NÉ : plus de temps passé dans le réseau que de TTL → jeté avant tout rendu (0 frame).
    // Pas de journalisation : le signal n'a jamais atteint l'humain, ce n'est pas sa performance.
    if (transitAgeMs(raw) >= raw.timeToLiveMs) return
    set({ alert: { manifest: raw, receivedAtMs: performance.now(), status: 'ARMED' } })
  },
  lock: () => {
    const s = get()
    if (s.alert === null || s.alert.status !== 'ARMED') return   // transition UNIQUE (anti-double-envoi)
    // GEL DE THREAD : si le thread principal a figé au-delà du TTL, la touche en file d'attente
    // arrive AVANT la frame rAF suivante — le store re-vérifie l'échéance et refuse le lock.
    if (expired(s.alert)) { s.resolve('TIMEOUT'); return }
    const reactionMs = Math.round(performance.now() - s.alert.receivedAtMs)
    journalize(s.alert.manifest, 'ACK', reactionMs)
    set({ alert: { ...s.alert, status: 'LOCKED' },
      lastLockedId: s.alert.manifest.id, lockCount: s.lockCount + 1, lastOutcome: 'ACK' })
  },
  resolve: (outcome) => {
    const s = get()
    if (s.alert === null || s.alert.status !== 'ARMED') return   // LOCKED a déjà journalisé son ACK
    const reactionMs = outcome === 'REJECT_USER'
      ? Math.round(performance.now() - s.alert.receivedAtMs) : null
    journalize(s.alert.manifest, outcome, reactionMs)
    set({ alert: null, lastOutcome: outcome })
  },
  clear: () => set({ alert: null }),          // démontage pur (fin de TTL d'une alerte déjà LOCKED)
}))

// Affordances de test DEV-only (élaguées en prod par Vite) — même convention que terminal.ts.
if (import.meta.env.DEV && typeof window !== 'undefined') {
  ;(window as unknown as { __pushManifest?: (m: unknown) => void }).__pushManifest =
    (m) => useManifest.getState().push(m)
  ;(window as unknown as { __manifestState?: () => unknown }).__manifestState = () => {
    const s = useManifest.getState()
    return { id: s.alert?.manifest.id ?? null, status: s.alert?.status ?? null,
      lastLockedId: s.lastLockedId, lockCount: s.lockCount, lastOutcome: s.lastOutcome }
  }
}
