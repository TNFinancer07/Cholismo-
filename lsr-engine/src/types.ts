/**
 * LSR v1.2 — Types du domaine (Liquidity Sweep Reversion).
 * Modules purs, déterministes : horloge et état sont injectés, jamais lus.
 */

export type Instrument = 'MES' | 'MNQ';

/** Spécification contractuelle CME (constantes, non calibrables). */
export interface InstrumentSpec {
  readonly tickSize: number;
  readonly tickValue: number;
}

/** F1 — seuls EOD_STATIC et EOD_TRAILING sont admissibles. */
export type AccountType = 'EOD_STATIC' | 'EOD_TRAILING' | 'INTRADAY_TRAILING';

export type Side = 'LONG' | 'SHORT';
export type SecondaryReference = 'VAH' | 'VAL' | 'LVN' | 'NONE';

export interface NewsEvent {
  readonly timestamp: number;
  readonly impact: 'RED' | 'ORANGE' | 'YELLOW';
  readonly name: string;
  readonly windowBeforeMs?: number;
  readonly windowAfterMs?: number;
}

export interface MarketDepthLevel {
  readonly price: number;
  readonly size: number;
}
export interface MarketDepth {
  readonly bids: readonly MarketDepthLevel[];
  readonly asks: readonly MarketDepthLevel[];
}

export interface MarketState {
  readonly now: number;
  readonly instrument: Instrument;
  readonly vix: number;
  readonly atrFast: number;
  readonly atrSlow: number;
  readonly spreadTicks: number;
  readonly depth: MarketDepth;
  readonly economicCalendar: readonly NewsEvent[];
}

export interface AccountState {
  readonly accountType: AccountType;
  readonly initialCapital: number;
  readonly currentEquity: number;
  readonly dayStartEquity: number;
  /** Niveau d'équité mortel du jour. */
  readonly drawdownFloor: number;
  /** Niveau d'équité mortel de la campagne. */
  readonly campaignFloor: number;
  /** null = firme sans DLL. Apex EOD : valeur numérique. */
  readonly dailyLossLimit: number | null;
}

/** Mesures order flow (B1/B2/B3/B4), fournies par la loop. */
export interface OrderFlowSnapshot {
  /** B1 — fraction du mur rechargée dans la fenêtre [0..1]. */
  readonly wallRefillRatio: number;
  /** B2 — fraction d'agressifs ACHETEURS au tape [0..1]. */
  readonly tapeAggressorBuyFraction: number;
  /** B3 — delta normalisé de la bougie de rejet, signé [-1..1]. */
  readonly rejectionDeltaRatio: number;
  /** B4 — agression post-sweep / agression du sweep [0..inf). */
  readonly postSweepAggressionRatio: number;
}

export interface SweepSetup {
  readonly setupId: string;
  readonly side: Side;
  readonly sweepTimestamp: number;
  /** Niveau de réintégration — référence de l'entrée A1. */
  readonly entryPrice: number;
  /** Extrême du sweep — référence du SL A3. */
  readonly sweepExtremePrice: number;
  /** Distance au VPOC cible, en ticks — borne du TP A2. */
  readonly distanceToVpocTicks: number;
  readonly orderFlow: OrderFlowSnapshot;
  readonly coincidesWithVpoc: boolean;
  readonly secondaryReference: SecondaryReference;
}

export interface LsrRuntimeState {
  readonly sessionDate: string;
  readonly consecutiveLosses: number;
  readonly tradesToday: number;
  readonly lockoutUntil: number | null;
  readonly campaignStopUntil: number | null;
  readonly rejectedSetupIds: readonly string[];
}

