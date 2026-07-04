# DECISIONS.md — Hypothèses & décisions d'implémentation

> Journal exigé par `CLAUDE.md §11/§12`. Chaque formule non figée est isolée et marquée
> `v1 provisional`. Statut : `AUTORITÉ` = extrait tel quel de la spec ; `PLACEHOLDER` =
> hypothèse d'implémentation, révisable, ne fait pas autorité métier.

## D-000 · Inspiration design — lignée des grands terminaux financiers
Demande explicite de l'opérateur : « s'inspirer grandement des plus grands logiciels de
finance » (Bloomberg Terminal, Refinitiv Eikon, FactSet, ICE Data Services, BlackRock
Aladdin, Murex, Calypso). Traduction concrète, sans violer `PRD §Rendu transverse` :

- **Bloomberg Terminal** — fond noir profond, ambre/or réservé au Router (bordure/trait),
  densité maximale, chiffres monospace, barre de statut supérieure, **barre de touches de
  fonction en bas d'écran** (raccourcis clavier affichés en permanence), panneaux titrés par
  mnémonique (`B4 · SIGNAL UNIFIÉ`).
- **Refinitiv Eikon / FactSet** — espace de travail en tuiles liées : chaque panneau est une
  projection du même `ContextSchema` (les vues sont liées par construction, pas par câblage).
- **ICE Data Services** — indicateurs de qualité de donnée de première classe : badge
  `FRESH/STALE/ABSENT` + âge réel sur chaque champ (`meta`), jamais de valeur sans pedigree.
- **BlackRock Aladdin** — « one language of risk » : un seul schéma source de vérité,
  le risque encodé de façon redondante (couleur + forme + position), état maître global.
- **Murex / Calypso** — cycle de vie événementiel : le Decision Log est un blotter
  event-sourced append-only, l'état courant est une projection rejouée (grammaire imposée
  par `CLAUDE §2.5`, ici assumée jusque dans l'UI : colonnes de blotter, horodatage, audit).

## D-001 · /reference/ absent → tout est PLACEHOLDER
Aucun artifact `/reference/` fourni. `reference/MANIFEST.md` classe fail-closed : seuls les
blocs donnés **dans** `PRD.md`/`TASKS.md`/`CLAUDE.md` sont `AUTORITÉ`. Aucun arbre
conditionnel de chat, aucun prompt n'est présenté comme canonique.

## D-002 · Redis obligatoire, SQLite fichier local
Redis porte l'état intra-session (état sources, countdown C3, streak, scénario actif).
SQLite (`backend/data/events.db`) porte l'event store append-only + checkpointing.
En docker-compose, Redis est un service ; en dev local, `REDIS_URL` pointe un serveur local.
Fail-closed : si Redis est indisponible, Phase 0 = `BLOCKED` (dépendance down, `CLAUDE §2.2`).

## D-003 · Append-only imposé par le moteur, pas par convention (`AUTORITÉ` §Zone D)
Triggers SQLite `BEFORE UPDATE`/`BEFORE DELETE` → `RAISE(ABORT)` sur la table `events`.
Aucun chemin de code ne fait UPDATE/DELETE ; même un bug ne le pourrait pas.

## D-004 · Champ `instrument` ajouté à DecisionEvent (`PLACEHOLDER` raisonné)
`PRD §Réconciliation` matche « par timestamp + instrument » : le DecisionEvent doit donc
porter l'instrument (`ES`, `NQ`, `EURUSD`). Ajout au payload de l'event (le schéma d'event
du PRD liste les champs minimaux, pas exhaustifs).

## D-005 · Règles Phase 0 v1 (`PLACEHOLDER` sauf seuils `AUTORITÉ`)
Moteur déterministe = liste ordonnée de prédicats booléens purs, fail-closed :
- `DATA_FRESH` — tous les blocs du canal rapide `FRESH` (source down/lente → BLOQUÉ). AUTORITÉ (`CLAUDE §2.2/2.3`).
- `VIX_LIMIT` — `vix ≤ 30`. Seuil AUTORITÉ.
- `CHOP_LIMIT` — `chop < 61.8`. Seuil AUTORITÉ.
- `RMS_LIMIT` — `rms < 5` bloque (crit) ; `rms ≥ 3` = warning affiché sans blocage.
  Interprétation de « RMS≥3 warn/crit » (TASKS 2.3) : warn à 3, crit à 5. PLACEHOLDER.
- `SESSION_WINDOW` — `session_marker ≠ HORS_SESSION`. PLACEHOLDER (fenêtres §D-006).
- `STREAK_AUDIT` — `streak < 8` ou audit acquitté (C2). Seuil 8 AUTORITÉ.
- `REDIS_UP` / `ENGINE_FRESH` — le moteur lui-même doit avoir évalué < 5 s, sinon BLOQUÉ.
Groq est **advisory uniquement** : son avis est affiché, jamais dans le verrou ; timeout
> 100 ms → avis `UNAVAILABLE` et Phase 0 inchangée (le verrou reste les booléens).

