import { describe, it, expect } from 'vitest';
import { runPhase0 } from '../src/scanner';
import type { Phase0Input } from '../src/scanner';
import { RejectReason } from '../src/types';
import { DEFAULT_CONFIG } from '../src/config';
import { market, account, setup, orderFlow, state, T0 } from './fixtures';

// tradesToday=1 par défaut pour ne pas déclencher A5b dans les tests génériques
const input = (o: Partial<Phase0Input> = {}): Phase0Input => ({
  market: market(), account: account(), setup: setup(), state: state({ tradesToday: 1 }), ...o,
});

describe('Baseline v1.2', () => {
  it('passe la Phase 0 quand tout est conforme', () => {
    const r = runPhase0(input());
    expect(r.passed).toBe(true);
    expect(r.rejectReason).toBeNull();
    expect(r.campaignMode).toBe('NORMAL');
  });
});

describe('F1 — méta-veto type de compte', () => {
  it('bloque INTRADAY_TRAILING (ex. Apex Intraday Trail)', () => {
    expect(runPhase0(input({ account: account({ accountType: 'INTRADAY_TRAILING' }) })).rejectReason)
      .toBe(RejectReason.F1_TRAILING_INTRADAY);
  });
  it('accepte EOD_STATIC et EOD_TRAILING (ex. Apex EOD Trail)', () => {
    expect(runPhase0(input({ account: account({ accountType: 'EOD_STATIC' }) })).passed).toBe(true);
    expect(runPhase0(input({ account: account({ accountType: 'EOD_TRAILING' }) })).passed).toBe(true);
  });
});

describe('F2 — disjoncteur intraday', () => {
  it('déclenche à 80% de la frontière du jour (isolé de F8)', () => {
    const acc = account({ currentEquity: 48_400, campaignFloor: 44_000 });
    expect(runPhase0(input({ account: acc })).rejectReason).toBe(RejectReason.F2_DAILY_CIRCUIT_BREAKER);
  });
  it('ne déclenche pas juste sous le seuil', () => {
    expect(runPhase0(input({ account: account({ currentEquity: 48_500, campaignFloor: 44_000 }) })).passed).toBe(true);
  });
  it('un DLL plus contraignant que le plancher devient la frontière (cas Apex EOD)', () => {
    const acc = account({ dailyLossLimit: 1000, currentEquity: 49_150 });
    expect(runPhase0(input({ account: acc })).rejectReason).toBe(RejectReason.F2_DAILY_CIRCUIT_BREAKER);
  });
});

describe('F3 — volatilité', () => {
  it('bloque VIX > 30', () => {
    expect(runPhase0(input({ market: market({ vix: 30.1 }) })).rejectReason).toBe(RejectReason.F3_VOLATILITY_VIX);
  });
  it('accepte VIX = 30 (borne inclusive)', () => {
    expect(runPhase0(input({ market: market({ vix: 30 }) })).passed).toBe(true);
  });
  it('bloque ATR rapide > 1.5x ATR de fond', () => {
    expect(runPhase0(input({ market: market({ atrFast: 20, atrSlow: 10 }) })).rejectReason)
      .toBe(RejectReason.F3_VOLATILITY_ATR);
  });
  it('FAIL-CLOSED : donnée ATR manquante bloque', () => {
    expect(runPhase0(input({ market: market({ atrSlow: 0 }) })).rejectReason).toBe(RejectReason.F3_VOLATILITY_ATR);
  });
});

describe('F4 — liquidité (seuils par instrument)', () => {
  it('bloque un spread > max MES (1 tick)', () => {
    expect(runPhase0(input({ market: market({ spreadTicks: 2 }) })).rejectReason).toBe(RejectReason.F4_SPREAD_TOO_WIDE);
  });
  it('MNQ tolère un spread de 2 ticks', () => {
    const m = market({
      instrument: 'MNQ', spreadTicks: 2,
      depth: {
        bids: [{ price: 1, size: 30 }, { price: 1, size: 20 }, { price: 1, size: 20 }],
        asks: [{ price: 1, size: 30 }, { price: 1, size: 20 }, { price: 1, size: 20 }],
      },
    });
    // 70 cumulé >= 60 requis sur MNQ ; distanceToVpoc 6 -> tp 5 >= tpMin 4
    expect(runPhase0(input({ market: m })).passed).toBe(true);
  });
  it('exige de la profondeur des DEUX côtés', () => {
    const thin = market({
      depth: {
        bids: [{ price: 1, size: 60 }, { price: 1, size: 55 }, { price: 1, size: 50 }],
        asks: [{ price: 1, size: 40 }, { price: 1, size: 40 }, { price: 1, size: 40 }],
      },
    });
    expect(runPhase0(input({ market: thin })).rejectReason).toBe(RejectReason.F4_INSUFFICIENT_DEPTH);
  });
});

