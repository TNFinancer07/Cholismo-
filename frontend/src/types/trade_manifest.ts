/** Miroir TypeScript du TradeManifest (backend/app/trade_manifest.py, D-045) — garder synchronisés.
 *
 *  Contrat-pont entre le moteur LSR v1.2 (TypeScript, externe au dépôt) et Cholismo : le backend
 *  sérialise la sortie APPROUVÉE d'`evaluateLsr()` dans cet objet, le frontend l'affiche. HORS
 *  ContextSchema (§1) — d'où le camelCase, exception délibérée et bornée : le contrat naît côté
 *  TypeScript dans le moteur et arrive tel quel, aucune couche de traduction sur le fil.
 *
 *  §2.1 — un manifeste est une PROPOSITION enregistrée et affichée, jamais un ordre. Rien ici ne
 *  parle à un courtier.
 *
 *  Péremption : `timestamp` + `timeToLiveMs` (ms). Les helpers sont fail-closed (§3) — horloge
 *  non finie → périmé / 0 ms restantes ; borne d'échéance INCLUSE (à l'instant pile, c'est mort).
 *  L'horloge est TOUJOURS passée en argument (jamais lue ici) : même sémantique déterministe et
 *  testable que côté moteur et côté backend. */

export interface EntryPlan {
  /** LIMIT = prix limite posé ; MARKET = prix de référence observé à l'émission. */
  type: 'LIMIT' | 'MARKET'
  price: number
}

export interface RiskPlan {
  stopLoss: number
  takeProfit: number
  /** Contrats — le backend garantit un entier strictement positif (sinon pas de manifeste). */
  positionSize: number
}

export interface TradeManifest {
  /** SHA-1 tronqué du contenu : même plan au même instant → même id (clé React stable). */
  id: string
  /** Émission, epoch ms. */
  timestamp: number
  instrument: string
  direction: 'BUY' | 'SELL'
  reason: string
  entry: EntryPlan
  risk: RiskPlan
  /** Durée de vie du signal, ms (défaut backend : 3000). */
  timeToLiveMs: number
}

/** Échéance absolue, epoch ms. */
export function expiresAtMs(m: TradeManifest): number {
  return m.timestamp + m.timeToLiveMs
}

/** Périmé dès l'échéance ATTEINTE. Horloge non finie → périmé : un doute sur l'heure ne laisse
 *  jamais un ticket actionnable (§3). */
export function isExpired(m: TradeManifest, nowMs: number): boolean {
  if (!Number.isFinite(nowMs)) return true
  return nowMs >= expiresAtMs(m)
}

/** Millisecondes restantes, bornées à 0 — jamais de compte à rebours négatif à l'écran. */
export function remainingMs(m: TradeManifest, nowMs: number): number {
  if (!Number.isFinite(nowMs)) return 0
  return Math.max(0, Math.floor(expiresAtMs(m) - nowMs))
}
