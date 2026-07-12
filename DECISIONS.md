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
  mnémonique (`B4 · SIGNAL UNIFIÉ`), **barre de commande** (`/` puis mnémonique + `⏎ <GO>` :
  `B4`, `LIVE`, `VIX`, `GO`, `HELP`…) — pure navigation/reflet : `GO`/`NOGO` passent par les
  mêmes verrous serveur que les boutons, aucun chemin privilégié — et **flashs de tick**
  vert/rouge sur les valeurs FRESH qui bougent.
- **Eikon / FactSet (bis)** — **sparklines** inline (SVG maison) sur score unifié, CVD,
  EUR/USD, VIX, GEX : historique volatil côté client des valeurs du schéma reçues par SSE,
  traçable au schéma, jamais une valeur inventée ni persistée.
- **Eikon (ter) — espaces de travail** : multi-layouts nommés (`DÉFAUT`, `MICRO · S1`,
  `MACRO · S2`, `DISCIPLINE` + duplicables en `PERSO n`), onglets sous la barre de statut,
  bascule touches `1-9` ou mnémoniques (`MICRO`, `WS1…`, `WS`, `WSRESET`), mode édition
  (déplacer ◀▲▼▶, masquer, renommer, blotter on/off), persistés en localStorage **par
  opérateur**. Un workspace ne fait que réarranger les panneaux du registre — chaque panneau
  reste traçable à un bloc du schéma (CLAUDE §1), aucune donnée créée, aucun verrou contourné.
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
Sharpe par trade = mean(r_multiples)/stdev(r_multiples) (écart-type échantillon, sans
annualisation), calculé **uniquement** sur les `OutcomeEvent` référençant un
`DecisionEvent` réconcilié (`matched=true`). Result score affiché seulement à 20+ trades
(`CLAUDE §2.7`), sinon `N/A (< 20 trades)`.

## D-014 · IA hors hot path — stubs câblés, clés absentes = fail-closed
Groq/Claude/Gemini : clients async isolés (`backend/app/ai/`), jamais appelés dans le
chemin de décision. Sans clé API : Groq advisory → `UNAVAILABLE` (Phase 0 inchangée),
scoring Claude et audit Gemini → jobs marqués `SKIPPED_NO_KEY` et loggés. Budgets/coûts
loggés dans `ai_calls` (SQLite, append-only aussi).

## D-021 · Les 5 stratégies réelles câblées visiblement (`AUTORITÉ` /reference/)
Les artefacts fournis par les opérateurs sont installés dans `/reference/` et classés dans
`MANIFEST.md` : **Sony ×2 exécution** (SVS — Structural Vacuum Squeeze, scoring v2.0 CHOP ;
Mean Reversion — Piège d'Absorption v5.8) et **Youssef ×3 analyse macro** (fondations/N2A,
N2B 7 blocs, N3-N5). Câblage :
- `s1_state.strategies` (canal rapide) — éligibilité SVS + MR : seuls les gates dont la
  donnée existe dans le schéma sont évalués (`PASS/FAIL/ABSENT` fail-closed) ; les gates
  sans source câblée sont affichés `MANUAL`, jamais devinés. Le SCORE lui-même reste chez
  l'opérateur — le terminal montre éligibilité + modificateurs de taille (VIX × session).
- `s2_state.pipeline` (canal lent) — régime D4 avec hystérésis « always-on » (mise à jour
  au tick rapide, publication à la cadence lente), quadrant Bridgewater + poids canoniques,
  N3 Flux 1 (renorm, tanh, gate fund, conviction, 4 horizons), Flux 2 (6 arbitrages).
- Extension additive du `ContextSchema` (v1.0 → champs `strategies`/`pipeline` optionnels) ;
  les nouveaux panneaux S1S/S2P tracent à ces blocs (CLAUDE §1 respecté).
- **Intrants simulés** : g/π, D1-D5 et les deltas d'arbitrage sont produits par le
  `MockDataSource` (simulation des sorties N1/N2A) tant qu'aucun feed réel n'existe. Les
  FORMULES aval sont AUTORITÉ ; les VALEURS d'entrée sont mock (couture unique, CLAUDE §4).
