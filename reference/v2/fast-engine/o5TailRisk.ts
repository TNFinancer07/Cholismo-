/**
 * Gate O5 · Tail risk caché — Cholismo / LSR v1.7 — v2
 * ======================================================
 * Extrait de la dimension macro D4 (voir cholismo_pont_options_lsr_v2.html,
 * section 10). Nommé O5, pas "D4" — voir README pour la justification
 * complète du nommage, déjà tranchée.
 *
 * CHANGEMENT DE RUPTURE PAR RAPPORT À v1 (o5TailRisk.v1.ts.bak) :
 * v1 acceptait un buffer de RENDEMENTS bruts (number[]). v2 accepte un
 * buffer de BARRES (timestamp + clôture) : nécessaire pour calculer des
 * log-returns, détecter les doublons/barres hors-ordre après reconnexion
 * Rithmic, et détecter les trous temporels. L'appelant doit migrer de
 * pushReturn(buffer, value, max) vers pushBar(buffer, bar, max).
 *
 * Fiches retenues et implémentées ici (issues du brainstorm d'optimisation,
 * toutes déjà validées avant cette écriture) :
 *   - Rendements en log-return plutôt qu'en différence de ticks
 *   - Détection des barres dupliquées / hors-ordre après reconnexion
 *   - Détection des trous temporels -> nouveau statut O5_DATA_GAP
 *   - Diagnostic d'attribution (quelle barre domine le moment d'ordre 4)
 *   - Journal enrichi : skewness, variance, en plus du kurtosis
 *
 * Explicitement rejeté (voir brainstorm) : calcul incrémental type
 * Welford/West, buffer en Float64Array, lissage du kurtosis par moyenne
 * mobile, fenêtre adaptative par période de séance. Mesuré et documenté :
 * gain nul ou négatif, ou destruction du signal recherché.
 *
 * Invariants d'architecture inchangés depuis v1 :
 *   - Fonctions pures, état injecté.
 *   - Fail-closed : toute donnée absente, insuffisante, dupliquée, trouée
 *     ou dégénérée produit un statut consultatif explicite — jamais PASS
 *     par défaut.
 *   - Mode G2 : ne lève jamais. Aucune fonction de ce fichier ne retourne
 *     de booléen bloquant — uniquement des objets de statut journalisés.
 *     Ce n'est pas un choix de configuration désactivable : il n'existe
 *     structurellement aucun chemin de blocage à réactiver par erreur.
 *   - PLACEHOLDER explicite sur tout seuil non calibré.
 */

export type O5Status =
  | 'PASS'
  | 'FLAG_HIDDEN_TAIL'
  | 'O5_SAMPLE_TOO_SMALL'
  | 'O5_DATA_GAP';

export interface PriceBar {
  readonly timestamp: number; // ms epoch, horodatage de clôture de la barre
  readonly close: number;     // prix de clôture (ES, points)
}

export interface O5Config {
  /** Nombre de barres dans la fenêtre glissante (-> windowSize-1 rendements). PLACEHOLDER. */
  readonly windowSize: number;
  /** Nombre minimal de RENDEMENTS (pas de barres) avant tout calcul. PLACEHOLDER. */
  readonly minSamples: number;
  /** Seuil d'excess kurtosis. PLACEHOLDER. Convention : excess = m4/m2² − 3. */
  readonly kurtosisThreshold: number;
  /** Écart maximal toléré entre deux barres consécutives (ms) avant O5_DATA_GAP. PLACEHOLDER. */
  readonly maxBarGapMs: number;
  readonly isPlaceholder: true;
}

export const O5_CONFIG_PLACEHOLDER: O5Config = {
  windowSize: 121,       // 121 barres -> 120 rendements, cohérent avec la spec d'origine
  minSamples: 30,
  kurtosisThreshold: 6.0,
  maxBarGapMs: 90_000,   // 90 s pour des barres nominales 1 min — tolère une barre manquée, pas deux
  isPlaceholder: true,
};

