/**
 * LSR v1.2 — Grandeurs de risque dérivées.
 *
 * CONVENTION DE SIGNE : les planchers sont des NIVEAUX d'équité. Les grandeurs
 * exposées sont POSITIVES (marge de perte restante, fraction de buffer consommée).
 */
import type { AccountState, AccountFrontiers } from './types';
import type { LsrConfig } from './config';

function clamp(x: number, lo: number, hi: number): number {
  return x < lo ? lo : x > hi ? hi : x;
}

export function deriveAccountFrontiers(acc: AccountState, _cfg: LsrConfig): AccountFrontiers {
  const roomToFloorStart = acc.dayStartEquity - acc.drawdownFloor;
  const roomToFloorNow = acc.currentEquity - acc.drawdownFloor;
  const perteJour = Math.max(0, acc.dayStartEquity - acc.currentEquity);

  const dll = acc.dailyLossLimit;
  const frontiereJourInitiale =
    dll == null ? Math.max(0, roomToFloorStart) : Math.max(0, Math.min(roomToFloorStart, dll));

  const remainingDailyAllowance = dll == null ? Number.POSITIVE_INFINITY : Math.max(0, dll - perteJour);
  const frontiereJourRestante = Math.max(0, Math.min(roomToFloorNow, remainingDailyAllowance));

  const campaignBuffer = acc.initialCapital - acc.campaignFloor;
  const campaignConsumed = acc.initialCapital - acc.currentEquity;
  const ddCampagne = campaignBuffer <= 0 ? 1 : clamp(campaignConsumed / campaignBuffer, 0, 1);

  return { perteJour, frontiereJourInitiale, frontiereJourRestante, ddCampagne };
}
