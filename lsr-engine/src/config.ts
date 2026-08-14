/**
 * LSR v1.2 — Configuration.
 * Deux niveaux :
 *   - GLOBAL      : règles de risque et de session, identiques pour tout instrument.
 *   - PAR INSTRUMENT : tout ce qui touche la microstructure (spread, profondeur,
 *     géométrie en ticks, seuils order flow) — MES et MNQ n'ont pas la même
 *     densité de carnet ni la même vitesse.
 * Aucun seuil n'est codé en dur dans la logique.
 */
import type { Instrument, InstrumentSpec, AccountState } from './types';

/** Spécifications contractuelles CME (constantes, non calibrables). */
export const INSTRUMENT_SPECS: Readonly<Record<Instrument, InstrumentSpec>> = {
  MES: { tickSize: 0.25, tickValue: 1.25 },
  MNQ: { tickSize: 0.25, tickValue: 0.5 },
};

/** Paramètres calibrables PAR INSTRUMENT. Valeurs = 1re passe, à figer sur 60 trades. */
export interface InstrumentTuning {
  // F4 — fenêtre de liquidité
  readonly f4MaxSpreadTicks: number;
  readonly f4MinCumulativeDepth: number;
  // A2 — TP borné VPOC
  readonly tpMaxTicks: number;
  readonly tpMinTicks: number;
  readonly tpVpocMarginTicks: number;
  // A1 — zone d'entrée
  readonly entryOffsetTicks: number;
  readonly entryCancelDistanceTicks: number;
  // A3 — buffer bruit du stop
  readonly slNoiseBufferMinTicks: number;
  readonly slNoiseBufferMaxTicks: number;
  // B1–B4 — gates order flow
  readonly b1MinWallRefillRatio: number;
  readonly b2TapeFlipThreshold: number;
  readonly b3MinDeltaRatio: number;
  readonly b4MaxPostSweepAggression: number;
  // UI — distance de déclenchement d'alerte (spec 05)
  readonly alertDistanceTicks: number;
}

export interface LsrConfig {
  // ── Risque ──
  readonly riskFractionOfCapital: number;
  readonly bufferDivisor: number;            // 5 — règle stricte v1.1
  readonly f2CircuitThreshold: number;       // 0.80
  // ── F3 volatilité ──
  readonly f3VixHardBlock: number;
  readonly f3AtrMultiplier: number;
  // ── F5 news ──
  readonly f5DefaultBlackoutBeforeMs: number;
  readonly f5DefaultBlackoutAfterMs: number;
  // ── F6 / F7 ──
  readonly f6CooldownMs: number;
  readonly f6ConsecutiveLossTrigger: number;
  readonly f7FomoWindowMs: number;
  readonly f7ResubmitLockoutMs: number;
  // ── F8 campagne ──
  readonly f8RestrictedThreshold: number;
  readonly f8StopThreshold: number;
  readonly f8StopDurationMs: number;
  readonly f8RestrictedMaxTradesPerDay: number;
  readonly normalMaxTradesPerDay: number;
  // ── Scale-out ──
  readonly clip1Ratio: number;
  // ── Calibration par instrument ──
  readonly perInstrument: Readonly<Record<Instrument, InstrumentTuning>>;
}

/**
 * MES — Micro E-mini S&P 500. Carnet dense, mouvement plus lent.
 * Valeurs de 1re passe (PLACEHOLDER de calibration).
 */
export const MES_TUNING: InstrumentTuning = {
  f4MaxSpreadTicks: 1,
  f4MinCumulativeDepth: 150,
  tpMaxTicks: 5,
  tpMinTicks: 3,
  tpVpocMarginTicks: 1,
  entryOffsetTicks: 1,
  entryCancelDistanceTicks: 3,
  slNoiseBufferMinTicks: 1,
  slNoiseBufferMaxTicks: 2,
  b1MinWallRefillRatio: 0.4,
  b2TapeFlipThreshold: 0.6,
  b3MinDeltaRatio: 0.3,
  b4MaxPostSweepAggression: 0.3,
  alertDistanceTicks: 6,
};

/**
 * MNQ — Micro E-mini Nasdaq-100. Plus rapide, plus volatil, carnet plus fin :
 * buffers et TP légèrement plus larges, exigence de profondeur plus basse.
 * Valeurs de 1re passe (PLACEHOLDER de calibration).
 */
