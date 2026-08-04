import { describe, it, expect } from 'vitest';
import { computeRiskSize, buildExecutionPlan, splitScaleOut } from '../src/risksizer';
import { evaluateLsr } from '../src/planner';
import { vixMultiplier, DEFAULT_CONFIG, MES_TUNING, APEX_EOD_50K, apexEodAccount } from '../src/config';
import { deriveAccountFrontiers } from '../src/frontiers';
import { computeGeometry } from '../src/geometry';
import { market, account, setup, state } from './fixtures';

const cfg = DEFAULT_CONFIG;

describe('Modificateur VIX — bornes', () => {
  it.each([[10, 1.0], [14.99, 1.0], [15, 0.75], [19.99, 0.75], [20, 0.5], [30, 0.5], [30.01, 0], [45, 0]])(
    'VIX %f -> x%f', (vix, mult) => expect(vixMultiplier(vix)).toBe(mult),
  );
});

describe('RÈGLE STRICTE : division du buffer par 5', () => {
  it('plafonne à frontière_restante / 5', () => {
    const acc = account();
    const fr = deriveAccountFrontiers(acc, cfg);
    expect(fr.frontiereJourRestante).toBe(2000);
    const r = computeRiskSize(acc, market({ vix: 10 }), 8, fr, cfg);
    expect(r.riskDollar).toBe(400);   // 2000/5
    expect(r.grossContracts).toBe(40); // 400/(8*1.25)
    expect(r.contracts).toBe(40);
  });
  it('plafonne à 1% du capital si la frontière est large', () => {
    const acc = account({ currentEquity: 60_000, dayStartEquity: 60_000, drawdownFloor: 40_000, campaignFloor: 40_000 });
    const fr = deriveAccountFrontiers(acc, cfg);
    expect(computeRiskSize(acc, market({ vix: 10 }), 10, fr, cfg).riskDollar).toBe(500);
  });
  it('applique le floor sur la taille brute', () => {
    const fr = deriveAccountFrontiers(account(), cfg);
    expect(computeRiskSize(account(), market({ vix: 10 }), 6, fr, cfg).grossContracts).toBe(53); // 400/7.5
  });
  it('applique le modif VIX puis re-floor', () => {
    const fr = deriveAccountFrontiers(account(), cfg);
    const r = computeRiskSize(account(), market({ vix: 22 }), 8, fr, cfg);
    expect(r.vixMult).toBe(0.5);
    expect(r.contracts).toBe(20);
  });
  it('MNQ a une valeur de tick différente (0.50)', () => {
    const fr = deriveAccountFrontiers(account(), cfg);
    expect(computeRiskSize(account(), market({ instrument: 'MNQ', vix: 10 }), 8, fr, cfg).contracts).toBe(100);
  });
  it('renvoie 0 contrat si la frontière est minuscule', () => {
    const acc = account({ currentEquity: 48_010 });
    const fr = deriveAccountFrontiers(acc, cfg);
    expect(computeRiskSize(acc, market({ vix: 10 }), 8, fr, cfg).contracts).toBe(0);
  });
});

describe('Preset Apex EOD', () => {
  it('produit un compte EOD_TRAILING avec DLL', () => {
    const acc = apexEodAccount(APEX_EOD_50K);
    expect(acc.accountType).toBe('EOD_TRAILING');
    expect(acc.dailyLossLimit).toBe(1000);
    expect(acc.drawdownFloor).toBe(47_500);
  });
  it('le DLL borne la frontière du jour, pas le plancher', () => {
    const fr = deriveAccountFrontiers(apexEodAccount(APEX_EOD_50K), cfg);
    // min(50000-47500 = 2500, DLL 1000) = 1000
    expect(fr.frontiereJourInitiale).toBe(1000);
    expect(fr.frontiereJourRestante).toBe(1000);
  });
  it('le sizing suit la frontière Apex (1000/5 = 200)', () => {
    const acc = apexEodAccount(APEX_EOD_50K);
    const fr = deriveAccountFrontiers(acc, cfg);
    const r = computeRiskSize(acc, market({ vix: 10 }), 8, fr, cfg);
    expect(r.riskDollar).toBe(200);
    expect(r.contracts).toBe(20);
  });
});

