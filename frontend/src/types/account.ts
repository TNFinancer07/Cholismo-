/** Miroir TypeScript de la Couche Compte & RiskSizer (backend/app/risk_sizer.py, D-047) —
 *  garder synchronisés. snake_case comme le backend (l'état naît côté Python, contrairement au
 *  TradeManifest né côté moteur TS — chaque contrat garde la convention de son lieu de naissance).
 *
 *  F1 STRUCTUREL : seuls les modèles EOD sont représentables — le type refuse l'Apex
 *  « Intraday Trail » (incompatible LSR). `drawdown_floor` est STATIQUE en intraday.
 *
 *  Le buffer est LA distance vers la mort : min(equity − floor, equity − (day_start − DLL)).
 *  Règle du 1/5e : risque alloué = buffer/5 ; contrats = floor(risque / (ticks × valeur_tick)).
 *  F8 : taille < 1 ou buffer ≤ 0 → REJECTED / INSUFFICIENT_BUFFER — `contracts` n'existe que
 *  sur APPROVED (jamais un 0 déguisé en taille, §3). */

export type AccountType = 'EOD_TRAILING' | 'EOD_STATIC'

export interface AccountState {
  account_type: AccountType
  current_equity: number
  day_start_equity: number
  /** Statique en intraday (EOD : recalculé à la clôture seulement, par le driver). */
  drawdown_floor: number
  /** DLL — pause la journée, ne tue pas le compte. */
  daily_loss_limit: number
}

export interface SizerResult {
  status: 'APPROVED' | 'REJECTED'
  /** 'INSUFFICIENT_BUFFER' (F8), 'INVALID_INPUT' (corruption d'entrée — non-fini, grandeurs de
   *  compte nulles/négatives, floor négatif) ou 'SIZE_SANITY_CAP' (taille au-delà du plafond de
   *  plausibilité — une équité corrompue produirait sinon un floor() astronomique cohérent). */
  reason: string
  contracts: number | null
  buffer: number | null
  risk_allowed: number | null
}
