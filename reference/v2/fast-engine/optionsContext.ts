/**
 * optionsContext.ts — lecture du contexte options publié par options_worker.py
 * ==============================================================================
 * Cholismo · Pont Options -> LSR v2 · Fast Engine
 *
 * Règle de conception unique, non négociable, vérifiée par mesure :
 * une lecture locale coûte ~0,02 µs ; le moindre saut asynchrone en coûte
 * déjà ~130x plus, un aller-retour Redis réel un ou deux ordres de grandeur
 * de plus. AU MOMENT DE LA DÉCISION (armement), on lit une variable en
 * mémoire — jamais le réseau, jamais Redis directement.
 *
 * Le abonnement pub/sub tourne en tâche de fond, hors du chemin de décision.
 * getOptionsContextSnapshot() est synchrone, pure sur son paramètre `now`,
 * et ne peut par construction pas bloquer : elle ne fait aucun appel I/O.
 */

export type SnapshotHealth = 'OK' | 'STALE' | 'VENDOR_DOWN' | 'UNAVAILABLE';

/** Miroir exact du JSON publié par options_worker.py (ContextPublisher). */
export interface OptionsContextRaw {
  readonly status: 'OK' | 'VENDOR_DOWN';
  readonly gexLocalByStrike: Readonly<Record<string, number>>;
  readonly gammaZeroEs: number | null;
  readonly putWallEs: number | null;
  readonly callWallEs: number | null;
  readonly netDriftCrossover: {
    readonly direction: 'up' | 'down' | null;
    readonly ts: number | null;
    readonly sourceConfirmed: boolean;
  };
  readonly conversionFactorUsed: number | null;
  readonly computedAt: number;
  readonly sourceVendor: string;
  readonly consecutiveFailures?: number;
}

export interface OptionsContextSnapshot {
  readonly health: SnapshotHealth;
  readonly raw: OptionsContextRaw | null;
  readonly ageMs: number | null;
}

export const OPTIONS_CONTEXT_KEY = 'options:context:latest';
export const OPTIONS_UPDATE_CHANNEL = 'options:context:updated';

/** Au-delà de ce délai depuis computedAt, une donnée OK est traitée comme périmée. PLACEHOLDER. */
export const STALE_THRESHOLD_MS = 90_000;

// ---------------------------------------------------------------------------
// État module-level, injecté au sens large : mis à jour uniquement par
// startOptionsContextSubscriber (tâche de fond), jamais par les évaluateurs
// de gates. Un module de test peut ignorer entièrement le subscriber et
// appeler setOptionsContextForTest() pour injecter un état directement —
// c'est ainsi que les tests des gates O1-O4 restent purs, sans Redis.
// ---------------------------------------------------------------------------
let _cache: OptionsContextRaw | null = null;

/** Lecture synchrone, pure sur `now`. Ne fait jamais d'I/O. Ne lève jamais. */
export function getOptionsContextSnapshot(now: number = Date.now()): OptionsContextSnapshot {
  if (_cache === null) {
    return { health: 'UNAVAILABLE', raw: null, ageMs: null };
  }
  if (_cache.status === 'VENDOR_DOWN') {
    return { health: 'VENDOR_DOWN', raw: _cache, ageMs: now - _cache.computedAt };
  }
  const age = now - _cache.computedAt;
  if (age > STALE_THRESHOLD_MS) {
    return { health: 'STALE', raw: _cache, ageMs: age };
  }
  return { health: 'OK', raw: _cache, ageMs: age };
}

/** Réservé aux tests : injecte un état directement, sans Redis. */
export function setOptionsContextForTest(raw: OptionsContextRaw | null): void {
  _cache = raw;
}

function tryParse(raw: string): OptionsContextRaw | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'status' in parsed &&
      'computedAt' in parsed
    ) {
      return parsed as OptionsContextRaw;
    }
    return null;
  } catch {
    return null; // message malformé -> ignoré, le cache existant n'est pas touché
  }
}

export interface SubscriberHandle {
  readonly stop: () => Promise<void>;
}

/**
 * Contournement de typage : `redis@4.7.1` avec la config TS de ce projet
 * (moduleResolution Bundler + strict) ne fait pas apparaître `.on()` dans
 * le type inféré de `createClient()` — problème connu de résolution des
 * types génériques du package, pas une omission de notre part. Interface
 * minimale locale plutôt que d'affaiblir `strict` pour tout le fichier.
 */
interface MinimalErrorEmitter {
  on(event: 'error', listener: (err: unknown) => void): void;
}

/**
 * Démarre l'abonnement en tâche de fond. Ne lève JAMAIS vers l'appelant :
 * toute erreur de connexion, de souscription, ou de message malformé est
 * absorbée. En cas d'échec total, le cache reste `null` indéfiniment —
 * getOptionsContextSnapshot() renvoie alors UNAVAILABLE, ce que tous les
 * évaluateurs O1-O4 traitent comme une absence de donnée (fail-closed).
 * O5 n'est pas affecté : il ne dépend jamais de ce module.
 *
 * Import dynamique de 'redis' pour que ce module reste chargeable et
 * testable même sans la dépendance installée (les tests des gates purs
 * n'en ont pas besoin).
 */
export async function startOptionsContextSubscriber(
  redisUrl: string,
  onError?: (err: unknown) => void
): Promise<SubscriberHandle> {
  try {
    const { createClient } = await import('redis');

    const primer = createClient({ url: redisUrl, socket: { connectTimeout: 2000 } });
    (primer as unknown as MinimalErrorEmitter).on('error', (err) => onError?.(err));
    await primer.connect();
    try {
      const initial = await primer.get(OPTIONS_CONTEXT_KEY);
      if (initial) {
        const parsed = tryParse(initial);
        if (parsed) _cache = parsed;
      }
    } finally {
      await primer.disconnect().catch(() => {});
    }

    const sub = createClient({ url: redisUrl, socket: { connectTimeout: 2000 } });
    (sub as unknown as MinimalErrorEmitter).on('error', (err) => onError?.(err));
    await sub.connect();
    await sub.subscribe(OPTIONS_UPDATE_CHANNEL, (message) => {
      const parsed = tryParse(message);
      if (parsed) _cache = parsed;
      // message malformé : ignoré silencieusement, jamais de throw depuis
      // un callback de subscriber (cela ferait tomber tout le processus).
    });

    return {
      stop: async () => {
        await sub.unsubscribe(OPTIONS_UPDATE_CHANNEL).catch(() => {});
        await sub.disconnect().catch(() => {});
      },
    };
  } catch (err) {
    onError?.(err);
    // Échec total de connexion : le cache reste tel quel (probablement
    // null). Un handle no-op est renvoyé pour que l'appelant n'ait pas à
    // distinguer ce cas d'un abonnement réussi puis arrêté.
    return { stop: async () => {} };
  }
}
