/**
 * decisionLog.ts — point d'entrée unique appelé à l'armement (approche du
 * niveau + Sweep), assemblant O1-O5 pour le journal de décision.
 * ==============================================================================
 * Cholismo · Pont Options -> LSR v2 · Fast Engine
 *
 * Appelé UNE FOIS par armement, après le calcul de la géométrie (entrée,
 * stop, TP) — cohérent avec la cadence déjà spécifiée : O1/O2 relus à
 * chaque armement, O3 après la géométrie, O4 synchrone avec le balayage.
 *
 * Aucune valeur retournée par cette fonction n'a de sens booléen bloquant.
 * `OptionsGatesLogEntry` n'a pas de champ `blocked` ni `allowed` — il n'y
 * a rien à vérifier avant d'exécuter le trade. La fonction existe pour
 * remplir le journal, pas pour être testée par un `if`.
 */

import { getOptionsContextSnapshot, type OptionsContextSnapshot } from './optionsContext';
import { evaluateO1, evaluateO2, evaluateO3, evaluateO4, type O1Result, type O2Result, type O3Result, type O4Result, type Side } from './gatesO1toO4';
import { evaluateO5, type O5Result, type PriceBar, O5_CONFIG_PLACEHOLDER, type O5Config } from './o5TailRisk';

export interface OptionsGatesLogEntry {
  readonly o1: O1Result;
  readonly o2: O2Result;
  readonly o3: O3Result;
  readonly o4: O4Result;
  /** O5 ne dépend jamais du contexte Redis — calcul local, zéro dépendance fournisseur. */
  readonly o5: O5Result;
  readonly contextHealth: OptionsContextSnapshot['health'];
  readonly timestamp: number;
}

export interface EvaluateOptionsGatesParams {
  readonly level: number;
  readonly side: Side;
  readonly entryPrice: number;
  readonly targetPrice: number;
  /** Buffer local de barres ES, tenu par le Fast Engine — indépendant de Redis. */
  readonly esBars: readonly PriceBar[];
  readonly o5Config?: O5Config;
  readonly now?: number;
}

/**
 * Point d'appel unique à l'armement. Ne lève jamais : chaque sous-évaluateur
 * est déjà fail-closed sur ses propres entrées invalides ; cette fonction
 * n'ajoute aucune logique susceptible d'échouer au-delà de la lecture pure
 * du cache local (getOptionsContextSnapshot, garanti sans I/O).
 */
export function evaluateOptionsGates(params: EvaluateOptionsGatesParams): OptionsGatesLogEntry {
  const now = params.now ?? Date.now();
  const snapshot = getOptionsContextSnapshot(now);

  const o1 = evaluateO1(snapshot, params.level, params.side);
  const o2 = evaluateO2(snapshot, params.entryPrice);
  const o3 = evaluateO3(snapshot, params.entryPrice, params.targetPrice, params.side);
  const o4 = evaluateO4(snapshot, params.side, params.level, now);
  const o5 = evaluateO5(params.esBars, params.o5Config ?? O5_CONFIG_PLACEHOLDER, now);

  return {
    o1,
    o2,
    o3,
    o4,
    o5,
    contextHealth: snapshot.health,
    timestamp: now,
  };
}

/**
 * Aplatit l'entrée en colonnes pour l'export CSV, à la suite des 30
 * colonnes existantes des contrôles fail-fast. Pure, ne touche à rien
 * d'autre que la mise en forme.
 */
export function toCsvColumns(entry: OptionsGatesLogEntry): Record<string, string | number> {
  return {
    context_health: entry.contextHealth,
    o1_status: entry.o1.status,
    o1_gex_local: entry.o1.gexLocal ?? '',
    o2_status: entry.o2.status,
    o2_distance_ticks: entry.o2.distanceTicks ?? '',
    o3_status: entry.o3.status,
    o3_obstacle_level: entry.o3.obstacleLevel ?? '',
    o4_status: entry.o4.status,
    o4_direction: entry.o4.direction ?? '',
    o5_status: entry.o5.status,
    o5_excess_kurtosis: entry.o5.excessKurtosis ?? '',
    o5_skewness: entry.o5.skewness ?? '',
    o5_variance: entry.o5.variance ?? '',
    o5_dominant_residual_share: entry.o5.dominantResidualShare ?? '',
    o5_sample_size: entry.o5.sampleSize,
  };
}
