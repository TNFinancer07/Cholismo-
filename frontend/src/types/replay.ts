/** État du mode Replay — miroir exact de `ReplayState.as_dict()` (backend `datasource/replay.py`).
 *
 *  `total` et `clock` sont `number | null` PAR LE TYPE : tant que le fichier n'est pas indexé
 *  ils sont inconnus, et un `0` par défaut ferait afficher « 0 tick » là où la vérité est
 *  « pas encore su ». Même discipline que `bid_vol` côté moteur (D-055). */
export interface ReplayState {
  /** L'état en une ligne, déjà formaté côté serveur — une seule source de vérité pour ce texte. */
  resume: string
  filepath: string
  playing: boolean
  speed: number
  position: number
  total: number | null
  clock: number | null
  first_ts: number | null
  last_ts: number | null
  /** Décalage appliqué aux horodatages publiés (le fichier est rebasé sur maintenant). */
  offset: number
  finished: boolean
  /** Toujours `replay` : la source s'annonce, elle ne se fait pas passer pour du direct. */
  source: string
  skipped: number
  skipped_reasons: Record<string, number>
}

/** Une commande à la fois, explicitement nommée — un « set » générique laisserait passer
 *  `speed: 0`, qui est une pause qui ne dit pas son nom. */
export type ReplayCommand =
  | { action: 'play' }
  | { action: 'pause' }
  | { action: 'restart' }
  | { action: 'speed'; speed: number }
  | { action: 'seek'; position?: number; ts?: number; fraction?: number }
