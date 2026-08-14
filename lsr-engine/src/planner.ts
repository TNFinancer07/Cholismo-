/**
 * LSR v1.2 — Planificateur : Phase 0 -> Géométrie (A1/A2/A3) -> RiskSizer -> manifeste.
 */
import type { LsrTradePlan, LsrRuntimeState, RejectReason } from './types';
import { RejectReason as RR } from './types';
import type { LsrConfig } from './config';
import { DEFAULT_CONFIG, tuning } from './config';
import { runPhase0 } from './scanner';
import type { Phase0Input } from './scanner';
import { computeGeometry } from './geometry';
import { computeRiskSize, buildExecutionPlan } from './risksizer';

export interface EvaluateResult {
  readonly plan: LsrTradePlan;
  readonly nextState: LsrRuntimeState;
}

export function evaluateLsr(input: Phase0Input): EvaluateResult {
  const cfg: LsrConfig = input.config ?? DEFAULT_CONFIG;
  const { market, account, setup } = input;
  const now = market.now;
  const t = tuning(cfg, market.instrument);

  const reject = (reason: RejectReason, mode: 'NORMAL' | 'RESTRICTED', nextState: LsrRuntimeState): EvaluateResult => ({
    plan: {
      strategy: 'LSR-v1.2', timestamp: now, instrument: market.instrument,
      status: 'REJECTED', rejectReason: reason, campaignMode: mode, executionPlan: null,
    },
    nextState,
  });

  const phase0 = runPhase0(input);
  if (!phase0.passed) return reject(phase0.rejectReason!, phase0.campaignMode, phase0.nextState);

  const geo = computeGeometry(market, setup, t);
  if (!geo.ok) return reject(geo.reason, phase0.campaignMode, phase0.nextState);

  const size = computeRiskSize(account, market, geo.geometry.stopDistanceTicks, phase0.frontiers, cfg);
  if (!Number.isFinite(size.contracts) || size.contracts < 1) {
    return reject(RR.SIZING_ZERO_CONTRACTS, phase0.campaignMode, phase0.nextState);
  }

  const executionPlan = buildExecutionPlan(geo.geometry, size.contracts, cfg);
  const nextState: LsrRuntimeState = { ...phase0.nextState, tradesToday: phase0.nextState.tradesToday + 1 };

  return {
    plan: {
      strategy: 'LSR-v1.2', timestamp: now, instrument: market.instrument,
      status: 'APPROVED', rejectReason: null, campaignMode: phase0.campaignMode, executionPlan,
    },
    nextState,
  };
}
