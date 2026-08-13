/**
 * gatesO1toO4.ts — évaluateurs consultatifs des gates options
 * ================================================================
 * Cholismo · Pont Options -> LSR v2 · Fast Engine
 *
 * GARANTIE STRUCTURELLE, pas une configuration :
 * Chaque fonction de ce fichier retourne un objet de statut (`{ gate, status, ... }`).
 * Aucune ne retourne de booléen, aucune ne lève. Il n'existe nulle part dans
 * ce fichier de motif `if (!result) return null` ou `if (!gate.pass) block()`.
 * Il n'y a donc pas de « blocage désactivé » à réactiver par erreur — il n'y
 * a simplement aucun chemin de blocage. Mode G2 : consultatif, journalisé,
 * point final.
 *
 * Codes de statut repris tels que spécifiés dans
 * cholismo_pont_options_lsr_v2.html (section 5), sans réinvention.
 */

import type { OptionsContextSnapshot } from './optionsContext';

export type Side = 'LONG' | 'SHORT';

const TICK_ES = 0.25;

// ---------------------------------------------------------------------------
// O1 — régime gamma local, signé par le côté du trade (asymétrie établie
// dans le Pont v2, section 3 : un LONG en régime négatif est la
// configuration la plus défavorable des quatre combinaisons possibles).
// ---------------------------------------------------------------------------

export type O1Status = 'PASS' | 'FLAG_WEAK' | 'FLAG_STRONG' | 'O1_REGIME_INDETERMINE' | 'O1_DATA_UNAVAILABLE';

export interface O1Result {
  readonly gate: 'O1';
  readonly status: O1Status;
  readonly gexLocal: number | null;
  readonly nearestStrike: number | null;
}

/** Seuil de significativité du GEX local — en dessous, le régime est bruit, pas signal. PLACEHOLDER. */
export const O1_SIGNIFICANCE_THRESHOLD = 30; // M$/1%, ordre de grandeur illustratif

function findNearestStrikeGex(
  map: Readonly<Record<string, number>>,
  level: number
): { strike: number; gex: number } | null {
  let best: { strike: number; gex: number } | null = null;
  let bestDist = Infinity;
  for (const key of Object.keys(map)) {
    const strike = Number(key);
    if (!Number.isFinite(strike)) continue;
    const dist = Math.abs(strike - level);
    if (dist < bestDist) {
      bestDist = dist;
      best = { strike, gex: map[key]! };
    }
  }
  return best;
}

export function evaluateO1(
  snapshot: OptionsContextSnapshot,
  level: number,
  side: Side
): O1Result {
  if (snapshot.health !== 'OK' || snapshot.raw === null) {
    return { gate: 'O1', status: 'O1_DATA_UNAVAILABLE', gexLocal: null, nearestStrike: null };
  }
  const nearest = findNearestStrikeGex(snapshot.raw.gexLocalByStrike, level);
  if (nearest === null) {
    return { gate: 'O1', status: 'O1_DATA_UNAVAILABLE', gexLocal: null, nearestStrike: null };
  }

  const { strike, gex } = nearest;

  if (Math.abs(gex) <= O1_SIGNIFICANCE_THRESHOLD) {
    return { gate: 'O1', status: 'O1_REGIME_INDETERMINE', gexLocal: gex, nearestStrike: strike };
  }

  if (gex > 0) {
    return { gate: 'O1', status: 'PASS', gexLocal: gex, nearestStrike: strike };
  }

  // gex < 0 : régime négatif — asymétrie par côté
  return {
    gate: 'O1',
    status: side === 'LONG' ? 'FLAG_STRONG' : 'FLAG_WEAK',
    gexLocal: gex,
    nearestStrike: strike,
  };
}

// ---------------------------------------------------------------------------
// O2 — zone d'exclusion autour du gamma zero (HVL). Symétrique par
// construction : ni LONG ni SHORT n'est privilégié près du point où le
// mécanisme est éteint.
// ---------------------------------------------------------------------------

export type O2Status = 'PASS' | 'FLAG_EXCLUSION_ZONE' | 'O2_FLIP_UNKNOWN';

export interface O2Result {
  readonly gate: 'O2';
  readonly status: O2Status;
  readonly distanceTicks: number | null;
}

/** ≈ 1,2x le stop LSR de 10 ticks. PLACEHOLDER, non calibré. */
export const O2_EXCLUSION_TICKS = 12;

export function evaluateO2(snapshot: OptionsContextSnapshot, entryPrice: number): O2Result {
  if (snapshot.health !== 'OK' || snapshot.raw === null || snapshot.raw.gammaZeroEs === null) {
    return { gate: 'O2', status: 'O2_FLIP_UNKNOWN', distanceTicks: null };
  }
  const distanceTicks = Math.abs(entryPrice - snapshot.raw.gammaZeroEs) / TICK_ES;
  return {
    gate: 'O2',
    status: distanceTicks >= O2_EXCLUSION_TICKS ? 'PASS' : 'FLAG_EXCLUSION_ZONE',
    distanceTicks,
  };
}

