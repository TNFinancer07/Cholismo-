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
 *  - un manifeste reçu pendant qu'une alerte est affichée → IGNORÉ (anti-substitution : le
 *    ticket ne change jamais sous le doigt de l'opérateur entre sa lecture et son Espace) ;
 *  - §2.1 : valider ENREGISTRE la décision, rien ici ne parle à un courtier. */
import { create } from 'zustand'
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

interface ManifestStore {
  alert: ManifestAlert | null
  /** Traçabilité post-démontage + garde anti-double-envoi observable dans les essais. */
  lastLockedId: string | null
  lockCount: number
  push: (raw: unknown) => void
  lock: () => void
  clear: () => void
}

export const useManifest = create<ManifestStore>((set, get) => ({
  alert: null,
  lastLockedId: null,
  lockCount: 0,
  push: (raw) => {
    if (get().alert !== null) return          // anti-substitution — premier arrivé tient la fenêtre
    if (!isValidManifest(raw)) return         // fail-closed — rien plutôt qu'un ticket dégradé
    set({ alert: { manifest: raw, receivedAtMs: performance.now(), status: 'ARMED' } })
  },
  lock: () =>
    set((s) => s.alert !== null && s.alert.status === 'ARMED'
      ? { alert: { ...s.alert, status: 'LOCKED' },
          lastLockedId: s.alert.manifest.id, lockCount: s.lockCount + 1 }
      : s),
  clear: () => set({ alert: null }),
}))

// Affordances de test DEV-only (élaguées en prod par Vite) — même convention que terminal.ts.
if (import.meta.env.DEV && typeof window !== 'undefined') {
  ;(window as unknown as { __pushManifest?: (m: unknown) => void }).__pushManifest =
    (m) => useManifest.getState().push(m)
  ;(window as unknown as { __manifestState?: () => unknown }).__manifestState = () => {
    const s = useManifest.getState()
    return { id: s.alert?.manifest.id ?? null, status: s.alert?.status ?? null,
      lastLockedId: s.lastLockedId, lockCount: s.lockCount }
  }
}
