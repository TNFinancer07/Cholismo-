/**
 * LSR v1.2 — Gates order flow (B1/B2/B3/B4).
 * Purs, fail-closed, side-aware, seuils PAR INSTRUMENT.
 * Ordre : B4 (anti-continuation) -> B1 (rechargement) -> B2 (tape) -> B3 (delta).
 */
import type { SweepSetup, RejectReason as RR } from './types';
import { RejectReason } from './types';
import type { InstrumentTuning } from './config';

/** B4 — vitesse du sweep : un excès est bref, une initiative est soutenue. */
export function b4SweepVelocity(setup: SweepSetup, t: InstrumentTuning): RR | null {
  const r = setup.orderFlow.postSweepAggressionRatio;
  if (!Number.isFinite(r) || r < 0) return RejectReason.OF_B4_SUSTAINED_AGGRESSION;
  return r <= t.b4MaxPostSweepAggression ? null : RejectReason.OF_B4_SUSTAINED_AGGRESSION;
}

/** B1 — rechargement du mur : les passifs doivent revenir défendre le niveau. */
export function b1WallRefill(setup: SweepSetup, t: InstrumentTuning): RR | null {
  const r = setup.orderFlow.wallRefillRatio;
  if (!Number.isFinite(r) || r < 0) return RejectReason.OF_B1_NO_WALL_REFILL;
  return r >= t.b1MinWallRefillRatio ? null : RejectReason.OF_B1_NO_WALL_REFILL;
}

/** B2 — bascule des agressifs au tape, symétrique selon le côté. */
export function b2TapeFlip(setup: SweepSetup, t: InstrumentTuning): RR | null {
  const f = setup.orderFlow.tapeAggressorBuyFraction;
  if (!Number.isFinite(f) || f < 0 || f > 1) return RejectReason.OF_B2_TAPE_NOT_FLIPPED;
  const ok = setup.side === 'LONG' ? f >= t.b2TapeFlipThreshold : f <= 1 - t.b2TapeFlipThreshold;
  return ok ? null : RejectReason.OF_B2_TAPE_NOT_FLIPPED;
}

/** B3 — delta normalisé (delta/volume) de la bougie de rejet, signé. */
export function b3NormalizedDelta(setup: SweepSetup, t: InstrumentTuning): RR | null {
  const d = setup.orderFlow.rejectionDeltaRatio;
  if (!Number.isFinite(d) || d < -1 || d > 1) return RejectReason.OF_B3_DELTA_TOO_WEAK;
  const ok = setup.side === 'LONG' ? d >= t.b3MinDeltaRatio : d <= -t.b3MinDeltaRatio;
  return ok ? null : RejectReason.OF_B3_DELTA_TOO_WEAK;
}

/** Séquence complète — premier motif de rejet ou null. */
export function runOrderFlowGates(setup: SweepSetup, t: InstrumentTuning): RR | null {
  return (
    b4SweepVelocity(setup, t) ??
    b1WallRefill(setup, t) ??
    b2TapeFlip(setup, t) ??
    b3NormalizedDelta(setup, t)
  );
}