export const RejectReason = {
  F1_TRAILING_INTRADAY: 'F1_TRAILING_INTRADAY',
  F2_DAILY_CIRCUIT_BREAKER: 'F2_DAILY_CIRCUIT_BREAKER',
  F3_VOLATILITY_VIX: 'F3_VOLATILITY_VIX',
  F3_VOLATILITY_ATR: 'F3_VOLATILITY_ATR',
  F4_SPREAD_TOO_WIDE: 'F4_SPREAD_TOO_WIDE',
  F4_INSUFFICIENT_DEPTH: 'F4_INSUFFICIENT_DEPTH',
  F5_NEWS_BLACKOUT: 'F5_NEWS_BLACKOUT',
  F6_COOLDOWN_ACTIVE: 'F6_COOLDOWN_ACTIVE',
  F7_FOMO_TIMEOUT: 'F7_FOMO_TIMEOUT',
  F7_RESUBMIT_LOCKOUT: 'F7_RESUBMIT_LOCKOUT',
  F8_CAMPAIGN_STOP: 'F8_CAMPAIGN_STOP',
  F8_RESTRICTED_CONFLUENCE: 'F8_RESTRICTED_CONFLUENCE',
  F8_TRADE_CAP_REACHED: 'F8_TRADE_CAP_REACHED',
  A5B_FIRST_TRADE_CONFLUENCE: 'A5B_FIRST_TRADE_CONFLUENCE',
  A2_INSUFFICIENT_TP_ROOM: 'A2_INSUFFICIENT_TP_ROOM',
  OF_B4_SUSTAINED_AGGRESSION: 'OF_B4_SUSTAINED_AGGRESSION',
  OF_B1_NO_WALL_REFILL: 'OF_B1_NO_WALL_REFILL',
  OF_B2_TAPE_NOT_FLIPPED: 'OF_B2_TAPE_NOT_FLIPPED',
  OF_B3_DELTA_TOO_WEAK: 'OF_B3_DELTA_TOO_WEAK',
  SIZING_ZERO_CONTRACTS: 'SIZING_ZERO_CONTRACTS',
  INVALID_INPUT: 'INVALID_INPUT',
} as const;
export type RejectReason = typeof RejectReason[keyof typeof RejectReason];

export type CampaignMode = 'NORMAL' | 'RESTRICTED';

export interface AccountFrontiers {
  readonly perteJour: number;
  readonly frontiereJourInitiale: number;
  readonly frontiereJourRestante: number;
  readonly ddCampagne: number;
}

export interface Phase0Result {
  readonly passed: boolean;
  readonly rejectReason: RejectReason | null;
  readonly campaignMode: CampaignMode;
  readonly nextState: LsrRuntimeState;
  readonly frontiers: AccountFrontiers;
}

/** Géométrie du plan (A1/A2/A3), calculée avant le sizing. */
export interface TradeGeometry {
  readonly entryPrice: number;
  readonly cancelBeyondPrice: number;
  readonly stopPrice: number;
  readonly stopDistanceTicks: number;
  readonly tpPrice: number;
  readonly tpTicks: number;
}

export type GeometryResult =
  | { readonly ok: true; readonly geometry: TradeGeometry }
  | { readonly ok: false; readonly reason: RejectReason };

export interface ExecutionPlan {
  readonly contracts: number;
  readonly entryOrder: {
    readonly type: 'LIMIT';
    readonly price: number;
    readonly cancelBeyondPrice: number;
  };
  readonly stopLoss: {
    readonly type: 'MIT_OR_STOP';
    readonly price: number;
    readonly distanceTicks: number;
  };
  readonly takeProfit: {
    readonly type: 'LIMIT';
    readonly price: number;
    readonly distanceTicks: number;
  };
  readonly scaleOutPlan: {
    readonly clip1_contracts: number;
    readonly clip1_tp_ticks: number;
    readonly clip2_contracts: number;
    readonly clip2_tp_trailing: boolean;
  };
}

export interface LsrTradePlan {
  readonly strategy: 'LSR-v1.2';
  readonly timestamp: number;
  readonly instrument: Instrument;
  readonly status: 'APPROVED' | 'REJECTED';
  readonly rejectReason: string | null;
  readonly campaignMode: CampaignMode;
  readonly executionPlan: ExecutionPlan | null;
}