export const MNQ_TUNING: InstrumentTuning = {
  f4MaxSpreadTicks: 2,
  f4MinCumulativeDepth: 60,
  tpMaxTicks: 8,
  tpMinTicks: 4,
  tpVpocMarginTicks: 1,
  entryOffsetTicks: 1,
  entryCancelDistanceTicks: 4,
  slNoiseBufferMinTicks: 2,
  slNoiseBufferMaxTicks: 4,
  b1MinWallRefillRatio: 0.4,
  b2TapeFlipThreshold: 0.6,
  b3MinDeltaRatio: 0.3,
  b4MaxPostSweepAggression: 0.3,
  alertDistanceTicks: 10,
};

export const DEFAULT_CONFIG: LsrConfig = {
  riskFractionOfCapital: 0.01,
  bufferDivisor: 5,
  f2CircuitThreshold: 0.8,
  f3VixHardBlock: 30,
  f3AtrMultiplier: 1.5,
  f5DefaultBlackoutBeforeMs: 2 * 60_000,
  f5DefaultBlackoutAfterMs: 2 * 60_000,
  f6CooldownMs: 15 * 60_000,
  f6ConsecutiveLossTrigger: 2,
  f7FomoWindowMs: 90_000,
  f7ResubmitLockoutMs: 15 * 60_000,
  f8RestrictedThreshold: 0.6,
  f8StopThreshold: 0.8,
  f8StopDurationMs: 24 * 60 * 60_000,
  f8RestrictedMaxTradesPerDay: 3,
  normalMaxTradesPerDay: 10,
  clip1Ratio: 0.5,
  perInstrument: { MES: MES_TUNING, MNQ: MNQ_TUNING },
};

export function instrumentSpec(instrument: Instrument): InstrumentSpec {
  return INSTRUMENT_SPECS[instrument];
}

/** Accès au bloc de calibration d'un instrument. */
export function tuning(cfg: LsrConfig, instrument: Instrument): InstrumentTuning {
  return cfg.perInstrument[instrument];
}

/**
 * Modificateur de sizing selon le régime VIX.
 * [0,15) → 1.0 · [15,20) → 0.75 · [20,30] → 0.50 · (30,∞) → 0 (suspendu, cf. F3)
 */
export function vixMultiplier(vix: number, hardBlock: number = DEFAULT_CONFIG.f3VixHardBlock): number {
  if (vix > hardBlock) return 0;
  if (vix < 15) return 1.0;
  if (vix < 20) return 0.75;
  return 0.5;
}

// ─────────────────────────────────────────────────────────────
// Presets de compte — APEX (EOD TRAIL uniquement)
// ─────────────────────────────────────────────────────────────

/**
 * ⚠ F1 — LSR n'admet QUE les comptes EOD (static ou trailing).
 * Apex propose deux modèles :
 *   - Intraday Trail : le seuil suit le pic d'équité EN TEMPS RÉEL, non réalisé
 *     inclus → INCOMPATIBLE, rejeté par F1.
 *   - EOD Trail      : le seuil ne se recalcule qu'à la clôture → COMPATIBLE.
 * Ne jamais instancier un compte Apex Intraday avec ce moteur.
 *
 * ⚠ Les montants ci-dessous sont des ordres de grandeur publics et changent
 * régulièrement. VÉRIFIER sur le site Apex le jour de l'achat et corriger ici.
 * Rappel : depuis mars 2026, Apex ne propose plus de reset — un breach impose
 * le rachat d'une évaluation.
 */
export interface ApexEodPreset {
  readonly label: string;
  readonly initialCapital: number;
  readonly maxDrawdown: number;      // distance au seuil EOD
  readonly dailyLossLimit: number;   // DLL — pause la journée, ne tue pas le compte
  readonly profitTarget: number;
}

export const APEX_EOD_50K: ApexEodPreset = {
  label: 'Apex EOD Trail 50K (À VÉRIFIER)',
  initialCapital: 50_000,
  maxDrawdown: 2_500,
  dailyLossLimit: 1_000,
  profitTarget: 3_000,
};

/** Construit un AccountState de départ à partir d'un preset Apex EOD. */
export function apexEodAccount(preset: ApexEodPreset, currentEquity?: number, dayStartEquity?: number): AccountState {
  const equity = currentEquity ?? preset.initialCapital;
  const dayStart = dayStartEquity ?? equity;
  const floor = preset.initialCapital - preset.maxDrawdown;
  return {
    accountType: 'EOD_TRAILING',
    initialCapital: preset.initialCapital,
    currentEquity: equity,
    dayStartEquity: dayStart,
    drawdownFloor: floor,
    campaignFloor: floor,
    dailyLossLimit: preset.dailyLossLimit,
  };
}