- **Conflits résolus** (consignés aussi dans MANIFEST) : table WEIGHTS par quadrant —
  fichier 1 (« canonique ») fait foi ; 6 arbitrages — fichier 3 (« fait foi ») ; échelle de
  conviction Arb1/2/3 non spécifiée → convention `min(|δ|/seuil×5, cap)` (Arb3 ×4) calquée
  sur les formules données pour Arb4/5/6. Version SVS : **tranché par l'opérateur — la
  désignation canonique est SVS v3.0** (le « v2.0 » de l'en-tête du document ne couvre que
  la matrice de scoring CHOP) ; le contenu du fichier (seuils, filtres, planchers) fait foi.
- Stack RMS du Mode Live : noms canoniques KillSwitch/CircuitBreaker/StrategyOverlay/
  RiskSizer/PortfolioRisk (MR §01b). Onglet Prompts : extraits réels des 5 artefacts.

## D-022 · Onglet JOURNAL — journal de trading event-sourced (`AUTORITÉ` /reference/journal)
L'app de référence (« Journal de Session — Sony & Youssef », React/localStorage) est
transposée en vue dédiée du terminal (`/` → `JOURNAL`, alias `JT`), en remplaçant son
stockage navigateur par la grammaire du terminal :
- **brouillon** de fiche = Redis (modifiable, supprimable — état de travail) ;
- **« Clôturer & verrouiller »** = entrée `trade_locked` **append-only** (SQLite,
  `journal_entries`, triggers RAISE ABORT identiques au Decision Log) — pas de « Rouvrir » :
  l'audit trail du terminal est réellement immuable, plus strict que l'app de référence ;
- règles de verrouillage du document appliquées serveur (422) : direction/type de sortie/
  résultat R/« SL respecté ? » obligatoires ; « SL non respecté ⇒ erreur Type A
  automatique » ; sortie précoce ⇒ justification (friction #2) ;
- sentiment pré/post par opérateur en Redis, figé dans l'entrée `session_closed` ;
- lockout « 2 pertes consécutives → pause 24 h » (couche KillSwitch) **dérivé**, affiché
  dans l'en-tête — non branché sur Phase 0 pour l'instant (candidat futur, à trancher) ;
- CHOP/VIX préremplis depuis le schéma live à la création de fiche (pedigree réel) ;
- webhooks n8n `trade_closed`/`session_closed` async + loggés dans `ai_calls` ;
  `trade_created`/`threshold_breached` et `field_updates` non implémentés (PLACEHOLDER).

## D-023 · Cockpit RECAP · Mode Live · Paramètres 2 étages (maquettes opérateur, PLACEHOLDER sauf mention)
Deux maquettes fournies par l'opérateur (« Brainstorm Récapitulatif + Paramètres » et
« Cholismo Cycle Automatisé Unifié ») sont implémentées comme **projections du terminal**,
pas recopiées : leurs arbres conditionnels restent des maquettes (§11), la logique vient
du schéma/event store existants.
- **RECAP** (vue `RECAP`) : pure projection (journal `trade_locked` + decision log +
  schéma). Arbitrages de la maquette respectés : hiérarchie réflexe/analyse ; seuls P&L et
  risque s'animent (lissés) ; **aucun toggle destructif dans la vue** (lecture gratuite,
  le danger se mérite) — armer/désarmer n'existe pas côté serveur, seul l'état + raison
  est affiché. Le « feu météo » réutilise l'arbitrage de la console (une seule source de
  vérité). P&L en R depuis le journal (vérité opérateur) × `risk.r_unit_usd` (D-018) ;
  risk-clock honnête : `null` tant qu'aucune perte n'a défini le rythme. Fenêtres
  SVS/MR = horloge Montréal des stratégies Sony (compte à rebours réel, pas de TTL inventé).
