/**
 * LSR v1.2 — Géométrie du plan (A1 / A2 / A3), calibrée par instrument.
 * A1 : entrée = niveau + offset DANS le sens de la réintégration ; annulation
 *      si le prix repasse de l'autre côté (setup invalidé avant fill).
 * A2 : TP = min(TP_max, dist_VPOC - marge), rejet sous TP_min.
 * A3 : SL au-delà de l'extrême du sweep + buffer bruit f(spread, régime ATR).
 */
import type { MarketState, SweepSetup, GeometryResult } from './types';
import { RejectReason } from './types';
import type { InstrumentTuning } from './config';
import { instrumentSpec } from './config';

export function noiseBufferTicks(m: MarketState, t: InstrumentTuning): number {
  const base = Math.max(t.slNoiseBufferMinTicks, Math.ceil(m.spreadTicks));
  const regimeExtra = m.atrFast > m.atrSlow ? 1 : 0;
  return Math.min(t.slNoiseBufferMaxTicks, base + regimeExtra);
}

export function computeTpTicks(distanceToVpocTicks: number, t: InstrumentTuning): number {
  return Math.min(t.tpMaxTicks, Math.floor(distanceToVpocTicks) - t.tpVpocMarginTicks);
}

export function computeGeometry(m: MarketState, setup: SweepSetup, t: InstrumentTuning): GeometryResult {
  if (!Number.isFinite(setup.distanceToVpocTicks) || !Number.isFinite(setup.sweepExtremePrice)) {
    return { ok: false, reason: RejectReason.INVALID_INPUT };
  }
  const { tickSize } = instrumentSpec(m.instrument);
  const dir = setup.side === 'LONG' ? 1 : -1;

  const tpTicks = computeTpTicks(setup.distanceToVpocTicks, t);
  if (tpTicks < t.tpMinTicks) return { ok: false, reason: RejectReason.A2_INSUFFICIENT_TP_ROOM };

  const entryPrice = roundTick(setup.entryPrice + dir * t.entryOffsetTicks * tickSize, tickSize);
  const cancelBeyondPrice = roundTick(setup.entryPrice - dir * t.entryCancelDistanceTicks * tickSize, tickSize);

  const buffer = noiseBufferTicks(m, t);
  const stopPrice = roundTick(setup.sweepExtremePrice - dir * buffer * tickSize, tickSize);

  const stopDistanceTicks = Math.round((dir * (entryPrice - stopPrice)) / tickSize);
  if (!Number.isFinite(stopDistanceTicks) || stopDistanceTicks <= 0) {
    return { ok: false, reason: RejectReason.INVALID_INPUT };
  }

  const tpPrice = roundTick(entryPrice + dir * tpTicks * tickSize, tickSize);
  return { ok: true, geometry: { entryPrice, cancelBeyondPrice, stopPrice, stopDistanceTicks, tpPrice, tpTicks } };
}

function roundTick(price: number, tick: number): number {
  const inv = 1 / tick;
  return Math.round(price * inv) / inv;
}
