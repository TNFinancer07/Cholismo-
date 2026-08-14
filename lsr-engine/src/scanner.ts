/**
 * LSR v1.2 — LSR_SCANNER (Phase 0 : F1–F8 + A5b + gates order flow).
 * Fonctions pures, fail-fast, nextState immuable, seuils par instrument.
 */
import type {
  MarketState, AccountState, SweepSetup, LsrRuntimeState,
  Phase0Result, RejectReason as RR, CampaignMode, AccountFrontiers,
  MarketDepth, MarketDepthLevel,
} from './types';
import { RejectReason } from './types';
import type { LsrConfig, InstrumentTuning } from './config';
import { DEFAULT_CONFIG, tuning } from './config';
import { deriveAccountFrontiers } from './frontiers';
import { runOrderFlowGates } from './orderflow';

export interface Phase0Input {
  readonly market: MarketState;
  readonly account: AccountState;
  readonly setup: SweepSetup;
  readonly state: LsrRuntimeState;
  readonly config?: LsrConfig;
}

/** F1 — méta-veto : Apex Intraday Trail et assimilés sont refusés ici. */
export function f1AccountType(acc: AccountState): RR | null {
  return acc.accountType === 'INTRADAY_TRAILING' ? RejectReason.F1_TRAILING_INTRADAY : null;
}

export function f2DailyCircuitBreaker(fr: AccountFrontiers, cfg: LsrConfig): RR | null {
  if (fr.frontiereJourInitiale <= 0) return RejectReason.F2_DAILY_CIRCUIT_BREAKER;
  return fr.perteJour >= cfg.f2CircuitThreshold * fr.frontiereJourInitiale
    ? RejectReason.F2_DAILY_CIRCUIT_BREAKER : null;
}

/** FAIL-CLOSED : donnée ATR manquante -> bloque. */
export function checkDynamicAtr(atrFast: number, atrSlow: number, multiplier: number): boolean {
  if (!(atrFast > 0) || !(atrSlow > 0)) return true;
  return atrFast > atrSlow * multiplier;
}

export function f3Volatility(m: MarketState, cfg: LsrConfig): RR | null {
  if (m.vix > cfg.f3VixHardBlock) return RejectReason.F3_VOLATILITY_VIX;
  if (checkDynamicAtr(m.atrFast, m.atrSlow, cfg.f3AtrMultiplier)) return RejectReason.F3_VOLATILITY_ATR;
  return null;
}

/** Profondeur cumulée top-3, requise des DEUX côtés. Sans allocation (hot path). */
export function validateBookProximityDepth(depth: MarketDepth, minCumulativeSize: number): boolean {
  const sumTop3 = (levels: readonly MarketDepthLevel[]): number => {
    let s = 0;
    const n = levels.length < 3 ? levels.length : 3;
    for (let i = 0; i < n; i++) s += levels[i]!.size;
    return s;
  };
  return sumTop3(depth.bids) >= minCumulativeSize && sumTop3(depth.asks) >= minCumulativeSize;
}

export function f4Liquidity(m: MarketState, t: InstrumentTuning): RR | null {
  if (m.spreadTicks > t.f4MaxSpreadTicks) return RejectReason.F4_SPREAD_TOO_WIDE;
  if (!validateBookProximityDepth(m.depth, t.f4MinCumulativeDepth)) return RejectReason.F4_INSUFFICIENT_DEPTH;
  return null;
}

export function f5News(m: MarketState, cfg: LsrConfig): RR | null {
  const now = m.now;
  for (const ev of m.economicCalendar) {
    if (ev.impact !== 'RED') continue;
    const before = ev.windowBeforeMs ?? cfg.f5DefaultBlackoutBeforeMs;
    const after = ev.windowAfterMs ?? cfg.f5DefaultBlackoutAfterMs;
    if (now >= ev.timestamp - before && now <= ev.timestamp + after) return RejectReason.F5_NEWS_BLACKOUT;
  }
  return null;
}

export function f6Cooldown(state: LsrRuntimeState, now: number): RR | null {
  return state.lockoutUntil != null && now < state.lockoutUntil ? RejectReason.F6_COOLDOWN_ACTIVE : null;
}

export function f7FomoAndResubmit(setup: SweepSetup, state: LsrRuntimeState, m: MarketState, cfg: LsrConfig): RR | null {
  if (state.rejectedSetupIds.includes(setup.setupId)) return RejectReason.F7_RESUBMIT_LOCKOUT;
  if (m.now - setup.sweepTimestamp > cfg.f7FomoWindowMs) return RejectReason.F7_FOMO_TIMEOUT;
  return null;
}

export function hasConfluence(setup: SweepSetup): boolean {
  return setup.coincidesWithVpoc && setup.secondaryReference !== 'NONE';
}

export function f8Campaign(
  fr: AccountFrontiers, setup: SweepSetup, state: LsrRuntimeState, now: number, cfg: LsrConfig,
): { reason: RR | null; mode: CampaignMode } {
  if (state.campaignStopUntil != null && now < state.campaignStopUntil) {
    return { reason: RejectReason.F8_CAMPAIGN_STOP, mode: 'NORMAL' };
  }
  if (fr.ddCampagne >= cfg.f8StopThreshold) {
    return { reason: RejectReason.F8_CAMPAIGN_STOP, mode: 'NORMAL' };
  }
  if (fr.ddCampagne >= cfg.f8RestrictedThreshold) {
    if (state.tradesToday >= cfg.f8RestrictedMaxTradesPerDay) {
      return { reason: RejectReason.F8_TRADE_CAP_REACHED, mode: 'RESTRICTED' };
    }
    if (!hasConfluence(setup)) return { reason: RejectReason.F8_RESTRICTED_CONFLUENCE, mode: 'RESTRICTED' };
    return { reason: null, mode: 'RESTRICTED' };
  }
  if (state.tradesToday >= cfg.normalMaxTradesPerDay) {
    return { reason: RejectReason.F8_TRADE_CAP_REACHED, mode: 'NORMAL' };
  }
  return { reason: null, mode: 'NORMAL' };
}