export interface O5Result {
  readonly status: O5Status;
  readonly excessKurtosis: number | null;
  /** Asymétrie de la distribution — m3/m2^1.5. Contexte, n'influence jamais le statut. */
  readonly skewness: number | null;
  /** Variance des log-returns sur la fenêtre. Contexte pour la calibration. */
  readonly variance: number | null;
  /** Part du moment d'ordre 4 total portée par le résidu le plus extrême, dans [0,1]. */
  readonly dominantResidualShare: number | null;
  readonly sampleSize: number;
  readonly timestamp: number;
  readonly configUsed: O5Config;
}

export interface PushBarResult {
  readonly buffer: readonly PriceBar[];
  readonly accepted: boolean;
  readonly reason?: 'duplicate' | 'out_of_order';
}

/**
 * Ajoute une barre au buffer glissant. Fonction pure. Rejette toute barre
 * dont l'horodatage n'est pas strictement postérieur à la dernière connue —
 * protection contre un replay de reconnexion Rithmic qui renverrait une
 * barre déjà vue (double-poids silencieux d'un mouvement, potentiellement
 * extrême). Ne lève jamais ; le rejet est signalé dans le résultat, à
 * l'appelant de compter les rejets s'il le souhaite (état tenu par
 * l'appelant, cohérent avec le principe d'état injecté).
 */
export function pushBar(
  buffer: readonly PriceBar[],
  bar: PriceBar,
  maxSize: number
): PushBarResult {
  const last = buffer[buffer.length - 1];
  if (last !== undefined) {
    if (bar.timestamp === last.timestamp) {
      return { buffer, accepted: false, reason: 'duplicate' };
    }
    if (bar.timestamp < last.timestamp) {
      return { buffer, accepted: false, reason: 'out_of_order' };
    }
  }
  const next = [...buffer, bar];
  const trimmed = next.length > maxSize ? next.slice(next.length - maxSize) : next;
  return { buffer: trimmed, accepted: true };
}

/**
 * Convertit une série de barres en log-returns : ln(closeₜ / closeₜ₋₁).
 * Suppose les barres triées par timestamp croissant (garanti par pushBar).
 * Retourne NaN pour toute transition invalide (prix non positif ou non
 * fini) plutôt que de lever — evaluateO5 traite tout NaN comme un
 * échantillon invalide.
 */
export function toLogReturns(bars: readonly PriceBar[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const prevBar = bars[i - 1];
    const curBar = bars[i];
    if (prevBar === undefined || curBar === undefined) {
      out.push(NaN);
      continue;
    }
    const prev = prevBar.close;
    const cur = curBar.close;
    if (!Number.isFinite(prev) || !Number.isFinite(cur) || prev <= 0 || cur <= 0) {
      out.push(NaN);
      continue;
    }
    out.push(Math.log(cur / prev));
  }
  return out;
}

/** Détecte un écart temporel entre deux barres consécutives dépassant maxGapMs. */
export function hasTemporalGap(bars: readonly PriceBar[], maxGapMs: number): boolean {
  for (let i = 1; i < bars.length; i++) {
    const prevBar = bars[i - 1];
    const curBar = bars[i];
    if (prevBar === undefined || curBar === undefined) continue;
    if (curBar.timestamp - prevBar.timestamp > maxGapMs) return true;
  }
  return false;
}

interface Moments {
  readonly mean: number;
  readonly variance: number;      // m2
  readonly skewness: number;      // m3 / m2^1.5
  readonly excessKurtosis: number; // m4/m2² − 3
  readonly dominantResidualShare: number; // max(d⁴) / Σd⁴
}

/**
 * Calcule mean/variance/skewness/excess kurtosis/attribution du résidu
 * dominant en un seul passage sur les données (plus un second pour les
 * sommes centrées — deux passes, numériquement stable, coût négligeable
 * mesuré : voir le brainstorm de performance, ~1.3 µs pour n=120).
 * Retourne null si la série est dégénérée (variance nulle), vide, ou
 * contient une valeur non finie.
 */