describe('Scale-out', () => {
  it('clip1 prend la majorité absolue', () => {
    expect(splitScaleOut(40, cfg)).toEqual({ clip1_contracts: 20, clip2_contracts: 20 });
    expect(splitScaleOut(41, cfg)).toEqual({ clip1_contracts: 21, clip2_contracts: 20 });
    expect(splitScaleOut(1, cfg)).toEqual({ clip1_contracts: 1, clip2_contracts: 0 });
  });
});

describe('buildExecutionPlan depuis la géométrie', () => {
  it('reporte prix et ticks, trailing seulement si clip2 > 0', () => {
    const g = computeGeometry(market(), setup(), MES_TUNING);
    expect(g.ok).toBe(true);
    if (g.ok) {
      const p = buildExecutionPlan(g.geometry, 10, cfg);
      expect(p.entryOrder.price).toBe(g.geometry.entryPrice);
      expect(p.entryOrder.cancelBeyondPrice).toBe(g.geometry.cancelBeyondPrice);
      expect(p.stopLoss.distanceTicks).toBe(g.geometry.stopDistanceTicks);
      expect(p.takeProfit.distanceTicks).toBe(g.geometry.tpTicks);
      expect(p.scaleOutPlan.clip2_tp_trailing).toBe(true);
      expect(buildExecutionPlan(g.geometry, 1, cfg).scaleOutPlan.clip2_tp_trailing).toBe(false);
    }
  });
});

describe('evaluateLsr — manifeste complet', () => {
  const base = { market: market({ vix: 10 }), account: account(), setup: setup(), state: state({ tradesToday: 1 }) };

  it('APPROVED : structure exacte + compteur incrémenté', () => {
    const { plan, nextState } = evaluateLsr(base);
    expect(plan.strategy).toBe('LSR-v1.2');
    expect(plan.status).toBe('APPROVED');
    expect(plan.rejectReason).toBeNull();
    expect(plan.executionPlan).not.toBeNull();
    expect(plan.executionPlan!.entryOrder.type).toBe('LIMIT');
    expect(plan.executionPlan!.stopLoss.type).toBe('MIT_OR_STOP');
    expect(Number.isInteger(plan.executionPlan!.contracts)).toBe(true);
    expect(plan.executionPlan!.contracts).toBeGreaterThanOrEqual(1);
    expect(nextState.tradesToday).toBe(2);
  });

  it('REJECTED A2 quand il n y a pas de room TP', () => {
    const { plan } = evaluateLsr({ ...base, setup: setup({ distanceToVpocTicks: 3 }) });
    expect(plan.status).toBe('REJECTED');
    expect(plan.rejectReason).toBe('A2_INSUFFICIENT_TP_ROOM');
  });

  it('REJECTED : executionPlan null et raison renseignée', () => {
    const { plan } = evaluateLsr({ ...base, market: market({ vix: 35 }) });
    expect(plan.status).toBe('REJECTED');
    expect(plan.executionPlan).toBeNull();
    expect(plan.rejectReason).toBe('F3_VOLATILITY_VIX');
  });

  it('LOOP 4 : équité NaN -> REJECTED, jamais NaN contrats', () => {
    const { plan } = evaluateLsr({ ...base, account: account({ currentEquity: NaN }) });
    expect(plan.status).toBe('REJECTED');
    expect(plan.executionPlan).toBeNull();
  });

  it('n incrémente pas le compteur sur un rejet', () => {
    expect(evaluateLsr({ ...base, market: market({ vix: 35 }) }).nextState.tradesToday).toBe(1);
  });

  it('bout-en-bout sur compte Apex EOD', () => {
    const { plan } = evaluateLsr({ ...base, account: apexEodAccount(APEX_EOD_50K) });
    expect(plan.status).toBe('APPROVED');
    // v1.2 : le stop vient de la GÉOMÉTRIE (A3), pas d'un input.
    // entrée 5000.25 / stop 4997.75 -> 10 ticks. Risque Apex = DLL 1000 / 5 = 200.
    // 200 / (10 ticks * 1.25) = 16 contrats.
    expect(plan.executionPlan!.stopLoss.distanceTicks).toBe(10);
    expect(plan.executionPlan!.contracts).toBe(16);
  });
});