/** LOOP 4 — garde-fou global contre les flux corrompus. */
export function hasNonFiniteInputs(m: MarketState, acc: AccountState, s: SweepSetup): boolean {
  return (
    !Number.isFinite(m.now) || !Number.isFinite(m.vix) ||
    !Number.isFinite(m.atrFast) || !Number.isFinite(m.atrSlow) || !Number.isFinite(m.spreadTicks) ||
    !Number.isFinite(acc.initialCapital) || !Number.isFinite(acc.currentEquity) ||
    !Number.isFinite(acc.dayStartEquity) || !Number.isFinite(acc.drawdownFloor) ||
    !Number.isFinite(acc.campaignFloor) ||
    (acc.dailyLossLimit != null && !Number.isFinite(acc.dailyLossLimit)) ||
    !Number.isFinite(s.entryPrice) || !Number.isFinite(s.sweepExtremePrice) ||
    !Number.isFinite(s.distanceToVpocTicks) || !Number.isFinite(s.sweepTimestamp)
  );
}

const emptyFrontiers = (): AccountFrontiers => ({
  perteJour: 0, frontiereJourInitiale: 0, frontiereJourRestante: 0, ddCampagne: 0,
});

const SETUP_QUALITY_REJECTS = new Set<RR>([
  RejectReason.F7_FOMO_TIMEOUT, RejectReason.F8_RESTRICTED_CONFLUENCE,
  RejectReason.A5B_FIRST_TRADE_CONFLUENCE, RejectReason.OF_B4_SUSTAINED_AGGRESSION,
  RejectReason.OF_B1_NO_WALL_REFILL, RejectReason.OF_B2_TAPE_NOT_FLIPPED,
  RejectReason.OF_B3_DELTA_TOO_WEAK,
]);

function stateOnReject(state: LsrRuntimeState, reason: RR, setup: SweepSetup, now: number, cfg: LsrConfig): LsrRuntimeState {
  let next = state;
  if (SETUP_QUALITY_REJECTS.has(reason)) {
    next = {
      ...next,
      rejectedSetupIds: next.rejectedSetupIds.includes(setup.setupId)
        ? next.rejectedSetupIds : [...next.rejectedSetupIds, setup.setupId],
      lockoutUntil: Math.max(next.lockoutUntil ?? 0, now + cfg.f7ResubmitLockoutMs),
    };
  }
  if (reason === RejectReason.F8_CAMPAIGN_STOP && (next.campaignStopUntil == null || next.campaignStopUntil <= now)) {
    next = { ...next, campaignStopUntil: now + cfg.f8StopDurationMs };
  }
  return next;
}

/**
 * Phase 0 complète, fail-fast.
 * Ordre : garde -> F1 -> F8-ARRÊT -> F2 -> F6 -> F7 -> F3 -> F5 -> F4
 *         -> A5b -> F8-restreint/plafond -> gates OF.
 */
export function runPhase0(input: Phase0Input): Phase0Result {
  const cfg = input.config ?? DEFAULT_CONFIG;
  const { market, account, setup, state } = input;
  const now = market.now;
  const t = tuning(cfg, market.instrument);

  if (hasNonFiniteInputs(market, account, setup)) {
    return {
      passed: false, rejectReason: RejectReason.INVALID_INPUT, campaignMode: 'NORMAL',
      nextState: state, frontiers: emptyFrontiers(),
    };
  }

  const frontiers = deriveAccountFrontiers(account, cfg);
  const fail = (reason: RR, mode: CampaignMode = 'NORMAL'): Phase0Result => ({
    passed: false, rejectReason: reason, campaignMode: mode,
    nextState: stateOnReject(state, reason, setup, now, cfg), frontiers,
  });

  let r: RR | null;
  if ((r = f1AccountType(account))) return fail(r);

  const f8 = f8Campaign(frontiers, setup, state, now, cfg);
  if (f8.reason === RejectReason.F8_CAMPAIGN_STOP) return fail(f8.reason);

  if ((r = f2DailyCircuitBreaker(frontiers, cfg))) return fail(r);
  if ((r = f6Cooldown(state, now))) return fail(r);
  if ((r = f7FomoAndResubmit(setup, state, market, cfg))) return fail(r);
  if ((r = f3Volatility(market, cfg))) return fail(r);
  if ((r = f5News(market, cfg))) return fail(r);
  if ((r = f4Liquidity(market, t))) return fail(r);

  // A5b — premier trade de session : confluence renforcée obligatoire.
  if (state.tradesToday === 0 && !hasConfluence(setup)) {
    return fail(RejectReason.A5B_FIRST_TRADE_CONFLUENCE, f8.mode);
  }

  if (f8.reason) return fail(f8.reason, f8.mode);

  const ofReason = runOrderFlowGates(setup, t);
  if (ofReason) return fail(ofReason, f8.mode);

  return { passed: true, rejectReason: null, campaignMode: f8.mode, nextState: state, frontiers };
}

export function validateSessionAndSetup(input: Phase0Input): boolean {
  return runPhase0(input).passed;
}
