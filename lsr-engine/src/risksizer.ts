/**
 * LSR v1.2 — RiskSizer. Le stop provient de la géométrie (A3).
 *   risque_$ = min(0.01 * capital, frontiere_restante / 5)
 *   contrats = floor( floor(risque / (stopTicks * tickValue)) * mult_VIX )
 */
import type { AccountState, MarketState, ExecutionPlan, AccountFrontiers, TradeGeometry } from './types';
import type { LsrConfig } from './config';
import { DEFAULT_CONFIG, instrumentSpec, vixMultiplier } from './config';

export interface RiskSizeResult {
  readonly contracts: number;
  readonly riskDollar: number;
  readonly grossContracts: number;
  readonly vixMult: number;
}

export function computeRiskSize(
  account: AccountState, market: MarketState, stopDistanceTicks: number,
  frontiers: AccountFrontiers, config: LsrConfig = DEFAULT_CONFIG,
): RiskSizeResult {
  const spec = instrumentSpec(market.instrument);
  const riskDollar = Math.min(
    config.riskFractionOfCapital * account.initialCapital,
    frontiers.frontiereJourRestante / config.bufferDivisor,
  );
  const perContractRisk = stopDistanceTicks * spec.tickValue;
  const grossContracts =
    Number.isFinite(riskDollar) && riskDollar > 0 && perContractRisk > 0
      ? Math.floor(riskDollar / perContractRisk) : 0;
  const vixMult = vixMultiplier(market.vix, config.f3VixHardBlock);
  const scaled = Math.floor(grossContracts * vixMult);
  const contracts = Number.isFinite(scaled) && scaled > 0 ? scaled : 0;
  return { contracts, riskDollar, grossContracts, vixMult };
}

export function splitScaleOut(contracts: number, config: LsrConfig = DEFAULT_CONFIG) {
  const clip1 = Math.min(contracts, Math.ceil(contracts * config.clip1Ratio));
  return { clip1_contracts: clip1, clip2_contracts: contracts - clip1 };
}

export function buildExecutionPlan(
  geo: TradeGeometry, contracts: number, config: LsrConfig = DEFAULT_CONFIG,
): ExecutionPlan {
  const { clip1_contracts, clip2_contracts } = splitScaleOut(contracts, config);
  return {
    contracts,
    entryOrder: { type: 'LIMIT', price: geo.entryPrice, cancelBeyondPrice: geo.cancelBeyondPrice },
    stopLoss: { type: 'MIT_OR_STOP', price: geo.stopPrice, distanceTicks: geo.stopDistanceTicks },
    takeProfit: { type: 'LIMIT', price: geo.tpPrice, distanceTicks: geo.tpTicks },
    scaleOutPlan: {
      clip1_contracts, clip1_tp_ticks: geo.tpTicks,
      clip2_contracts, clip2_tp_trailing: clip2_contracts > 0,
    },
  };
}