- **Mode Live** (vue `MODELIVE`) : lecture marché + dialogue **100 % déterministes côté
  serveur** (règles pures sur le schéma, <1 ms). La maquette suggérait un agent LLM ;
  CLAUDE §2.8 interdit tout LLM synchrone dans le hot path → le répondeur est un port
  des règles du mock sur les valeurs réelles, badgé ADVISORY, fail-closed sur données
  absentes, refus hors périmètre, conflits score/flux exposés, jamais d'override. Un
  étage LLM async (Groq/Claude) reste possible PLUS TARD, hors hot path, non requis.
  Cadence lecture = settings (`live.cycle_seconds` 180 s / 600 s hors fenêtre, cadence du
  mock) + event-driven sur franchissement de seuil côté client.
- **Paramètres** (vue `PARAMS`) : moteur 2 étages event-sourcé (`setting_events`
  append-only, mêmes triggers). Étage spécifique = par stratégie (`SVS`/`MEAN_REVERSION`) ;
  par instrument ES/NQ **non retenu** (un seul instrument câblé — honnêteté avant tout).
  Invariants serveur : AUTORITÉ verrouillé 409 (pondérations 35/25/20/15/5, CHOP 61.8,
  VIX 30, sizing 50 %, audit 8/20, budget Groq) ; risque réduit-seulement 422
  (spécifique ⊆ global, protection par construction) ; garde-fou 428 + ack explicite
  (seuil C3 < 50) ; écriture en LIVE 423 sauf déverrouillage explicite. Consommés
  réellement : `decision.arm_threshold` (moteur, cache en process — zéro I/O hot path),
  `ai.claude_scoring_period_seconds` (boucle Claude), `risk.*` (jauges RECAP),
  `live.cycle_*` (cadence Mode Live), `alerts.*` (vue Live). Presets/import = events
  (l'historique garde tout) ; validation COMPLÈTE avant écriture, rien de semi-appliqué.

## D-024 · Couleurs opérateur : Sony ROUGE / Youssef JAUNE (arbitrage opérateur) + badge par bloc
L'opérateur a demandé un code couleur d'identification des blocs : **rouge pour Sony,
jaune pour Youssef** — en remplacement du cyan/violet initial de `CLAUDE §3`. Contradiction
de spec réelle (collision avec les statuts de risque VERT/JAUNE/ROUGE et l'or Router) →
question posée (§12), **tranché par l'opérateur : rouge/jaune avec garde-fous**.
Garde-fous appliqués :
- **Teintes distinctes** : Sony `#f43f5e` (framboise) ≠ risque ROUGE `#f87171` (saumon) ;
  Youssef `#facc15` (citron) ≠ risque JAUNE `#fbbf24` (ambre) ≠ Router `#f0b429` (or).
- **La couleur opérateur n'est jamais seule** : chaque panneau porte un **badge texte**
  (`S1 · SONY` / `S2 · YOUSSEF` / `ROUTER` / `SYSTÈME`) + un liseré gauche ; les blocs
  mixtes (B1 états, B2 bridge, lecture Mode Live) sont badgés `S1 + S2` (dégradé).
- **Attribution schéma-driven** : `s1_state` → SONY ; `s2_state` → YOUSSEF ;
  `unified_signal_output`/`sync_state` → ROUTER ; Phase 0, calibration, streak, mode,
  harnais mock, blotter → SYSTÈME (les events du blotter portent déjà `operator` par ligne).
  Forcer ces blocs système sur un opérateur serait mensonger — non retenu.
- Le code risque VERT/JAUNE/ROUGE reste inchangé et toujours doublé forme+icône (§3).
`CLAUDE §3` mis à jour en conséquence (l'arbitrage opérateur fait foi).

## D-025 · Carnet d'ordres (`s1_state.order_book`, panneau `OB`) — PLACEHOLDER
Nouveau bloc du schéma (domaine Sony, canal rapide) + panneau DOM. Hypothèses :
- **Profondeur 10 niveaux** par côté, tick ES 0.25, `value = {bids: [[prix, taille]…],
  asks: […]}` bids décroissants / asks croissants — PLACEHOLDER en attendant le feed réel.
- **Lecture seule absolue** (§2.1) : aucun chemin d'exécution — contrairement aux DOM de
  plateformes, cliquer un prix ne fait RIEN. Le panneau n'a aucun handler d'action.
- **Pas critique Phase 0 en v1** : le carnet est de l'affichage/lecture ; en faire un
  blocker `DATA_PRESENT` changerait un verrou dur → décision séparée si besoin.
- **Validation déterministe serveur** : carnet croisé (best bid ≥ best ask) = donnée
  réelle pathologique → montrée + flag `CROSSED_BOOK` ; structure malformée = donnée
  inexploitable → RETIRÉE (ABSENT + flag `MALFORMED`, fail-closed §3).
- **Imbalance** Σbid/(Σbid+Σask) dérivée à l'affichage du même champ (pure) ; côtés
  colorés vert/rouge par convention de marché mais TOUJOURS libellés `BID`/`ASK` (§3).
- Mock : pathologies dédiées — profondeur partielle, spread élargi, croisement sur la
  probabilité `contradict_p` du scénario. Layouts localStorage bumpés v2 (OB visible).
- **Durci par `/devil` (Loop 4)** : le moteur CANONISE sans inventer — niveaux non finis
  (NaN/inf) ou ≤ 0 ⇒ carnet entier RETIRÉ (`MALFORMED`, pas de demi-vérité) ; doublons de
  prix agrégés (tailles sommées) ; côtés triés (un feed réel peut arriver non trié) ;
  **profondeur bornée aux 10 meilleurs niveaux** (contrat d'affichage + anti-inondation
  SSE/DOM sur feed extrême). Côté UI : **mute du canal SSE** (≠ coupure de source) ⇒
  bandeau « FLUX MUET — dernière image Xs » + carnet grisé — le dernier payload gardait
  un `freshness` FRESH figé qui aurait menti. Débordement horizontal < 1100 px corrigé à
  la racine (`min-w-0` entête `Panel` + zones de grille — défaut préexistant aggravé par
  les badges D-024, trouvé par l'attaque resize).

## D-026 · Tape / Time & Sales (`s1_state.tape`, panneau `TP`) — PLACEHOLDER
Nouveau bloc du schéma (domaine Sony « order flow » §3, canal rapide) + panneau. Hypothèses :
- **Fenêtre glissante SERVEUR** : le champ `tape` porte les `TAPE_WINDOW=40` prints les
  plus récents (plus récent en tête). Choix vs buffer client : le champ EST le tape, donc
  sur coupure il vieillit STALE→ABSENT et disparaît honnêtement (un buffer client
  garderait des prints périmés à l'air vivant — violation §3). Cohérent avec `order_book`.
- **Print** = `{ts, price, size, side ∈ BUY|SELL, seq}`. `side` = sens agresseur (BUY à
  l'offre / SELL au bid), biaisé par `aggressor_ratio` dans le mock — PLACEHOLDER.
- **Lecture seule absolue** (§2.1) : ce sont les prints OBSERVÉS du marché, pas les ordres
  de l'opérateur ; aucun handler, aucun chemin d'exécution.
- **Pas critique Phase 0 en v1** (affichage/lecture).
- **Validation déterministe serveur** (`_validate_tape`) : prix/taille non fini ou ≤ 0,
  side invalide ⇒ print écarté ; plus aucun print exploitable ⇒ tape RETIRÉ (ABSENT +
  `MALFORMED`, fail-closed §3). Tri par `seq` décroissant, borné à `TAPE_WINDOW`
  (anti-inondation SSE/DOM).
- **Gros print** : seuil = 90e centile de la fenêtre courante, dérivation PURE d'affichage
  (surlignage) — rien d'inventé. Sens jamais par la couleur seule : glyphe ▲/▼ + colonne
  dédiée (§3). `order_book`/`tape` ajoutés à `SOURCES["sierra_chart"]` (panneau MOCK).
  Layouts localStorage bumpés v3 (TP visible dans MICRO · S1).

**Durcissement /devil (Loop 4)** — 3 attaques, toutes gérées (tests dans `test_tape.py`) :
1. **Rafale hostile** (5000 prints, `seq` mélangés) → `_validate_tape` borne à
   `TAPE_WINDOW=40` via `heapq.nlargest` par `seq` (pas de tri O(n log n) complet) : sortie
   = 40 plus récents, triés, DOM/SSE protégés. Test `test_burst_is_bounded_to_window_and_ordered`.
2. **Séquences désordonnées / `seq` dupliqués** (feed multi-thread) → dédup par
   `dict[seq]` (dernière écriture gagne), garantissant des **clés React uniques** (`key={p.seq}`
   dans `TapePanel`) : plus de warning « same key » ni de ligne fantôme. Tests
   `test_duplicate_seq_is_deduped_stable_react_keys`.
3. **Robustesse par-print** : un print structurellement cassé (prix non numérique, clé
   manquante) est écarté SEUL — `try/except` intra-boucle + `continue`, la fenêtre valide
   survit. Corrige un bug trouvé à l'attaque : le `try/except` grossier précédent jetait TOUTE
   la fenêtre sur un seul print pourri (aurait masqué le flux entier — anti-§3). Test
   `test_one_structurally_broken_print_does_not_discard_the_window`.
- **Redimensionnement** (E2E Playwright, 1600→720px) : le panneau Tape **ne déborde jamais de
  lui-même** à toute largeur et reste rendu ; body sain jusqu'à 820px (mini réaliste d'un
  terminal dense). En deçà de ~786px, le seul débordement horizontal vient de la **barre de
  statut Zone 0** (`Zone0StatusBar`, chrome global mono-ligne dense) — **hors panneau Tape**,
  tracé ici comme risque assumé (viewport phone irréaliste pour un terminal classe Bloomberg ;
  n'affecte aucune contrainte dure §2/§3, aucune donnée inventée). Correctif chrome global
  différé (commit séparé — « une feature par commit »).

## D-027 · Calendrier économique (`econ_calendar.events`, panneau `EC`) — PLACEHOLDER
Nouveau bloc du schéma + panneau. Hypothèses (Loop 1 étape 1) :
- **Bloc SYSTÉMIQUE, pas opérateur** : le calendrier macro/géo impacte la liquidité pour
  LES DEUX opérateurs (la fenêtre « news Tier 1 ±30 min » est un filtre Phase 0 de Sony —
  AUTORITÉ `reference/MANIFEST §Sony·SVS` — et les publications pèsent sur l'EUR/USD de
  Youssef). Accent `none` → badge `SYSTÈME`, pas de couleur opérateur (D-024).
- **Canal LENT** (`SLOW_BLOCKS`) : un planning évolue en minutes, pas en sous-seconde (§6).
  Source dédiée `econ_feed` (coupable via API comme les autres → STALE→ABSENT réels).
- **Événement** = `{ts, name, tier ∈ 1|2|3, region}` ; tier = impact liquidité
  (1 fort / 2 modéré / 3 faible) — nomenclature PLACEHOLDER, mapping réel (Forex Factory,
  BLS…) à trancher quand un vrai feed existera.
- **Compte à rebours HONNÊTE** : le `ts` de chaque événement est une heure programmée
  CONNUE → le countdown est une dérivation CLIENT de `serverNow` (précis, ré-affiché
  chaque seconde). Contraste assumé avec B2/GEX (§8.2) où la péremption est INCONNUE et
  où l'on affiche l'âge : ici le compte à rebours est légitime, là il serait un mensonge.
- **Validation déterministe serveur** (`_validate_econ_calendar`) : leçon du /devil Tape
  appliquée D'EMBLÉE — robustesse PAR-ÉVÉNEMENT (un événement cassé écarté SEUL),
  dédup par `(ts, name, region)` (clés React stables), tri chronologique (le plus proche
  en tête — c'est un planning), borné `CAL_WINDOW=12` ; plus rien d'exploitable →
  RETIRÉ (ABSENT + `MALFORMED`, §3). Le mock injecte ~3 % d'événements cassés (§4).
- **Fenêtre T1 ±30 min SIGNALÉE, PAS CÂBLÉE** : le panneau affiche une bannière factuelle
  quand un Tier 1 est à ±30 min (surface le filtre Sony), mais le moteur Phase 0 ne
  consomme PAS encore ce champ — câblage déterministe = feature séparée (une feature par
  commit) ; l'UI ne prononce jamais OUVERT/BLOQUÉ ici (§2.2).
- **Affichage** : tier JAMAIS par la couleur seule — carrés pleins `▣▣▣/▣▣/▣` (forme) +
  code texte `T1/T2/T3` + libellé (§3) ; passé récent (< 30 min) conservé estompé (le
  blackout est symétrique), passé lointain masqué ; prochain événement surligné.
  Layouts localStorage bumpés v4 (EC dans DÉFAUT, MICRO, MACRO).
- **Aucun chemin d'exécution** (§2.1) : événements OBSERVÉS/annoncés, rien à décider ici.

**Durcissement /devil (Loop 4)** — 3 attaques demandées, 4 failles réelles trouvées, toutes
corrigées (tests dans `test_econ_calendar.py`, E2E 8/8) :
1. **Désync d'horloge client** (E2E : `Date.now` skewé **+2 h** avant boot) → la correction
   `clockOffset` (re-dérivée à chaque event `session_identity`, sub-seconde) tient : les
   countdowns restent sains, pas de faux « tout passé ». Géré par conception ; quand le
   canal est mort, c'est la bannière muette (2.) qui couvre.
2. **Stale ANIMÉ** : le panneau n'avait AUCUNE détection de canal lent muet — backend mort
   = countdowns qui continuent de décroître sur un panneau à l'air FRESH (pire que du
   stale : du périmé qui bouge). Corrigé : bannière « flux muet — planning possiblement
   obsolète » (seuil 40 s ≈ 2,5 ticks lents) + grisage. Les countdowns CONTINUENT
   volontairement : le `ts` programmé reste vrai ; c'est la LISTE (ajouts/annulations)
   qui devient suspecte — c'est ce que dit la bannière.
3. **Famine du cap par le passé** : `sorted[:CAL_WINDOW]` gardait les 12 plus ANCIENS —
   20 événements écoulés pouvaient évincer un NFP T1 imminent pendant que le client
   affichait « aucun événement » (fail-silent dangereux). Corrigé : `CAL_PAST_GRACE`
   (±30 min, la fenêtre blackout symétrique) appliquée AVANT tri+cap ; et distinction
   honnête entre deux vides — feed pourri ⇒ ABSENT + `MALFORMED` ; feed vivant sans rien
   de pertinent ⇒ FRESH + liste vide (« aucun événement dans la fenêtre », pas une fausse
   panne). Le filtre client ±30 min reste en défense-en-profondeur (grâce serveur à
   cadence 15 s, sortie de fenêtre à la seconde côté client).
4. **Reconnexion SSE inexistante (SYSTÉMIQUE, tout le terminal)** : `connectSSE` créait les
   `EventSource` une fois, sans retry. Deux pannes distinctes prouvées au débogueur réseau :
   (a) réponse non-200 du proxy (backend mort) → la spec HTML ferme DÉFINITIVEMENT, zéro
   retry natif ; (b) pire : connexion PENDUE silencieusement par le proxy quand l'upstream
   meurt en cours de stream — aucun `onerror`, jamais (les pings sse-starlette sont des
   commentaires invisibles côté JS). Tout redémarrage du backend laissait donc le terminal
   muet jusqu'au reload manuel. Corrigé dans `lib/sse.ts` : `resilientSource` (retry 4 s
   sur erreur) + **watchdog de vivacité** (pattern `RUNTIME_LOOPS` : canal déjà productif
   silencieux > 10 s fast / > 45 s slow ⇒ recycler la source ; un backend encore mort
   bascule alors sur la boucle d'erreur). Prouvé E2E : kill réel du backend → bannières
   muettes honnêtes → relance → flux repris sans reload (~3 s fast, ~5 s slow après retour).
- **Rafale simultanée** (data dump 8h30 : 30 publications distinctes à la même seconde +
  doublons) : dédup `(ts, name, region)`, cap `CAL_WINDOW`, clés React uniques — passait
  déjà, figé par test. Tous les événements du même `ts` sont surlignés « prochain »
  ensemble (comportement voulu : ils SONT tous imminents).

## D-015 · Un opérateur par instance (AUTORITÉ `CLAUDE §9`)
`VITE_OPERATOR` (ou `?operator=YOUSSEF`) fixe l'instance ; défaut `SONY`. Tous les events
portent `operator`.