function computeMoments(returns: readonly number[]): Moments | null {
  const n = returns.length;
  if (n === 0) return null;

  let sum = 0;
  for (const r of returns) {
    if (!Number.isFinite(r)) return null;
    sum += r;
  }
  const mean = sum / n;

  let m2 = 0;
  let m3 = 0;
  let m4 = 0;
  let maxD4 = 0;
  for (const r of returns) {
    const d = r - mean;
    const d2 = d * d;
    const d3 = d2 * d;
    const d4 = d2 * d2;
    m2 += d2;
    m3 += d3;
    m4 += d4;
    if (d4 > maxD4) maxD4 = d4;
  }
  m2 /= n;
  m3 /= n;
  m4 /= n;

  if (m2 === 0) return null;

  const variance = m2;
  const skewness = m3 / Math.pow(m2, 1.5);
  const excessKurtosis = m4 / (m2 * m2) - 3;
  const dominantResidualShare = m4 === 0 ? 0 : maxD4 / (m4 * n);

  return { mean, variance, skewness, excessKurtosis, dominantResidualShare };
}

/**
 * Évalue le gate O5 sur un buffer de barres.
 *
 * Garde-fous, dans l'ordre :
 *   1. Pas assez de barres pour former minSamples rendements -> O5_SAMPLE_TOO_SMALL
 *   2. Trou temporel dans la fenêtre                          -> O5_DATA_GAP
 *   3. Rendements non calculables (NaN) ou série dégénérée     -> O5_SAMPLE_TOO_SMALL
 *   4. Toute exception interne inattendue                      -> O5_SAMPLE_TOO_SMALL
 *   5. Sinon : comparaison stricte au seuil                     -> PASS | FLAG_HIDDEN_TAIL
 *
 * Ne lève jamais. Mode G2 : résultat consultatif, journalisé, ne doit
 * jamais interrompre la chaîne d'appel de lsr_engine.
 */
export function evaluateO5(
  bars: readonly PriceBar[],
  config: O5Config = O5_CONFIG_PLACEHOLDER,
  now: number = Date.now()
): O5Result {
  const empty = (status: O5Status, sampleSize: number): O5Result => ({
    status,
    excessKurtosis: null,
    skewness: null,
    variance: null,
    dominantResidualShare: null,
    sampleSize,
    timestamp: now,
    configUsed: config,
  });

  try {
    const minBarsNeeded = config.minSamples + 1;
    if (bars.length < minBarsNeeded) {
      return empty('O5_SAMPLE_TOO_SMALL', bars.length);
    }

    const window = bars.slice(-config.windowSize);

    if (hasTemporalGap(window, config.maxBarGapMs)) {
      return empty('O5_DATA_GAP', window.length);
    }

    const returns = toLogReturns(window);
    if (returns.length < config.minSamples) {
      return empty('O5_SAMPLE_TOO_SMALL', returns.length);
    }

    const moments = computeMoments(returns);
    if (moments === null || !Number.isFinite(moments.excessKurtosis)) {
      return empty('O5_SAMPLE_TOO_SMALL', returns.length);
    }

    return {
      status: moments.excessKurtosis > config.kurtosisThreshold ? 'FLAG_HIDDEN_TAIL' : 'PASS',
      excessKurtosis: moments.excessKurtosis,
      skewness: moments.skewness,
      variance: moments.variance,
      dominantResidualShare: moments.dominantResidualShare,
      sampleSize: returns.length,
      timestamp: now,
      configUsed: config,
    };
  } catch {
    // Fail-closed absolu : cohérent avec v1, jamais de propagation d'erreur.
    return empty('O5_SAMPLE_TOO_SMALL', bars.length);
  }
}
