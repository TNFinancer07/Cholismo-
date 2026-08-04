import { describe, it, expect } from 'vitest';
import { b1WallRefill, b2TapeFlip, b3NormalizedDelta, b4SweepVelocity, runOrderFlowGates } from '../src/orderflow';
import { MES_TUNING } from '../src/config';
import { setup, orderFlow } from './fixtures';

const t = MES_TUNING;

describe('B4 — vitesse du sweep', () => {
  it('passe si l agression retombe', () => {
    expect(b4SweepVelocity(setup({ orderFlow: orderFlow({ postSweepAggressionRatio: 0.2 }) }), t)).toBeNull();
  });
  it('bloque si elle reste soutenue', () => {
    expect(b4SweepVelocity(setup({ orderFlow: orderFlow({ postSweepAggressionRatio: 0.5 }) }), t)).not.toBeNull();
  });
  it('fail-closed sur valeur négative', () => {
    expect(b4SweepVelocity(setup({ orderFlow: orderFlow({ postSweepAggressionRatio: -1 }) }), t)).not.toBeNull();
  });
});

describe('B1 — rechargement du mur', () => {
  it('bloque sous le seuil', () => {
    expect(b1WallRefill(setup({ orderFlow: orderFlow({ wallRefillRatio: 0.2 }) }), t)).not.toBeNull();
  });
  it('passe au seuil exact', () => {
    expect(b1WallRefill(setup({ orderFlow: orderFlow({ wallRefillRatio: 0.4 }) }), t)).toBeNull();
  });
});

describe('B2 — bascule du tape (symétrie)', () => {
  it('LONG requiert les acheteurs', () => {
    expect(b2TapeFlip(setup({ side: 'LONG', orderFlow: orderFlow({ tapeAggressorBuyFraction: 0.7 }) }), t)).toBeNull();
    expect(b2TapeFlip(setup({ side: 'LONG', orderFlow: orderFlow({ tapeAggressorBuyFraction: 0.5 }) }), t)).not.toBeNull();
  });
  it('SHORT requiert les vendeurs', () => {
    expect(b2TapeFlip(setup({ side: 'SHORT', orderFlow: orderFlow({ tapeAggressorBuyFraction: 0.3 }) }), t)).toBeNull();
    expect(b2TapeFlip(setup({ side: 'SHORT', orderFlow: orderFlow({ tapeAggressorBuyFraction: 0.5 }) }), t)).not.toBeNull();
  });
});

describe('B3 — delta normalisé signé', () => {
  it('LONG exige un delta positif', () => {
    expect(b3NormalizedDelta(setup({ side: 'LONG', orderFlow: orderFlow({ rejectionDeltaRatio: 0.4 }) }), t)).toBeNull();
    expect(b3NormalizedDelta(setup({ side: 'LONG', orderFlow: orderFlow({ rejectionDeltaRatio: -0.4 }) }), t)).not.toBeNull();
  });
  it('SHORT exige un delta négatif', () => {
    expect(b3NormalizedDelta(setup({ side: 'SHORT', orderFlow: orderFlow({ rejectionDeltaRatio: -0.4 }) }), t)).toBeNull();
  });
  it('fail-closed hors bornes [-1,1]', () => {
    expect(b3NormalizedDelta(setup({ orderFlow: orderFlow({ rejectionDeltaRatio: 2 }) }), t)).not.toBeNull();
  });
});

describe('Séquence complète', () => {
  it('renvoie null quand tout passe', () => {
    expect(runOrderFlowGates(setup(), t)).toBeNull();
  });
  it('renvoie B4 en priorité quand plusieurs gates échouent', () => {
    const bad = setup({ orderFlow: orderFlow({ postSweepAggressionRatio: 0.9, wallRefillRatio: 0.1 }) });
    expect(runOrderFlowGates(bad, t)).toBe('OF_B4_SUSTAINED_AGGRESSION');
  });
});