describe('F5 — news T1', () => {
  it('bloque dans la fenêtre de blackout RED', () => {
    const m = market({ economicCalendar: [{ timestamp: T0 + 60_000, impact: 'RED', name: 'CPI' }] });
    expect(runPhase0(input({ market: m })).rejectReason).toBe(RejectReason.F5_NEWS_BLACKOUT);
  });
  it('ignore les événements non-RED', () => {
    const m = market({ economicCalendar: [{ timestamp: T0, impact: 'ORANGE', name: 'x' }] });
    expect(runPhase0(input({ market: m })).passed).toBe(true);
  });
  it('laisse passer hors fenêtre', () => {
    const m = market({ economicCalendar: [{ timestamp: T0 + 3_600_000, impact: 'RED', name: 'FOMC' }] });
    expect(runPhase0(input({ market: m })).passed).toBe(true);
  });
});

describe('F6 / F7', () => {
  it('F6 bloque pendant le cool-down', () => {
    expect(runPhase0(input({ state: state({ tradesToday: 1, lockoutUntil: T0 + 60_000 }) })).rejectReason)
      .toBe(RejectReason.F6_COOLDOWN_ACTIVE);
  });
  it('F6 laisse passer après expiration', () => {
    expect(runPhase0(input({ state: state({ tradesToday: 1, lockoutUntil: T0 - 1 }) })).passed).toBe(true);
  });
  it('F7 rejette au-delà de 90 s', () => {
    expect(runPhase0(input({ setup: setup({ sweepTimestamp: T0 - 91_000 }) })).rejectReason)
      .toBe(RejectReason.F7_FOMO_TIMEOUT);
  });
  it('F7 mémorise le setup rejeté et arme le lockout', () => {
    const r = runPhase0(input({ setup: setup({ sweepTimestamp: T0 - 91_000 }) }));
    expect(r.nextState.rejectedSetupIds).toContain('s-1');
    expect(r.nextState.lockoutUntil).toBe(T0 + DEFAULT_CONFIG.f7ResubmitLockoutMs);
  });
  it('F7 rejette une resoumission', () => {
    expect(runPhase0(input({ state: state({ tradesToday: 1, rejectedSetupIds: ['s-1'] }) })).rejectReason)
      .toBe(RejectReason.F7_RESUBMIT_LOCKOUT);
  });
});

describe('F8 — campagne', () => {
  it('ARRÊT >= 80% et arme les 24 h', () => {
    const acc = account({ currentEquity: 48_400, dayStartEquity: 48_400 });
    const r = runPhase0(input({ account: acc }));
    expect(r.rejectReason).toBe(RejectReason.F8_CAMPAIGN_STOP);
    expect(r.nextState.campaignStopUntil).toBe(T0 + DEFAULT_CONFIG.f8StopDurationMs);
  });
  it('reste bloqué pendant l arrêt 24 h', () => {
    expect(runPhase0(input({ state: state({ tradesToday: 1, campaignStopUntil: T0 + 3_600_000 }) })).rejectReason)
      .toBe(RejectReason.F8_CAMPAIGN_STOP);
  });
  it('RESTREINT >= 60% exige la confluence', () => {
    const acc = account({ currentEquity: 48_800, dayStartEquity: 48_800 });
    const r = runPhase0(input({ account: acc, setup: setup({ coincidesWithVpoc: false, secondaryReference: 'NONE' }) }));
    expect(r.campaignMode).toBe('RESTRICTED');
    expect(r.rejectReason).toBe(RejectReason.F8_RESTRICTED_CONFLUENCE);
  });
  it('RESTREINT passe avec confluence', () => {
    const acc = account({ currentEquity: 48_800, dayStartEquity: 48_800 });
    const r = runPhase0(input({ account: acc }));
    expect(r.campaignMode).toBe('RESTRICTED');
    expect(r.passed).toBe(true);
  });
  it('RESTREINT plafonne à 3 trades', () => {
    const acc = account({ currentEquity: 48_800, dayStartEquity: 48_800 });
    expect(runPhase0(input({ account: acc, state: state({ tradesToday: 3 }) })).rejectReason)
      .toBe(RejectReason.F8_TRADE_CAP_REACHED);
  });
  it('NORMAL plafonne à 10 trades', () => {
    expect(runPhase0(input({ state: state({ tradesToday: 10 }) })).rejectReason)
      .toBe(RejectReason.F8_TRADE_CAP_REACHED);
  });
});

