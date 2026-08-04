import type { MarketState, AccountState, SweepSetup, LsrRuntimeState, OrderFlowSnapshot } from '../src/types';
import { freshRuntimeState } from '../src/index';

export const T0 = 1_700_000_000_000;

export function orderFlow(over: Partial<OrderFlowSnapshot> = {}): OrderFlowSnapshot {
  return {
    wallRefillRatio: 0.6,
    tapeAggressorBuyFraction: 0.7,
    rejectionDeltaRatio: 0.5,
    postSweepAggressionRatio: 0.1,
    ...over,
  };
}

export function market(over: Partial<MarketState> = {}): MarketState {
  return {
    now: T0, instrument: 'MES', vix: 12, atrFast: 8, atrSlow: 10, spreadTicks: 1,
    depth: {
      bids: [{ price: 4999.75, size: 60 }, { price: 4999.5, size: 55 }, { price: 4999.25, size: 50 }],
      asks: [{ price: 5000.25, size: 60 }, { price: 5000.5, size: 55 }, { price: 5000.75, size: 50 }],
    },
    economicCalendar: [],
    ...over,
  };
}

/** Baseline sans DLL (MFF-like) — buffer jour = buffer campagne = 2000. */
export function account(over: Partial<AccountState> = {}): AccountState {
  return {
    accountType: 'EOD_STATIC',
    initialCapital: 50_000,
    currentEquity: 50_000,
    dayStartEquity: 50_000,
    drawdownFloor: 48_000,
    campaignFloor: 48_000,
    dailyLossLimit: null,
    ...over,
  };
}

export function setup(over: Partial<SweepSetup> = {}): SweepSetup {
  return {
    setupId: 's-1',
    side: 'LONG',
    sweepTimestamp: T0 - 10_000,
    entryPrice: 5000,
    sweepExtremePrice: 4998,
    distanceToVpocTicks: 6,
    orderFlow: orderFlow(),
    coincidesWithVpoc: true,
    secondaryReference: 'VAH',
    ...over,
  };
}

export function state(over: Partial<LsrRuntimeState> = {}): LsrRuntimeState {
  return { ...freshRuntimeState('2025-01-01'), ...over };
}