// ---------------------------------------------------------------------------
// O3 — obstacle géométrique entre l'entrée et l'objectif.
// LONG : le call wall ne doit pas se trouver strictement entre entrée et TP.
// SHORT : symétriquement pour le put wall.
// ---------------------------------------------------------------------------

export type O3Status = 'PASS' | 'FLAG_OBSTACLE' | 'O3_WALLS_UNKNOWN';

export interface O3Result {
  readonly gate: 'O3';
  readonly status: O3Status;
  readonly obstacleLevel: number | null;
}

/** Tolérance sur le franchissement, en ticks — marge pour l'incertitude de conversion. PLACEHOLDER. */
export const O3_TOLERANCE_TICKS = 1;

function isStrictlyBetween(x: number, a: number, b: number, toleranceTicks: number): boolean {
  const lo = Math.min(a, b) + toleranceTicks * TICK_ES;
  const hi = Math.max(a, b) - toleranceTicks * TICK_ES;
  return x > lo && x < hi;
}

export function evaluateO3(
  snapshot: OptionsContextSnapshot,
  entryPrice: number,
  targetPrice: number,
  side: Side
): O3Result {
  if (snapshot.health !== 'OK' || snapshot.raw === null) {
    return { gate: 'O3', status: 'O3_WALLS_UNKNOWN', obstacleLevel: null };
  }
  const wall = side === 'LONG' ? snapshot.raw.callWallEs : snapshot.raw.putWallEs;
  if (wall === null) {
    return { gate: 'O3', status: 'O3_WALLS_UNKNOWN', obstacleLevel: null };
  }
  const blocked = isStrictlyBetween(wall, entryPrice, targetPrice, O3_TOLERANCE_TICKS);
  return {
    gate: 'O3',
    status: blocked ? 'FLAG_OBSTACLE' : 'PASS',
    obstacleLevel: blocked ? wall : null,
  };
}

// ---------------------------------------------------------------------------
// O4 — alignement du Net Premium Drift. BLOCAGE DE PÉRIMÈTRE DOCUMENTÉ :
// la source n'est aujourd'hui confirmée que sur QQQ, pas sur SPY/SPX (voir
// Pont v2, section 4). Tant que `sourceConfirmed` est false — ce qui est
// systématiquement le cas avec les données actuellement disponibles —
// ce gate retourne O4_SOURCE_UNCONFIRMED avant toute autre logique. La
// logique d'alignement ci-dessous est prête, mais volontairement inerte
// tant que ce prérequis n'est pas résolu — ce n'est pas du code mort à
// supprimer, c'est du code qui attend une donnée qui n'existe pas encore.
// ---------------------------------------------------------------------------

export type O4Status =
  | 'PASS'
  | 'O4_NO_CONVICTION'
  | 'O4_NO_LOCATION'
  | 'O4_DATA_MISSING'
  | 'O4_SOURCE_UNCONFIRMED';

export interface O4Result {
  readonly gate: 'O4';
  readonly status: O4Status;
  readonly direction: 'up' | 'down' | null;
}

/** Fenêtre de fraîcheur du croisement, alignée sur F7 (anti-FOMO, 90s). PLACEHOLDER. */
export const O4_WINDOW_MS = 90_000;
/** Tolérance de coïncidence de lieu avec le niveau GEX pertinent. PLACEHOLDER. */
export const O4_LOCATION_TOLERANCE_TICKS = 4;

export function evaluateO4(
  snapshot: OptionsContextSnapshot,
  side: Side,
  level: number,
  now: number
): O4Result {
  if (snapshot.health !== 'OK' || snapshot.raw === null) {
    return { gate: 'O4', status: 'O4_DATA_MISSING', direction: null };
  }

  if (!snapshot.raw.netDriftCrossover.sourceConfirmed) {
    return { gate: 'O4', status: 'O4_SOURCE_UNCONFIRMED', direction: null };
  }

  const { direction, ts } = snapshot.raw.netDriftCrossover;
  if (direction === null || ts === null) {
    return { gate: 'O4', status: 'O4_NO_CONVICTION', direction: null };
  }

  const expectedDirection: 'up' | 'down' = side === 'LONG' ? 'up' : 'down';
  if (direction !== expectedDirection) {
    return { gate: 'O4', status: 'O4_NO_CONVICTION', direction };
  }

  if (now - ts > O4_WINDOW_MS) {
    return { gate: 'O4', status: 'O4_NO_CONVICTION', direction };
  }

  const relevantLevel = side === 'LONG' ? snapshot.raw.putWallEs : snapshot.raw.callWallEs;
  if (relevantLevel === null) {
    return { gate: 'O4', status: 'O4_NO_LOCATION', direction };
  }
  const distanceTicks = Math.abs(level - relevantLevel) / TICK_ES;
  if (distanceTicks > O4_LOCATION_TOLERANCE_TICKS) {
    return { gate: 'O4', status: 'O4_NO_LOCATION', direction };
  }

  return { gate: 'O4', status: 'PASS', direction };
}