describe('A5b — premier trade de session', () => {
  it('exige la confluence quand tradesToday = 0', () => {
    const r = runPhase0(input({
      state: state({ tradesToday: 0 }),
      setup: setup({ coincidesWithVpoc: false, secondaryReference: 'NONE' }),
    }));
    expect(r.rejectReason).toBe(RejectReason.A5B_FIRST_TRADE_CONFLUENCE);
  });
  it('passe au 1er trade avec confluence', () => {
    expect(runPhase0(input({ state: state({ tradesToday: 0 }) })).passed).toBe(true);
  });
  it('ne s applique plus dès le 2e trade', () => {
    const r = runPhase0(input({
      state: state({ tradesToday: 1 }),
      setup: setup({ coincidesWithVpoc: false, secondaryReference: 'NONE' }),
    }));
    expect(r.passed).toBe(true);
  });
});

describe('Gates order flow B1–B4', () => {
  it('B4 bloque une agression soutenue', () => {
    expect(runPhase0(input({ setup: setup({ orderFlow: orderFlow({ postSweepAggressionRatio: 0.9 }) }) })).rejectReason)
      .toBe(RejectReason.OF_B4_SUSTAINED_AGGRESSION);
  });
  it('B1 bloque sans rechargement du mur', () => {
    expect(runPhase0(input({ setup: setup({ orderFlow: orderFlow({ wallRefillRatio: 0.1 }) }) })).rejectReason)
      .toBe(RejectReason.OF_B1_NO_WALL_REFILL);
  });
  it('B2 bloque si le tape n a pas basculé (LONG)', () => {
    expect(runPhase0(input({ setup: setup({ orderFlow: orderFlow({ tapeAggressorBuyFraction: 0.5 }) }) })).rejectReason)
      .toBe(RejectReason.OF_B2_TAPE_NOT_FLIPPED);
  });
  it('B3 bloque un delta trop faible (LONG)', () => {
    expect(runPhase0(input({ setup: setup({ orderFlow: orderFlow({ rejectionDeltaRatio: 0.1 }) }) })).rejectReason)
      .toBe(RejectReason.OF_B3_DELTA_TOO_WEAK);
  });
  it('SHORT symétrique : passe avec tape vendeur et delta négatif', () => {
    const s = setup({
      side: 'SHORT', sweepExtremePrice: 5002,
      orderFlow: orderFlow({ tapeAggressorBuyFraction: 0.3, rejectionDeltaRatio: -0.5 }),
    });
    expect(runPhase0(input({ setup: s })).passed).toBe(true);
  });
  it('FAIL-CLOSED sur mesure OF non finie', () => {
    expect(runPhase0(input({ setup: setup({ orderFlow: orderFlow({ wallRefillRatio: NaN }) }) })).rejectReason)
      .toBe(RejectReason.OF_B1_NO_WALL_REFILL);
  });
});

describe('LOOP 4 — robustesse données malformées', () => {
  it('équité NaN -> INVALID_INPUT', () => {
    expect(runPhase0(input({ account: account({ currentEquity: NaN }) })).rejectReason).toBe(RejectReason.INVALID_INPUT);
  });
  it('VIX NaN -> INVALID_INPUT', () => {
    expect(runPhase0(input({ market: market({ vix: NaN }) })).rejectReason).toBe(RejectReason.INVALID_INPUT);
  });
  it('ATR NaN -> INVALID_INPUT', () => {
    expect(runPhase0(input({ market: market({ atrFast: NaN }) })).rejectReason).toBe(RejectReason.INVALID_INPUT);
  });
  it('plancher Infinity -> INVALID_INPUT', () => {
    expect(runPhase0(input({ account: account({ drawdownFloor: Infinity }) })).rejectReason).toBe(RejectReason.INVALID_INPUT);
  });
});
