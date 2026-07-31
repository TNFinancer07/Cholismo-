/** Garde d'entrée des projections REST (Zone D, C4, orchestrateur).
 *
 *  **Cause racine du bug D-053-bis.** `refreshProjections` castait les corps de réponse
 *  (`as Calibration`, `as unknown as BlotterRow[]`) avant de les pousser dans le store. Un cast
 *  TypeScript est **effacé à l'exécution** : il ne vérifie rien. Un backend qui redémarre répond
 *  200 avec un corps partiel, le store se retrouvait à violer son propre type, et le premier
 *  consommateur qui faisait confiance au type LEVAIT — panneau disparu, aucun message.
 *
 *  Ces fonctions ne valident pas un schéma complet : elles vérifient **exactement ce que les
 *  consommateurs indexent**. Une forme inexploitable rend `null` — une projection tronquée est
 *  une projection ABSENTE (§3), jamais une valeur reconstituée.
 */
import type { ScenarioInfo } from '@/store/terminal'
import type { BlotterRow, Calibration, OrchestratorPayload } from '@/types/schema'

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x)
}

/** C4 indexe `quantitative.*`, `behavioral.*` et `sharpe.min_trades` : les trois doivent exister. */
export function asCalibration(payload: unknown): Calibration | null {
  if (!isRecord(payload)) return null
  if (!isRecord(payload.quantitative) || !isRecord(payload.behavioral)) return null
  if (!isRecord(payload.sharpe)) return null
  return payload as unknown as Calibration
}

/** Zone D itère la liste : sans tableau, il n'y a pas de log à afficher. */
export function asBlotterRows(payload: unknown): BlotterRow[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.decisions)) return null
  return payload.decisions as unknown as BlotterRow[]
}

/** La console orchestrateur et la vue LIVE font `Object.entries(orchestrator.sources)`. */
export function asOrchestrator(payload: unknown): OrchestratorPayload | null {
  if (!isRecord(payload) || !isRecord(payload.sources)) return null
  return payload as unknown as OrchestratorPayload
}

/** Le panneau MOCK fait `scenario.available.map(...)` puis lit `scenario.current.*` : les deux
 *  doivent exister. Même défaut que C4 — `scenario?.available` protège du `null`, pas du `{}`. */
export function asScenario(payload: unknown): ScenarioInfo | null {
  if (!isRecord(payload)) return null
  if (!isRecord(payload.current) || !Array.isArray(payload.available)) return null
  return payload as unknown as ScenarioInfo
}

/** `sources` est un dictionnaire nom → {up, fields} ; le panneau l'itère avec Object.entries. */
export function asSources(payload: unknown): Record<string, { up: boolean; fields: string[] }> | null {
  return isRecord(payload) ? (payload as Record<string, { up: boolean; fields: string[] }>) : null
}
