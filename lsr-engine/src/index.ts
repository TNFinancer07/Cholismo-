/**
 * LSR v1.2 — API publique du moteur. Le driver runtime n'importe que d'ici.
 */
export * from './types';
export * from './config';
export {
  runPhase0, validateSessionAndSetup, hasNonFiniteInputs, hasConfluence,
  f1AccountType, f2DailyCircuitBreaker, f3Volatility, f4Liquidity,
  f5News, f6Cooldown, f7FomoAndResubmit, f8Campaign,
  checkDynamicAtr, validateBookProximityDepth,
} from './scanner';
export type { Phase0Input } from './scanner';
export { b1WallRefill, b2TapeFlip, b3NormalizedDelta, b4SweepVelocity, runOrderFlowGates } from './orderflow';
export { computeGeometry, computeTpTicks, noiseBufferTicks } from './geometry';
export { computeRiskSize, buildExecutionPlan, splitScaleOut } from './risksizer';
export { evaluateLsr } from './planner';
export type { EvaluateResult } from './planner';
export { deriveAccountFrontiers } from './frontiers';

import type { LsrRuntimeState } from './types';
import type { LsrConfig } from './config';
import { DEFAULT_CONFIG } from './config';

export function freshRuntimeState(sessionDate: string): LsrRuntimeState {
  return {
    sessionDate, consecutiveLosses: 0, tradesToday: 0,
    lockoutUntil: null, campaignStopUntil: null, rejectedSetupIds: [],
  };
}

/** Reset quotidien : conserve un arrêt campagne 24 h en cours. */
export function rolloverDaily(state: LsrRuntimeState, newDate: string, now: number): LsrRuntimeState {
  const campaignStopUntil =
    state.campaignStopUntil != null && now < state.campaignStopUntil ? state.campaignStopUntil : null;
  return {
    sessionDate: newDate,
    consecutiveLosses: state.consecutiveLosses,
    tradesToday: 0,
    lockoutUntil: null,
    campaignStopUntil,
    rejectedSetupIds: [],
  };
}

/** F6 — appelé par le driver à la clôture, jamais par le moteur de décision. */
export function recordTradeOutcome(
  state: LsrRuntimeState, won: boolean, now: number, config: LsrConfig = DEFAULT_CONFIG,
): LsrRuntimeState {
  if (won) return { ...state, consecutiveLosses: 0 };
  const losses = state.consecutiveLosses + 1;
  const lockoutUntil = losses >= config.f6ConsecutiveLossTrigger
    ? Math.max(state.lockoutUntil ?? 0, now + config.f6CooldownMs)
    : state.lockoutUntil;
  return { ...state, consecutiveLosses: losses, lockoutUntil };
}