## D-006 · Fenêtres de session (`PLACEHOLDER`)
`LONDRES_OBS` = 08:00–12:00 CET · `OVERLAP_NY` = 14:30–17:30 CET · sinon `HORS_SESSION`.
À valider par les opérateurs.

## D-007 · Formules de scoring v1 provisional (`PLACEHOLDER`)
`Structure`, `OrderFlow`, `Sentiment`, `Quality` : fonctions pures isolées dans
`backend/app/scoring.py`, commentées `v1 provisional`, bornées 0–100. Les **poids**
35/25/20/15/5 et la renormalisation /80 si macro non calibrée sont `AUTORITÉ` (`PRD §0`).
`compute_s2_macro_score()` : implémentée selon le squelette `PRD §A3`, `CALIBRATED=False`
par défaut (variable d'env `MACRO_CALIBRATED`), retourne `None`, contribution live = 0.

## D-008 · Déclenchement de la fenêtre de décision C3 (`PLACEHOLDER`)
La décision passe `PENDING` (et le countdown 90 s démarre) quand : mode `LIVE` **et**
Phase 0 `OPEN` **et** score unifié ≥ `DECISION_ARM_THRESHOLD` (60) **et** pas de décision
déjà pendante. Hors mode LIVE, aucune fenêtre ne s'arme (ni auto ni manuelle) — sinon le
log se remplirait de timeouts SYSTEM en pré/post-session. Expiration
→ event `NO_GO reason=timeout` écrit par le backend (jamais d'entrée forcée). L'opérateur
peut aussi armer manuellement. `ANTIPARALYSIS_SECONDS = 90` (constante, à revalider vs
horizon SVS/S1 — note `PRD §C3`).

## D-009 · Verdict sync S1↔S2 (`PLACEHOLDER`)
`ALIGNED` si signe(CVD S1) == signe(biais EUR/USD cascade) et les deux `FRESH` ;
`PARTIAL` si un des deux `STALE`/non calibré ; `DIVERGENT` sinon. Calculé backend partagé.

## D-010 · C4 deux jauges, validation séquentielle impossible (`AUTORITÉ` interprétée)
Jauge **quantitative** (N trades réconciliés / 60, Sharpe ≥ 0 après 20+) et jauge
**comportementale** (100 % des GO avec self-check, 100 % des décisions réconciliées, audits
streak acquittés) sont calculées par des projections **indépendantes** de l'event store ;
aucune API ne permet de « valider » l'une via l'autre — c'est structurel, pas procédural.
Sizing verrouillé à 50 % tant que les deux jauges ne sont pas au vert ensemble.

## D-011 · shadcn/ui — composants au standard shadcn, générés dans le repo
Composants UI (`button`, `badge`, `card`, `dialog`, `slider`, …) écrits dans
`frontend/src/components/ui/` selon les conventions shadcn (cva + tailwind-merge + slots),
sans CLI (environnement hors-ligne). `components.json` présent pour compat future.

## D-012 · Pathologies mock (`AUTORITÉ` `CLAUDE §4`, calibrage PLACEHOLDER)
`MockDataSource` injecte en continu, avec probabilités par scénario : ticks manquants
(drop), retards (latence 2–15 s → STALE réel), valeurs contradictoires entre deux
sous-sources (spread anormal + flag), NaN (rendu ABSENT, jamais 0), désync d'horloge
(offset ±20 s sur `last_update_ts` d'une source). Coupure manuelle par source via API pour
vérifier STALE/ABSENT (TASKS 2.4).

## D-013 · Sharpe (`PLACEHOLDER` de calcul, gate AUTORITÉ)
Sharpe = mean(r_multiples)/stdev(r_multiples) × √N par session, calculé **uniquement** sur
les `OutcomeEvent` référençant un `DecisionEvent` réconcilié (`matched=true`). Result score
affiché seulement à 20+ trades (`CLAUDE §2.7`), sinon `N/A (< 20 trades)`.

## D-014 · IA hors hot path — stubs câblés, clés absentes = fail-closed
Groq/Claude/Gemini : clients async isolés (`backend/app/ai/`), jamais appelés dans le
chemin de décision. Sans clé API : Groq advisory → `UNAVAILABLE` (Phase 0 inchangée),
scoring Claude et audit Gemini → jobs marqués `SKIPPED_NO_KEY` et loggés. Budgets/coûts
loggés dans `ai_calls` (SQLite, append-only aussi).

## D-015 · Un opérateur par instance (AUTORITÉ `CLAUDE §9`)
`VITE_OPERATOR` (ou `?operator=YOUSSEF`) fixe l'instance ; défaut `SONY`. Tous les events
portent `operator`.
