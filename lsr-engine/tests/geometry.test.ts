import { describe, it, expect } from 'vitest';
import { computeGeometry, computeTpTicks, noiseBufferTicks } from '../src/geometry';
import { MES_TUNING, MNQ_TUNING } from '../src/config';
import { market, setup } from './fixtures';

describe('A2 — TP borné par le VPOC', () => {
  it('plafonne à tpMax (MES = 5)', () => expect(computeTpTicks(20, MES_TUNING)).toBe(5));
  it('vise 1 tick avant le VPOC', () => expect(computeTpTicks(6, MES_TUNING)).toBe(5));
  it('coupe court quand le VPOC est proche', () => expect(computeTpTicks(5, MES_TUNING)).toBe(4));
  it('MNQ plafonne plus haut (8)', () => expect(computeTpTicks(20, MNQ_TUNING)).toBe(8));
  it('rejette si room < tpMin', () => {
    const g = computeGeometry(market(), setup({ distanceToVpocTicks: 3 }), MES_TUNING);
    expect(g.ok).toBe(false);
    if (!g.ok) expect(g.reason).toBe('A2_INSUFFICIENT_TP_ROOM');
  });
});

describe('A3 — buffer bruit du stop', () => {
  it('MES : base = spread, borné à 2', () => {
    expect(noiseBufferTicks(market({ spreadTicks: 1, atrFast: 8, atrSlow: 10 }), MES_TUNING)).toBe(1);
    expect(noiseBufferTicks(market({ spreadTicks: 1, atrFast: 12, atrSlow: 10 }), MES_TUNING)).toBe(2);
  });
  it('MNQ : buffers plus larges (min 2, max 4)', () => {
    expect(noiseBufferTicks(market({ spreadTicks: 1, atrFast: 8, atrSlow: 10 }), MNQ_TUNING)).toBe(2);
    expect(noiseBufferTicks(market({ spreadTicks: 3, atrFast: 12, atrSlow: 10 }), MNQ_TUNING)).toBe(4);
  });
});

describe('Géométrie LONG', () => {
  it('entrée au-dessus, SL sous l extrême, TP au-dessus', () => {
    const g = computeGeometry(market(), setup({ side: 'LONG', entryPrice: 5000, sweepExtremePrice: 4998, distanceToVpocTicks: 6 }), MES_TUNING);
    expect(g.ok).toBe(true);
    if (g.ok) {
      expect(g.geometry.entryPrice).toBe(5000.25);
      expect(g.geometry.cancelBeyondPrice).toBe(4999.25);
      expect(g.geometry.stopPrice).toBe(4997.75);
      expect(g.geometry.stopDistanceTicks).toBe(10);
      expect(g.geometry.tpTicks).toBe(5);
      expect(g.geometry.tpPrice).toBe(5001.5);
    }
  });
});

describe('Géométrie SHORT (symétrie)', () => {
  it('entrée en dessous, SL au-dessus de l extrême', () => {
    const g = computeGeometry(market(), setup({ side: 'SHORT', entryPrice: 5000, sweepExtremePrice: 5002, distanceToVpocTicks: 6 }), MES_TUNING);
    expect(g.ok).toBe(true);
    if (g.ok) {
      expect(g.geometry.entryPrice).toBe(4999.75);
      expect(g.geometry.cancelBeyondPrice).toBe(5000.75);
      expect(g.geometry.stopPrice).toBe(5002.25);
      expect(g.geometry.stopDistanceTicks).toBe(10);
      expect(g.geometry.tpPrice).toBe(4998.5);
    }
  });
});

describe('Garde-fous géométrie', () => {
  it('rejette une distance VPOC non finie', () => {
    const g = computeGeometry(market(), setup({ distanceToVpocTicks: NaN }), MES_TUNING);
    expect(g.ok).toBe(false);
  });
  it('rejette un stop du mauvais côté de l entrée', () => {
    const g = computeGeometry(market(), setup({ side: 'LONG', entryPrice: 5000, sweepExtremePrice: 5010 }), MES_TUNING);
    expect(g.ok).toBe(false);
    if (!g.ok) expect(g.reason).toBe('INVALID_INPUT');
  });
});
