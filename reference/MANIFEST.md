# /reference/ — MANIFEST

> Règle (`CLAUDE.md §11`) : les artifacts de ce dossier sont des **maquettes**. Seuls les blocs
> listés ici comme `AUTORITÉ` peuvent être extraits comme logique métier canonique. Tout le
> reste est `PLACEHOLDER` : inspiration UI uniquement, jamais de la logique métier.

## État actuel

**Aucun artifact `/reference/` n'a été fourni dans ce dépôt** (dépôt initialisé vide).
Conséquence, appliquée fail-closed :

| Bloc | Statut | Conséquence |
|---|---|---|
| Arbres conditionnels du chat Mode Live | `PLACEHOLDER` (absent) | Non implémentés comme logique canonique ; refus VIX>30 / CHOP≥61.8 codé en dur depuis `PRD §Vues par mode` uniquement. |
| Formules Q7/Q8 | `PLACEHOLDER` (jamais résolues, cf. `CLAUDE §11`) | Non implémentées. |
| Prompts / contextes (onglet 6 blocs) | `PLACEHOLDER` (absent) | L'onglet affiche des gabarits explicitement marqués `PLACEHOLDER — à remplacer par les blocs AUTORITÉ de /reference/`. Rien d'inventé n'est présenté comme canonique. |
| Formules de scoring (Structure/OrderFlow/Sentiment/Quality) | `PLACEHOLDER` | Implémentées isolées, commentées `v1 provisional`, consignées dans `DECISIONS.md`. |
| `compute_s2_macro_score()` | `AUTORITÉ` (squelette donné dans `PRD §A3`) | Implémentée telle que spécifiée : `CALIBRATED=False` par défaut, retourne `None`, ne pilote rien. |
| Poids du signal unifié 35/25/20/15/5 + renormalisation /80 | `AUTORITÉ` (`PRD §0`) | Implémentés tels quels. |
| Seuils `CHOP≥61.8` crit · `VIX>30` crit · `RMS≥3` warn/crit · GEX stale 180 s · audit streak à 8 · countdown 90 s · N/60 · 50+ trades · result score à 20+ | `AUTORITÉ` (`TASKS §2.3`, `PRD §B2/§C/§D`) | Implémentés tels quels, constantes nommées dans `backend/app/config.py`. |
| Grammaire event store (DecisionEvent/OutcomeEvent/ReconEvent, append-only, projections) | `AUTORITÉ` (`PRD §Zone D`) | Implémentée telle quelle. |

> Quand des artifacts `/reference/` seront ajoutés, classer ici **chaque bloc** `AUTORITÉ` vs
> `PLACEHOLDER` avant toute extraction, et mettre à jour `DECISIONS.md`.
