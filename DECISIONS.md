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

## D-028 · Architecture LangGraph — détection Liquidity Sweep (`app/graph/liquidity_sweep.py`)
Initialisation de la couche graph-state (CLAUDE §4, priorité « en dernier » §10, demandée par
l'opérateur). Hypothèses (Loop 1 étape 1) :
- **LangGraph installé** (`langgraph>=1.2,<2`, requirements.txt) — cohérent stack §4, Loop 0
  résolu. Rétrograde `websockets` 16→15 (contrainte langgraph-sdk) : deps serveur + suite
  existante revérifiées vertes (42 tests).
- **Détection STRICTEMENT DÉTERMINISTE** — le graphe *orchestre* (nœuds `detect`→`emit`,
  arête conditionnelle), la *décision* est du code à seuils booléens. AUCUN LLM dans le
  chemin (« sans hallucination », §2.8/§7) : reproductible bit-à-bit (test dédié). C'est
  l'interprétation cardinale de la demande — un LLM qui « devine » un sweep serait une
  violation directe.
- **GraphState** : `delta_volume` (imbalance agresseur nette sur la fenêtre tape),
  `spread_width` (ticks = (best_ask−best_bid)/0.25), `best_bid_ask_depth` (tailles aux
  meilleurs niveaux) + contexte (`tape_burst`, `news_t1_imminent`, `data_ok`) + sorties.
- **Déclencheur** = `(tape_burst OU spread_width > 2) ET news_t1_imminent`. Le couplage ET
  est le cœur : anomalie microstructure seule ≠ sweep, news seule ≠ sweep. Seuils v1
  provisional (`SPREAD_TICKS_THRESHOLD=2`, `BURST_COUNT_THRESHOLD=8`/2 s, `NEWS_T1=±30 min`)
  isolés en tête de module, calibration owner Sony (§8/§12). Bien calibrés vs mock : spread
  normal 2 ticks (ignoré), pathologie « spread élargi » 4 ticks (déclenche).
- **Câblage réel** (`build_sweep_inputs`) : lit `s1_state.order_book`, `s1_state.tape`,
  `econ_calendar.events` (le bloc D-027) — FAIL-CLOSED sur la fraîcheur : seules les données
  FRESH sont exploitées, STALE/ABSENT ⇒ `None`, jamais inventé (§3).
- **Deux vides honnêtes** (anti-hallucination) : `data_ok=True, triggered=False` = « pas de
  sweep » prouvé ; `data_ok=False` = « impossible à évaluer » (micro OU news non
  disponible). Un détecteur ne confond jamais « tout va bien » et « je ne sais pas ». Test :
  données partielles alléchantes (burst+news vrais) mais `data_ok=False` ⇒ AUCUNE alerte.
- **Checkpointing §4** : `build_graph(checkpointer=…)` accepte un saver (MemorySaver en test,
  SqliteSaver en prod) → architecture checkpoint-ready ; le détecteur `SWEEP_GRAPH` reste
  SANS état (chaque appel indépendant, idéal reproductibilité).
- **N'émet qu'une ALERTE** (événement observé), jamais un ordre (§2.1).
- **Hors-scope de cette tranche (incréments suivants, une feature par commit)** : câblage
  périodique dans le moteur (le graphe est déterministe donc *éligible* < 200 ms §7, mais le
  câblage moteur + champ schéma `liquidity_sweep` + panneau restent à faire) ; SqliteSaver ;
  robustesse par-print de `delta_volume` (lit un `s1_state.tape` déjà validé D-026, mais un
  /devil durcira). Essai manuel réel concluant sur schéma d'un VRAI moteur (extraction live,
  alerte déterministe, reproductible).

**Durcissement /devil (Loop 4)** — 4 attaques, 3 failles réelles trouvées et corrigées
(tests dans `test_liquidity_sweep.py`, 16 verts) :
1. **Carnet CROISÉ / spread négatif** (bid ≥ ask) : `spread > 2` laissait passer un spread ≤ 0
   en SILENCE — la dislocation la PLUS extrême (marché verrouillé/croisé) était ignorée.
   Corrigé : `_spread_anomaly` distingue `WIDE_SPREAD` (> 2 ticks) et `CROSSED_BOOK` (≤ 0) ;
   le croisé déclenche, labellisé à part (l'humain vérifie — peut aussi être un glitch, §2.1
   in-the-loop). Prouvé live : carnet −4 ticks → alerte CROSSED_BOOK.
2. **Rafale FABRIQUÉE par désync d'horloge** : la fenêtre `ts > now − W` comptait les prints
   datés DANS LE FUTUR (désync source, pathologie CLOCK_DESYNC du mock) → fausse rafale.
   Corrigé : fenêtre bornée des deux côtés `]now−W, now]` ; un print futur (heure d'arrivée
   réelle inconnue) est exclu (fail-closed : pas de faux positif ; le spread reste un chemin
   indépendant).
3. **Corruption mathématique de `delta_volume`** : une taille inf/nan (ou un `delta_volume`
   d'état corrompu) fuyait dans l'alerte → JSON invalide en aval + direction fantôme
   (inf > 0 = True). Corrigé : garde `_finite()` par-print à l'extraction (leçon per-print du
   /devil Tape) ET au nœud d'émission (frontière de sortie) — toute mesure non finie ⇒ `None`,
   jamais propagée ; direction indéterminée sur delta corrompu. Idem `spread_width` non fini.
4. **Contradiction Tape vs Order Book** : GÉRÉE PAR CONCEPTION (déjà, figé par test) — le
   couplage OR + fail-closed par-source fait contribuer chaque source indépendamment ; source
   manquante ⇒ `None`, jamais inventée. Order book FRESH large + tape ABSENT ⇒ sweep sur
   spread SANS direction fantôme (pas de tape pour confirmer l'agresseur).

**Intégration au système (incrément suivant, feature séparée)** :
- **Bloc schéma `liquidity_sweep`** (canal FAST) : `LiquiditySweepAlert` déplacé dans
  `schema.py` (source unique) — le graphe le réutilise (pas d'import circulaire). Le bloc porte
  `assessable` (= data_ok, distingue « pas de sweep » de « impossible à évaluer »), `triggered`,
  `alert` courante, `last_compute_ts` (âge réel comme B2), et un feed `recent` court.
- **Exécution ASYNC NON-BLOQUANTE** (§2.8/§7) : `_sweep_loop` sur sa propre cadence
  (`SWEEP_TICK_SECONDS=1 s`), HORS des boucles fast/slow. `_assemble_sweep` lit le schéma
  SYNCHRONE (snapshot cohérent, pas de torn read) puis OFFLOADE `SWEEP_GRAPH.invoke` via
  `asyncio.to_thread` → le tick fast < 200 ms n'est JAMAIS bloqué (le détecteur est
  déterministe mais reste async par contrat).
- **Feed dédupliqué** par clé `trigger|direction` : condition persistante ⇒ une entrée ;
  sweep levé puis re-déclenché ⇒ nouvel événement. Advisory, jamais dans l'event store §2.5
  (détection ≠ décision) — projection volatile.
- **Panneau `IA` « Alertes IA · Sweep »** (un panneau = un champ) : ergonomie NON-INTRUSIVE
  (bandeau de statut, jamais de modale ; pas de clignotement). CROSSED_BOOK (rouge, sévère) et
  WIDE_SPREAD (jaune) distingués par chips typés (icône + texte + bordure, §3) ; direction
  ▲offre/▼bid ; états fail-closed honnêtes (« impossible à évaluer » ≠ « aucun sweep » ;
  « détecteur muet » sur silence > 5 s). Badge SYSTÈME, note « détecteur déterministe
  (LangGraph) — pas un LLM ». Espaces localStorage bumpés v5 (IA dans MICRO).
- **Vérifié** : 52/52 pytest (dont 3 intégration) · ruff · tsc · vite build ; E2E réel 9/9
  (statut honnête, sweep déclenché avec chips typés, coupure micro → « impossible à évaluer »,
  retour) — capture docs/ai-alerts.png.

**Durcissement /devil (Loop 4)** — 3 attaques, 1 faille visuelle réelle ; backend confirmé
robuste par conception (tests, 55 verts) :
- **BACKPRESSURE** (invoke LangGraph lent/bloqué) : GÉRÉE. Boucle `_sweep_loop` AUTO-CADENCÉE
  (`sleep(max(0.1, TICK − elapsed))` — pas de `create_task` par tick → aucun empilement,
  RUNTIME_LOOPS Loop D) + `asyncio.to_thread` → un invoke lent bloque un THREAD, JAMAIS la
  boucle d'événements ; le tick fast < 200 ms reste libre. Prouvé : invoke à 0.4 s, un ticker
  concurrent avance ≥ 50 fois pendant l'invoke. Si l'invoke traîne > 5 s, le panneau passe
  « détecteur muet » (fail-closed honnête).
- **RACE DU FEED** : GÉRÉE. `_sweep_recent`/`_sweep_last_key` mutés dans le SEUL `_assemble_sweep`
  (tâche unique, awaité un à la fois) ; `build_sweep_inputs` lit le schéma SYNCHRONE (snapshot,
  pas de torn read vs fast). Feed BORNÉ (deque maxlen `SWEEP_RECENT_MAX`) — prouvé : 20 sweeps
  distincts ⇒ 8 gardés, pas de fuite. Invariant `triggered ⇒ alert` figé (anti-incohérence UI).
- **REDIMENSIONNEMENT EXTRÊME** : faille réelle corrigée. `AlertRow` était un `flex` dense
  SANS `min-w-0` → son min-content forçait la colonne, débordement horizontal du body (leçon
  /devil OB). Corrigé : news en `min-w-0 flex-1 truncate` (tronque d'abord), reste `shrink-0`,
  rangée `overflow-hidden` (clippe aux largeurs extrêmes). Prouvé (E2E 1600→640) : le panneau
  IA ne déborde JAMAIS de lui-même, body sain ≥ 820 px ; le débordement sous ~786 px est le
  chrome global `Zone0StatusBar` (hors panneau IA, déjà tracé D-026), pas le panneau.
- **RAFALE DE MISES À JOUR** : feed borné + clés React stables (`ts-trigger-index`) → zéro
  warning de clé sur toute la session (E2E).
- **Observation honnête (hors-scope, tracée)** : un test PRÉEXISTANT `test_order_book` a montré
  UN flake ponctuel en suite complète (état Redis partagé inter-tests), non reproduit sur
  3 relances (55 verts) ni en isolation. Fragilité d'isolation Redis des tests intégration —
  concern séparé, ne touche pas le détecteur Sweep.

## D-029 · CVD par niveau + réinitialisation événementielle (`s1_state.cvd_by_level`)
Nouveau bloc du schéma + accumulation SUR LE HOT PATH. Hypothèses (Loop 1 étape 1) :
- **CVD par niveau** : au lieu d'un CVD scalaire cumulé (`order_flow.cvd`), on accumule le
  delta agresseur (buy − sell) PAR NIVEAU de prix → profil de footprint. `CvdState` porte
  `levels` (bornés, triés par prix), `total_delta`, `since_ts`, `last_reset_ts`,
  `reset_reason`, `stale`. Ordre OBSERVÉ, jamais un ordre (§2.1).
- **Sur le HOT PATH** (§7) : accumulation déterministe dans `_assemble_fast` (pas d'async —
  contrairement au Sweep D-028, c'est du calcul pur et cheap). Garde-fou perf MESURÉ :
  `_build_cvd` ≈ **0,05 ms/tick** (marge ×4000 sous 200 ms) ; `_assemble_fast` COMPLET ≈
  2,4 ms/tick. Test dédié asserte < 200 ms (et < 10 ms).
- **Alimentation par les prints NEUFS** : `seq` (id d'ajout monotone de la source) évite le
  double comptage entre ticks — on traite les prints `seq > dernier traité`. PLACEHOLDER : le
  vrai CVD consommerait le FLUX de trades complet ; ici on lit le tape (fenêtre glissante 40,
  D-026) — une rafale > 40 prints ENTRE deux ticks perdrait des prints (le mock émet 1-4/tick,
  large marge). À revoir avec un vrai feed.
- **RÉINITIALISATION événementielle liée à `econ_calendar`** : dès qu'un événement Tier-1
  franchit `now` (`now >= ts`) et diffère du dernier reset (clé `ts|name`), l'accumulateur
  repart à zéro → profil frais par régime de news. Reset UNE fois par événement (clé trackée).
  Calendrier absent → pas de reset (accumulation depuis le démarrage, honnête).
- **Fail-closed** (§3) : tape non FRESH → accumulation GELÉE + `stale=True`, jamais un niveau
  inventé ; le dernier profil connu est conservé (comme une image, pas une valeur fabriquée).
- **Bornes** : `CVD_MAX_TRACKED=512` prix suivis (garde-fou coût de tri) ; `CVD_MAX_LEVELS=24`
  affichés (les plus actifs par volume, puis triés par prix). `total_delta` est le net COMPLET
  (tous niveaux), pas seulement les 24 affichés — cohérent, à signaler dans un futur panneau.
- **Hors-scope de cette tranche** (une feature par commit) : ~~panneau footprint frontend~~
  (LIVRÉ, voir plus bas) ; câblage du reset sur d'autres événements (ouverture de session,
  marqueur) ; consommation du flux de trades complet. Essai manuel réel concluant sur schéma
  d'un VRAI moteur.

**Panneau CVD Footprint** (feature séparée, incrément suivant) : `FootprintPanel` lit UN champ
(`s1_state.cvd_by_level`, §1). Vue compacte « Prix | Delta » — échelle par prix DÉCROISSANT
(façon DOM), heatmap THERMIQUE vert (acheteur) / rouge (vendeur), intensité ∝ |delta| relatif ;
mais JAMAIS la couleur seule : le delta SIGNÉ est incrusté dans chaque cellule (§3, lisible
sans percevoir la couleur — idiome repris de `BridgewaterMatrix`). Résumé « net cumulé Δ » +
régime (`reset_reason`/`since_ts`). États fail-closed HONNÊTES : `stale` → « figé » grisé,
`capped` → « suivi saturé », pas de niveau → PAS DE DONNÉES. Temps réel via sélecteur zustand
ISOLÉ (`s => s.s1_state?.cvd_by_level`) : ne re-rend que ce panneau, rendu global non bloqué ;
coût O(≤24) par rendu. Espaces localStorage bumpés v6 (CVD dans MICRO). Vérifié : tsc · vite
build ; E2E réel 13/13 (échelle peuplée, deltas signés, cellules thermiques, temps réel,
resize scopé, zéro clé dupliquée) — capture docs/cvd-footprint.png. Flux OBSERVÉ, jamais un
ordre (§2.1).

**Durcissement /devil (Loop 4)** — 4 attaques, toutes gérées (E2E 13/13) :
- **maxAbs=0 (division par zéro heatmap)** : DÉJÀ gardé (`maxAbs > 0 ? … : 0` ; `maxAbs > 0`
  couvre aussi `NaN`). Renforcé défense-en-profondeur : `Number.isFinite(delta)` sur
  l'intensité ET dans le calcul de `maxAbs` → un `delta` inf/nan (non atteignable du backend
  fini, mais garde) ⇒ intensité 0, JAMAIS un alpha NaN dans le style (rendu cassé) ;
  `fmtSigned` rend « — » sur NaN. Invariant E2E : 24 cellules, tous les alpha finis dans [0,1].
- **RESIZE extrême** (1600→560 px) : le panneau ne déborde JAMAIS de lui-même. Sûr par
  construction — grille `[62px 1fr]`, barre 1fr qui rétrécit, nombre `absolute inset-0`
  (centré, jamais de débordement), `overflow-hidden` sur la cellule.
- **BASCULE d'état fresh → stale → fresh** : branches mutuellement exclusives, l'échelle rend
  TOUJOURS `cvd.levels` (les bandeaux stale/capped sont additifs) → intégrité préservée.
  Prouvé : coupure sierra_chart → « figé » + échelle non corrompue → réactivation → repeuplée.
- **RAFALE haute fréquence** : sélecteur zustand isolé, re-render ~4×/s (cadence data), coût
  O(≤24) ; feed borné ≤ 24, zéro clé dupliquée, zéro erreur console sur toute la session.

**/devil — passe CONTRÔLÉE** : maxAbs=0 (tous deltas nuls) et `capped` étaient impossibles à
provoquer avec le mock live (deltas non nuls, < 512 prix). Faute de vitest, ajout d'une
affordance de test DEV-only `window.__setCvd` (gated `import.meta.env.DEV` → ÉLAGUÉE en prod,
vérifié : absente du bundle) : le test gèle le SSE (backend tué → store figé), injecte un
`cvd_by_level` fabriqué, et prouve pour de VRAI — maxAbs=0 → 3 cellules, alphas tous finis, «0»
signé (pas de NaN) ; capped=true → bandeau « suivi saturé » ; stale=true → « figé ». Ces deux
branches ne sont plus « vérifiées par raisonnement » mais par rendu contrôlé.

**Polish /polish (Loop 5)** — hiérarchie visuelle (aucun changement de comportement) :
- **POC (Point of Control)** = niveau au VOLUME absolu max (`buy + sell`), DISTINCT de
  l'imbalance `|delta|` de la heatmap. Marqué discrètement : glyphe ▸ + prix en gras souligné
  (forme + position, §3) — jamais par la couleur. Prouvé : un POC à delta faible (+2) porte le
  marqueur tout en restant thermiquement discret, pendant qu'un gros delta (+56) s'illumine.
- **Gradient perceptuel** : alpha = `plancher + (|delta|/maxAbs)^1.6 × plafond` (gamma 1.6).
  Le gamma > 1 comprime le bas → les deltas marginaux restent discrets, seuls les GROS deltas
  montent (s'extraient) ; plafond 0.58 → jamais de saturation. Remplace le linéaire précédent.
- Vérifié : tsc · vite build ; E2E nominal + /devil re-passés (resize scopé, maxAbs=0, capped,
  stale) — capture docs/cvd-footprint.png (cas contrôlé POC-vs-gros-delta).

**Durcissement /devil (Loop 4)** — 4 attaques, 2 failles réelles corrigées (tests, 11 verts) :
1. **RÉGRESSION de seq** (redémarrage source, seq repart bas) : le garde `seq <= last_seq`
   ignorait alors TOUT print futur → GEL SILENCIEUX (tape FRESH mais accumulation morte, le
   pire — pas signalé par `stale`). Corrigé : si le max de la fenêtre passe SOUS `last_seq`
   (régression, pas un simple traînard) → re-baseline `last_seq = 0` et reprise. Un traînard
   isolé (max de fenêtre ≥ last_seq) reste ignoré (déjà passé) — test dédié anti-re-baseline.
2. **SATURATION du bouchon 512** : le soft-cap SAUTAIT tout nouveau niveau une fois plein →
   les vrais niveaux près du marché étaient VERROUILLÉS dehors (silencieux). Corrigé :
   ÉVICTION du niveau le moins actif à saturation (garde les plus pertinents) + flag `capped`
   honnête. Perf sous saturation+éviction MESURÉE : ~0,20 ms/tick (marge ×1000 sous 200 ms).
3. **PRIX ABERRANT** (+50 ticks) : géré par conception — tracké mais faible volume → hors du
   top-24 affiché (cap par volume) ; `total_delta` le reflète (réel) ; aucun crash. Figé par test.
4. **COURSE reset + prints même tick** : gérée par conception — ordre DÉTERMINISTE (reset
   d'abord, puis accumulation) : les prints neufs comptent dans l'accumulateur FRAIS
   (post-reset), jamais perdus. Figé par test.

## D-030 · Snapshot Déterministe (`app/snapshot.py`, `POST /snapshot`)
Module d'export : capture instantanée des 4 blocs (carnet, CVD par niveau, calendrier éco,
alertes IA) en JSON + Markdown, déclenchée par API. Hypothèses (Loop 1 étape 1) :
- **DÉTERMINISTE** : `build_snapshot` est une pure projection du `ContextSchema` courant
  (`model_dump`) — même schéma + mêmes id/ts ⇒ contenu identique bit-à-bit (aucun LLM, aucun
  hasard ; le seul non-déterminisme est l'horodatage, passé en paramètre). Test dédié.
- **FAIL-CLOSED (§3)** : chaque bloc est capturé TEL QUEL — un bloc absent/périmé garde son
  `freshness=ABSENT`/`value=None`, et le Markdown affiche « PAS DE DONNÉES ». Jamais un
  carnet/CVD inventé. Le snapshot est une preuve honnête de « ce que le terminal savait à
  l'instant T », gaps compris (cohérent objectif « preuve comportementale »).
- **Écriture ASYNC NON-BLOQUANTE (§7)** : `write_snapshot` sérialise (JSON + Markdown) puis
  OFFLOADE l'I/O disque via `asyncio.to_thread` (`_write_files`) → la boucle d'événements,
  donc le hot path, n'est jamais bloquée. Prouvé : écriture lente (0,3 s) + ticker concurrent
  qui avance (test non-bloquant).
- **JSON** = capture machine complète (les 4 blocs dumpés + métadonnées) ; **Markdown** =
  résumé lisible humain (carnet best bid/ask + spread ; CVD net + POC + échelle ; calendrier
  prochains événements + compte à rebours ; alertes IA statut). Écrits dans `SNAPSHOT_DIR`
  (`data/snapshots/`, gitignoré — artefacts générés).
- **Endpoint** `POST /snapshot` : lit `engine.schema`, id `snap_{int(ts)}_{operator}`, écrit,
  renvoie `{snapshot_id, created_ts, json_path, md_path}`. OBSERVATION, jamais un ordre (§2.1) ;
  n'écrit PAS dans l'event store append-only (§2.5) — export fichier séparé.
- **Hors-scope de cette tranche** (une feature par commit) : bouton de déclenchement frontend ;
  collision d'id si 2 snapshots dans la même seconde (int(ts)) — à durcir au /devil ; liste/
  téléchargement des snapshots. Essai manuel réel concluant (endpoint live → JSON + Markdown
  honnêtes avec données live : POC, spread, countdowns, SWEEP ACTIF).

## D-031 · log_scraper — tailer NT8 → auto-snapshot (`app/log_scraper.py`)
Tailer du log quotidien de NinjaTrader 8 : sur un fill DÉJÀ passé par l'humain dans NT8,
déclenche automatiquement une capture de snapshot (D-030). Hypothèses (Loop 1 étape 1) :
- **OBSERVATION seule (§2.1)** : le module lit les logs d'exécution que NT8 a produits
  lui-même — il ne fait que *constater* qu'un fill a eu lieu. Il ne passe, ne modifie ni ne
  route JAMAIS d'ordre. Le seul effet de bord est une capture de snapshot (fichier), jamais
  une action marché.
- **ASYNC NON-BLOQUANT (§7)** : la lecture disque (`_read_new`) est OFFLOADÉE via
  `asyncio.to_thread` ; la boucle d'événements n'est jamais bloquée par l'I/O. Prouvé : lecture
  lente (0,3 s) + ticker concurrent qui avance (test non-bloquant). Boucle auto-cadencée
  (RUNTIME_LOOPS Loop D) : `sleep(max(0.05, poll − elapsed))`, ne meurt jamais sur exception.
- **FAIL-CLOSED (§3)** : dossier/log absent ou illisible → `_read_new` renvoie `None`, aucun
  trigger, jamais un fill inventé. Le tailer démarre en FIN de fichier (première vue) → ne
  rejoue PAS l'historique. Rotation quotidienne détectée par changement d'inode → repart en
  fin du nouveau fichier ; troncature en place → repart en fin (aucun replay). Tests dédiés
  couvrent : nouvelle ligne, skip historique, fichier absent, rotation, non-bloquant.
- **DÉTERMINISTE** : détection par Regex sur mots-clés NT8 (`Execution=`, `filled`,
  `State=Filled`) + extraction des champs présents (instrument, prix, quantité) ; ligne de
  bruit → `None`. Aucun LLM. `nt8_daily_log_path` cible le log `log.YYYYMMDD*.txt` au stamp de
  date le plus récent présent (clock-indépendant — voir /devil) ou `None` (fail-closed).
- **Câblage** : `main.py` lifespan construit le tailer si `LOG_SCRAPER_ENABLED=true` ET
  `NT8_LOG_DIR` fourni (sinon `None` — désactivé par défaut, aucun log NT8 en démo). Le
  callback appelle `capture_snapshot(engine, now)` — helper partagé extrait de `POST /snapshot`
  (chemin unique : projection déterministe + écriture async). Toute erreur de capture est
  isolée (le tailer survit). Essai manuel réel concluant : fill NT8 appendé → 1 snapshot
  JSON + MD auto-créé ; historique et lignes de bruit → aucun trigger.
- **Amélioration vs D-030** : id snapshot horodaté à la **milliseconde** + désambiguïsé (voir
  /devil ci-dessous). Résiduel hors-scope (v1) : démarrage/arrêt/monitoring du scraper via API
  non exposés.

### /polish D-031 — diagnostic console actionnable
Le module est backend-only : la surface UX est la CONSOLE que l'opérateur regarde. Messages
opérateur en français actionnable (§5) ; les traces internes de résilience restent terses.
- **Diagnostic de démarrage** `startup_report(enabled, log_dir)` (pur, testé sur 5 états) logué
  au lancement : dit si le scraper est ACTIF, QUEL fichier il suit, sinon COMMENT l'activer.
  États non-nominaux honnêtes/fail-closed, jamais masqués : désactivé (→ vars à définir),
  NT8_LOG_DIR vide (→ INACTIF + quoi définir), dossier introuvable (→ chemin à corriger), pas
  de log du jour (→ EN ATTENTE), actif (→ chemin exact suivi + rappel « démarre en fin »).
- **Confirmation d'écriture** : sur fill → snapshot, log INFO actionnable
  « fill NT8 détecté (instrument @ prix) → snapshot ÉCRIT : <chemin json> » (l'opérateur voit
  où trouver le fichier) ; échec de capture → log exception disant quoi vérifier (droits
  SNAPSHOT_DIR / espace disque). Non-bloquant : sur la boucle async du scraper, hors hot path.

### /devil D-031 — durcissement (4 attaques)
Attaques : fichier verrouillé Windows · encodage corrompu / lignes tronquées · rafale de fills
(collision d'id ms) · rotation de fichier à minuit. Corrigées, chacune avec test de régression.
- **Fichier verrouillé / illisible (Windows, NT8 tient un handle)** : `_read_new` encadre
  `os.stat` ET `open` par `except OSError` (dont `PermissionError`) → renvoie `None`, aucun
  crash, aucun trigger. L'offset n'avance PAS sur échec → la ligne est rattrapée dès le
  déverrouillage. Test : `open` binaire patché pour lever PermissionError → fail-closed puis
  récupération.
- **Lignes tronquées (NT8 écrit un fill par morceaux)** : lecture passée en **MODE BINAIRE**
  (offset = vrai décalage d'octets, comparable à `st_size` ; le `tell()` texte est un cookie
  opaque, bug latent corrigé). La fin de ligne non terminée par `\n` est RETENUE dans `_buffer`
  et re-préfixée au cycle suivant → **jamais** de fill partiel émis, jamais un champ tronqué
  pris pour réel (§3). Buffer capé (`_BUFFER_MAX=1 Mo`) : ligne jamais terminée (corruption) →
  drop honnête. Test : ligne partielle sans `\n` → 0 trigger ; complétion → 1 trigger, champs
  exacts.
- **Encodage corrompu** : décodage `errors="replace"` → un octet invalide devient U+FFFD, jamais
  un crash ; les mots-clés/nombres NT8 étant ASCII, la détection reste robuste (hypothèse : les
  champs pilotes — keyword, prix, quantité — sont ASCII ; un nom d'instrument non-ASCII mal
  décodé n'empêche pas la capture).
- **Rafale de fills (collision d'id à la même milliseconde)** : `capture_snapshot` désambiguïse
  l'id via un **compteur monotone** (`snap_{ms}_{op}` puis `-1`, `-2`… dans la même ms), lu+
  incrémenté synchronement avant tout `await` (pas de course sur l'event loop coopératif, un
  opérateur par instance §9) → deux fills simultanés = deux fichiers distincts, **aucun
  écrasement**. Test unitaire (deux captures au même `ts` → ids distincts) + essai manuel
  (rafale de 2 fills → 3 snapshots distincts).
- **Rotation à minuit** : `nt8_daily_log_path` sélectionne désormais le log au **stamp de date
  le plus grand présent** (départagé par mtime), donc INDÉPENDANT de l'horloge/fuseau du process
  (le backend peut tourner en UTC alors que NT8 nomme en heure locale — l'ancien `gmtime`
  ratait le bon fichier plusieurs heures/jour). Sans couture à minuit : tant que NT8 n'a pas
  créé le fichier du nouveau jour, l'ancien reste ciblé (on rattrape sa fin) ; dès qu'il
  apparaît, on bascule (le changement d'inode cale la lecture en fin). Nom non conforme →
  ignoré. Test : bascule J1→J2 à horloge figée + fichier parasite ignoré.

## D-032 · Journal de Bord — index + visualiseur des snapshots (vue frontend)
Vue plein écran (pas un panneau SSE) qui archive et rejoue les snapshots déterministes (D-030).
`GET /snapshots/list` (index) + `GET /snapshots/{id}` (contenu) → vue `JBORD`. Hypothèses/décisions :
- **VUE, pas PANNEAU (traçabilité §1)** : un *panneau* live doit mapper un bloc du
  ContextSchema (§1) ; ici on relit des projections PASSÉES écrites sur disque → c'est une VUE
  d'archive (comme JOURNAL/RECAP/PARAMS), pas un panneau de signal. Le contenu reste traçable au
  schéma (chaque snapshot EST une projection déterministe). OBSERVATION seule (§2.1).
- **Backend** : `list_snapshots(dir, limit)` indexe par NOM de fichier + `stat` (aucune lecture
  de contenu → rapide sur des centaines de fills), récent→ancien, capé (défaut 200, max 1000).
  `read_snapshot(dir, id)` renvoie JSON parsé + Markdown. **Sécurité** : `id` doit matcher
  `^snap_\d+_[a-z]+(-\d+)?$` — garde anti-traversal (rejette `../`, séparateurs) AVANT toute
  lecture ; id invalide/inconnu → 404. Route `/snapshots/list` déclarée AVANT `/{id}`. Lecture
  offloadée (`to_thread`). Fail-closed (§3) : dossier absent → `[]`, jamais une erreur.
- **Frontend** : liste **VIRTUALISÉE** maison (fenêtre de lignes `ROW_H=30`, overscan) — fluide
  sur des centaines de snapshots SANS dépendance (pas de react-window ajouté ; contrainte proxy
  + « lisibilité > décoration »). Visualiseur bascule **Markdown / JSON** (`<pre>` monospace :
  le .md est lisible tel quel — pas de rendu HTML, évite une lib markdown + tout risque
  d'injection). Poll index 8 s (hors hot path). Bouton **Capturer** (POST /snapshot) →
  sélectionne le nouveau snapshot (« je capture, je le vois »). Bouton **Actualiser**.
- **Ergonomie (§polish)** : badge opérateur couleur JAMAIS seule (§3) — texte `S1·SONY` /
  `S2·YOUSSEF` ; ligne sélectionnée = liseré gauche or + fond (pas la couleur seule). État vide
  HONNÊTE et actionnable (« Aucun snapshot — clique Capturer ou déclenche un fill NT8 »). Nav
  clavier : liste `role=listbox` focusable, `ArrowUp/Down/Home/End` déplacent la sélection avec
  scroll-into-view. Découvrable : mnémonique `BORD` (alias SNAP/JB/SNAPSHOTS) dans la barre de
  commande + cycle `V` + entrée HELP. Colonne manquante d'un snapshot (`⚠ md`/`⚠ json`) signalée.
- **Vérif** : 6 tests backend (index récent→ancien, limite, dossier absent, lecture contenu,
  anti-traversal) — 95 passed, ruff clean ; `tsc`+`vite build` OK ; essai Playwright réel
  (capture → ligne → viewer MD/JSON → nav clavier) + captures d'écran.

## D-033 · Trade Reconciliator — moteur analytique FIFO (`app/trade_reconciliator.py`)
Moteur hors-ligne qui apparie les fills entrée↔sortie et calcule P&L USD + R-Multiple, exposé
via `GET /analyses/trades`. Hypothèses/décisions (Loop 1) :
- **Contradiction de spec résolue (source des fills)** : la requête demande de « charger
  l'historique des snapshots » et « apparier les fills », mais les snapshots (D-030) ne
  portaient QUE le contexte marché (carnet, CVD, calendrier, alertes) — PAS le fill. Résolution
  non ambiguë (§12) : **embarquer le fill déclencheur DANS le snapshot**. Le log_scraper tenait
  déjà le fill (ExecutionMatch) et le jetait ; désormais `capture_snapshot(..., fill=…)` l'écrit
  dans le bloc `fill` du snapshot (None pour une capture de contexte via `POST /snapshot`). Le
  snapshot devient auto-descriptif (« déclenché par ce fill »).
- **Côté du fill** : `parse_execution` extrait BUY/SELL (`Buy|BuyToCover|Sell|SellShort`) — noté
  `v1 provisional` (dépend du format exact NT8, à valider sur une install réelle). Absent → côté
  None → le réconciliateur compte le fill « non résolu », jamais deviné (§3).
- **FIFO net avec flips** : `reconcile_fills` tient un carnet de lots par RACINE d'instrument
  (`normalize_instrument` : « ES 12-24 » → « ES »). Un fill de même sens ouvre/ajoute ; de sens
  opposé ferme les lots les plus anciens (FIFO) et tout surplus RETOURNE la position. Chaque
  appariement = un `CompletedTrade` (direction, qty appariée, prix E/S, ts E/S).
- **P&L & R** : `CONTRACT_POINT_VALUE` (config) = $/pt — **ES=50, MES=5 AUTORITÉ (spec)**,
  NQ=20/MNQ=2 ajoutés. `pnl_usd = pnl_points × qty × point_value` ; `r_multiple = pnl_usd /
  R_UNIT_USD` (réutilise le 100 $ existant — source unique, pas de double définition).
  `exposure_seconds = exit_ts − entry_ts`.
- **FAIL-CLOSED (§3)** : contrat hors dictionnaire → `point_value`/`pnl_usd`/`r_multiple` =
  None, P&L en POINTS seulement (jamais un $ inventé) ; dossier absent → résultat vide ; fill
  incomplet → non résolu. `open_lots`/`unresolved_fills` remontés honnêtement dans le résumé.
- **ANALYTIQUE, jamais un ordre (§2.1)** ; lecture disque offloadée (`to_thread`), hors hot path.
- **Vérif** : 12 tests engine (FIFO, flip partiel, short, contrat inconnu, côté manquant,
  résumé, chargement, dossier absent, bout-en-bout) + 1 test parse côté ; 108 passed, ruff
  clean ; essai réel : 2 fills NT8 (BUY 2 @5000 / SELL 2 @5010) → snapshots avec fill embarqué
  → `GET /analyses/trades` = 1 trade LONG, **P&L 1000 $, R 10.0**, 0 non résolu.
- **Hors-scope (une feature = un commit)** : panneau frontend d'analyse (l'endpoint est prêt) ;
  frais/commissions ; slippage ; risque par-trade réel (R utilise le 100 $ de référence).

### /devil D-033 — durcissement (4 attaques)
Attaques : timestamps désordonnés · positions orphelines · JSON snapshot corrompu/illisible ·
instrument inconnu sans crash. Deux **bugs réels de crash d'endpoint** trouvés et corrigés :
- **JSON corrompu / non-objet (bug → 500)** : `json.load` peut renvoyer une liste/scalaire pour
  un JSON valide-mais-inattendu (`[1,2,3]`) → `data.get(...)` levait `AttributeError` ; et un
  `fill` aux valeurs non numériques (`price:"abc"`) faisait crasher `float()`/`int()`. Corrigé :
  garde `isinstance(data, dict)` + `try/except (ValueError, TypeError)` autour de la coercition →
  fichier écarté (§3), endpoint reste **200**. Prouvé live (5/8 fichiers hostiles écartés, 200).
- **Timestamps désordonnés** : `reconcile_fills` triait déjà par ts ; mais un fill à `ts=None`
  faisait crasher `sorted` (comparaison à None). Corrigé : pré-filtrage des `ts=None` en « non
  résolu » AVANT le tri. Sortie-avant-entrée dans la liste → réappariée correctement (essai).
- **Déterminisme (ex æquo de ts)** : deux snapshots au même ts étaient ordonnés selon
  `os.listdir` (dépendant du FS) → réconciliation non reproductible. Corrigé : tri par
  `(ts, snapshot_id)` → ordre stable indépendant du système de fichiers.
- **Risque de référence 0** (`R_UNIT_USD=0`) : `pnl_usd / 0` → `ZeroDivisionError` + `sum(None)`.
  Corrigé : `r_multiple = None` si risque nul, `total_r` somme seulement les R non-None.
- **Positions orphelines** (déjà géré, testé explicitement) : un lot non fermé reste dans le
  carnet → `open_lots`, aucun trade fabriqué. **Instrument inconnu** (déjà géré) : P&L en points,
  `pnl_usd`/`r_multiple` = None — endpoint sûr (essai : trade XYZ, $/R null, 200).
- **Vérif** : +9 tests /devil (désordre, orphelin, qty ≤ 0, ts None, risque 0, JSON corrompu/
  non-objet, valeurs non numériques, ex æquo déterministe, endpoint instrument inconnu) ;
  117 passed, ruff clean ; essai live sur dossier hostile → **200**, sorties honnêtes.

## D-034 · Vue Analyse P&L (frontend de D-033, `AnalysePnlView.tsx`)
Vue plein écran `PNL` qui consomme `GET /analyses/trades` — **aucune modif backend**. Décisions :
- **VUE, pas panneau (traçabilité §1)** : analytique REST sur des trades réconciliés (projections
  de snapshots), comme JOURNAL/RECAP/BORD — pas un panneau SSE non traçable. Câblée comme les
  autres vues : ViewKey `PNL`, branche `App.tsx`, cycle `V`, mnémonique `PNL` (alias PL/ANALYSE/
  TRADES) + HELP.
- **Résumé (point 1)** : tuiles Total P&L $, Total R, Lots ouverts — valeurs du `summary` backend.
  Lots ouverts > 0 → tuile ambre + « ⚠ » (positions non fermées, signalées honnêtement).
- **Santé (point 2) — calculée côté client depuis la liste** : Win Rate = gagnants/(gagnants+
  perdants) sur les trades à P&L $ connu ; R moyen = moyenne des R non-None. Aucun trade décidé
  → « — » (fail-closed §3, jamais 0 % inventé).
- **Table (point 3)** : trades triés chronologiquement (par `exit_ts`) — Heure, Instrument, Sens,
  Qté, P&L $, R, Durée (`fmtAge`). Contrat inconnu → P&L $/R affichés « — », jamais 0.
- **Code couleur (point 4)** : VERT (R/P&L > 0) / ROUGE (< 0), **strictement réservé au signe du
  P&L/R** — la direction (Sens) est NEUTRE (glyphe ▲/▼ + texte LONG/SHORT) pour ne pas surcharger
  la sémantique couleur (corrigé en auto-revue : un long perdant ne doit pas montrer un ▲ vert).
  §3 daltonisme : couleur JAMAIS seule → toujours glyphe + nombre signé + liseré gauche.
- **Poll 8 s** (hors hot path) ; bouton Actualiser ; état vide honnête et actionnable ;
  `unresolved_fills` > 0 signalé (fills exclus de l'analyse).
- **Vérif** : `tsc` + `vite build` OK ; essai Playwright réel avec données seed (2 ES gagnant/
  perdant + orphelin MES + inconnu XYZ) → Total +750 $, R +7,5, Win Rate 50 %, R moyen +3,75,
  lots ouverts 1, XYZ en « — » ; couleurs vert/rouge vérifiées + capture d'écran. Backend
  inchangé (git : seuls des fichiers frontend modifiés).

### /polish D-034 — tuiles de résumé triables
Les tuiles **Total P&L / Total R / Durée moyenne** deviennent des contrôles de tri de la table.
- **Nouvelle tuile** « Durée moyenne » = moyenne de `exposure_seconds` (côté client, `fmtAge`) ;
  « — » si aucun trade (§3).
- **Interaction** : clic = cycle **↓ décroissant → ↑ croissant → chronologique** (3ᵉ clic) ;
  changer de tuile réinitialise en décroissant. Le tri est instantané (mémoïsé, < 100 ms) et
  ramène la vue en haut de table. Valeurs null (contrat inconnu) TOUJOURS en bas — pas de valeur
  → pas de rang (§3), quel que soit le sens.
- **Indicateur (§3 couleur jamais seule)** : la tuile active porte une bordure + flèche **OR**
  (`router`) et un glyphe ↓/↑ ; les tuiles triables inactives montrent un ↕ estompé
  (affordance découvrable) ; l'en-tête de la colonne triée reçoit la même flèche or. L'OR =
  interactif/actif — volontairement DISTINCT du vert/rouge (signe du P&L/R) et des couleurs
  opérateur. Les tuiles non triables restent des `div` statiques (pas de faux affordance).
- **Découvrabilité (§5)** : `title` par tuile + astuce en pied de vue ; tuiles = `<button>`
  (focus clavier, Enter/Espace natifs).
- **Vérif** : `tsc` + `vite build` OK ; essai Playwright réel (3 trades à P&L/durées indépendants)
  → chrono 1re ligne = perdant ; clic Total P&L → gagnant en tête (↓) ; re-clic → perdant (↑) ;
  clic Durée moyenne → plus longue en tête, flèche migrée vers Durée ; 0 erreur JS + capture.

### /devil D-034 — durcissement (4 attaques)
Attaques : 500+ trades · rendu null/None · race sur clics d'actualisation · resize extrême.
- **500+ trades (bug de perf → corrigé)** : la table rendait TOUTES les lignes (`.map`) et
  re-triait à chaque frame de scroll. Corrigé : table **VIRTUALISÉE** (fenêtre `ROW_H=22` +
  overscan, en-tête `sticky`) + tri mémoïsé. Essai réel 500 trades → **30 lignes en DOM**
  (pas 500), rendu 52 ms, stable au scroll ; agrégats corrects à l'échelle (+25 000 $, +250 R,
  50 %, R moyen +0,50). Sans dépendance (windowing maison, comme la vue Journal de Bord).
- **Race sur clics d'actualisation (bug → corrigé)** : `refresh` n'ordonnait pas les réponses
  concurrentes → une réponse périmée pouvait écraser la fraîche. Corrigé : compteur de requête
  (`reqSeq`) — seule la réponse de la DERNIÈRE requête est appliquée ; les réponses en vol sont
  invalidées au démontage (`reqSeq.current++` au cleanup). Essai : 12 clics rapides → état
  cohérent, **0 erreur JS**.
- **Rendu null/None** (déjà géré, revérifié) : dataset 100 % instruments inconnus → endpoint
  0 gagnant/0 perdant, `r_multiple` null partout → tuiles Win Rate / R moyen = « — »,
  colonnes $/R = « — » (jamais 0 inventé, §3).
- **Resize extrême (320 px)** : la table PNL défile HORIZONTALEMENT dans son cadre
  (`overflow-auto` + `min-w-[560px]` ; mesuré : cadre 291 px, contenu 560 px → scroll interne),
  le corps de page n'est jamais élargi PAR la vue. Les tuiles passent en 2 colonnes, lisibles.
  **Résiduel hors-scope** : à 320 px le débordement horizontal du `body` (≈786 px) vient de la
  barre de statut Zone 0 et de la WorkspaceBar (shell global, présent sur TOUTES les vues), pas
  de la vue PNL — à traiter séparément si le responsive mobile devient une cible.

## D-035 · Cortex Cognitif — bias_detector (Axe 4, `app/bias_detector.py`)
Analyse post-hoc DÉTERMINISTE des CompletedTrades → 3 biais + Psych-Score /100, injectés dans
`GET /analyses/trades` (`res["discipline"]`). Décisions/hypothèses (Loop 1) :
- **ADVISORY, jamais bloquant (§2.1)** : lit des trades DÉJÀ clôturés, annote — aucune décision,
  aucun ordre, aucun verrou. Ne modifie NI ne bloque le flux d'exécution. Hors hot path
  (endpoint, `to_thread`). Aucun LLM (booléens de seuil, reproductible).
- **Enrichissement `entry_delta_anomaly`** : FOMO se définit « suite à anomalie de delta », mais
  le CompletedTrade ne portait pas le contexte d'entrée. Résolu proprement : le snapshot qui
  embarque le fill capture AUSSI `liquidity_sweep` → `load_fills` en dérive `Fill.delta_anomaly`
  (= `liquidity_sweep.triggered`), et `reconcile_fills` reporte l'anomalie du LOT D'ENTRÉE dans
  `CompletedTrade.entry_delta_anomaly`. Champs optionnels (défaut False) → tests D-033 intacts.
- **3 détecteurs (v1)** : 1) **FOMO** = `exposure < FOMO_MAX_DURATION_S` (30 s, PLACEHOLDER) ET
  `entry_delta_anomaly` ; 2) **EXEC_TOO_LONG** = `exposure > EXEC_MAX_DURATION_S` (1800 s,
  PLACEHOLDER) ; 3) **REVENGE** = entrée < `REVENGE_WINDOW_S` (180 s, **AUTORITÉ** — spec « < 3
  min ») après la CLÔTURE d'une PERTE (`pnl_usd < 0`). Seuils FOMO/EXEC à calibrer par l'humain
  (v1 provisional, config).
- **FAIL-CLOSED (§3)** : champ manquant/None → le détecteur concerné ne se déclenche pas (jamais
  un biais inventé). FOMO exige une anomalie CONNUE (pas d'anomalie → pas de FOMO).
- **Psych-Score = PROCESSUS, pas résultat (§2.7)** : `round(100 × trades_sans_biais / total)` —
  % de trades disciplinés (v1 provisional). Aucun trade → **None** (jamais un faux 100). N'est
  JAMAIS consolidé avec le P&L (result score) ; les deux coexistent dans le payload, séparés.
- **Payload** : `discipline = {psych_score, total_trades, biased_trades, clean_trades,
  biases_by_type, biases:[{type, trade_index, instrument, entry_ts, exit_ts, exposure_seconds,
  detail}]}`. Un trade à plusieurs biais compte UNE fois dans `biased_trades` (N findings).
- **Vérif** : 14 tests bias_detector (FOMO + garde anomalie, EXEC seuil, REVENGE fenêtre/gain,
  Psych 100/50/0/None, multi-biais, sérialisation) + 3 tests reconciliator (extraction anomalie,
  report d'entrée, endpoint discipline) ; 134 passed, ruff clean ; essai live : 4 trades (perte
  clean + revenge + FOMO + trop long) → **Psych-Score 25/100**, 3 biais typés, réponse purement
  descriptive. Backend seul (le payload gagne `discipline` sans casser la vue PNL existante).
- **Hors-scope (une feature = un commit)** : surface frontend du Psych-Score/biais (panneau
  « Cortex » — l'endpoint est prêt) ; calibration des seuils ; pondération sévérité par biais.

### /polish D-035 — surface « Cortex » dans la vue PNL (frontend)
Le Psych-Score + les biais (payload `discipline`) sont rendus dans `AnalysePnlView` — backend
inchangé.
- **Widget Cortex** : ligne « CORTEX COGNITIF · Psych-Score N/100 » — **vert si ≥ 80**, **ambre
  si < 80**, « — » si None (§3 : couleur + glyphe ✓/⚠/· + libellé « /100 »). Puis les compteurs
  de biais par type (chips ambre `⚡FOMO`, `↻REVENGE`, `⏱LENT`) OU « ✓ aucun biais détecté », et
  « X/Y trades biaisés ». Le widget sert AUSSI de légende des icônes de la table.
- **Colonne « Biais » par ligne** : icône ambre par biais (`⚡`/`↻`/`⏱`), **infobulle = explication
  française complète** (`detail`) au survol. L'ambre = avertissement comportemental, distinct du
  vert/rouge (signe P&L) et de l'or (interactif) — sémantique couleur préservée (§3).
- **Virtualisation fluide** : les biais sont indexés dans une **Map par `trade_index` d'origine**
  (lookup O(1) par ligne, mémoïsée) ; chaque trade trié porte son `_idx` d'origine pour retrouver
  ses biais malgré le tri. Aucun recalcul par frame de scroll → pas de saccade (durcissement
  /devil préservé).
- **Découvrabilité (§5)** : légende des icônes en pied de vue + dans le widget ; `title`/
  `aria-label` sur chaque icône. **Fail-closed** : `discipline` absent ou `psych_score` None →
  « — » / « aucun biais », jamais un score inventé.
- **Vérif** : `tsc` + `vite build` OK ; essai Playwright réel (seed 4 trades biaisés) → widget
  Cortex, Psych-Score 25/100 en AMBRE, 3 icônes de biais en ligne + infobulle FOMO, 0 erreur JS
  + capture. Backend inchangé (git : seul `AnalysePnlView.tsx`).

### /devil D-035 — durcissement (4 attaques)
Attaques : biais cumulés sur un trade · timestamps identiques/inversés · séquences massives ·
division par zéro / score négatif.
- **Séquences massives (bug de perf → corrigé)** : REVENGE était en O(n²) (double boucle) —
  mesuré 5000 trades = **1316 ms** (endpoint bloqué sur gros historique). Corrigé : clôtures des
  pertes pré-triées + **bisect** (O(n log n)), auto-exclusion préservée. Après : 5000 = **50 ms**,
  20000 = 184 ms ; sortie identique (essai : Psych-Score 25, mêmes biais). Test : 5000 trades
  < 0,5 s.
- **Timestamps identiques/inversés** : entrée EXACTEMENT à la clôture d'une perte (gap 0) →
  revenge (correct) ; une perte à durée nulle (entry==exit) ne se déclenche PAS revenge sur
  elle-même (auto-exclusion via `self_counted`) ; **durée négative** (timestamps inversés) → pas
  de FOMO (garde `0 ≤ durée`, fail-closed §3). Rappel : le réconciliateur trie les fills → une
  durée d'exposition est TOUJOURS ≥ 0 en amont ; la garde protège les appels directs.
- **Biais cumulés sur un trade** (déjà géré, testé) : REVENGE + FOMO sur le même trade → 2
  findings mais **1 seul trade biaisé** (`biased_trades` dédoublonne par `trade_index`). FOMO et
  EXEC_TOO_LONG sont mutuellement exclusifs (durée < 30 s vs > 1800 s).
- **Division par zéro / score négatif** (déjà sûr, testé) : `biased ≤ total` (indices ⊆
  {0..total−1}) → `clean ≥ 0` → score ∈ [0, 100], jamais négatif ni > 100 ; `total == 0` → None
  (aucune division). Non-numérique (pnl/exit) filtré (`_num`) → pas de crash de tri.
- **Vérif** : +6 tests /devil ; 140 passed, ruff clean ; perf mesurée avant/après + essai live
  inchangé.

## D-036 · Heatmap de liquidité (LOB) — `s1_state.liquidity_heatmap` + Canvas
Profondeur HISTORIQUE du carnet L2 rendue en HTML5 Canvas. Décisions/hypothèses (Loop 1) :
- **Schéma (MetaField)** : `s1_state.liquidity_heatmap` — value `{columns: [{ts, bids:[[p,s]…],
  asks:[[p,s]…]}…], max_size}`. Fenêtre glissante (`HEATMAP_COLS=60` ≈ 15 s à 4 Hz), `levels`
  par côté = `BOOK_DEPTH` (10). **Canal RAPIDE** : `s1_state` est déjà dans `FAST_BLOCKS` → poussé
  au tick rapide (0,25 s = **4 Hz**), sans nouveau canal.
- **Réutilise le carnet existant** : pas de nouveau pipeline d'ingestion L2 — la heatmap accumule
  `order_book` (D-025) en colonnes temporelles (`app/heatmap.py::accumulate_heatmap`, pur/testé).
  L'accumulation est sur le hot path mais O(cols×levels) — append + borne, trivial (§7).
- **FAIL-CLOSED (§3)** : carnet non FRESH (STALE/ABSENT) → AUCUNE colonne inventée ; l'historique
  est conservé, la fraîcheur du bloc SUIT le carnet. Le panneau : STALE → « FIGÉ » + grisé,
  ABSENT/vide → « PAS DE DONNÉES ».
- **Canvas haute-performance** : un seul `<canvas>` (DPR-scalé, ResizeObserver), redessiné à
  chaque update SSE (4 redraws/s, ~1200 rects — trivial). Temps = X, prix = Y, taille = intensité
  (bids VERT sous le mid / asks ROUGE au-dessus : côté encodé par couleur ET position). **Aucun
  nœud DOM par cellule** (essai : 1 canvas, 4 div dans le panneau, pas ~1000) → pas de surcharge
  DOM. **Lecture seule** : aucun affordance de passage d'ordre (§2.1).
- **Câblage** : `PANEL_IDS` + registre (`HM`), ajouté à l'espace **MICRO** (bump `STORAGE_KEY`
  v6→v7 — layouts persistés repartent des intégrés), mnémonique `HM` (zone B). Traçable §1 :
  un panneau = un bloc.
- **Vérif** : 7 tests backend (append FRESH, borne, fail-closed STALE/ABSENT, troncature levels,
  max_size) ; 147 passed, ruff clean ; `tsc` + `vite build` OK ; essai réel : engine accumule
  12 colonnes/3 s (FRESH, max_size réel), Canvas dessiné (55 % de pixels peints, 24 colonnes),
  0 erreur JS + capture.
- **Hors-scope (une feature = un commit)** : axes de prix/temps annotés ; survol → prix/taille ;
  agrégation multi-tick par colonne. (La **diffusion en DELTA** — initialement hors-scope — a été
  faite au /polish ci-dessous.)

### /devil D-036 — durcissement (5 cas limites)
Attaques : carnet vide · croisé · prix NaN/Inf · afflux massif · resize 0×0. Résultat : le
frontend ne crashe sur AUCUN (essai Playwright SSE gelé — 0 erreur JS).
- **NaN/Inf** : la source amont (`_validate_order_book`, D-025) RETIENT déjà tout carnet
  non-fini (→ ABSENT/MALFORMED), donc aucune valeur non-finie n'atteint le heatmap. Double
  sécurité ajoutée : `_finite_levels` filtre au niveau du heatmap (garantit un JSON SSE jamais
  NaN/Inf → pas de parse cassé). Frontend : `draw` ignore tout prix/taille non-fini (Canvas
  ignore de toute façon les rects NaN). Un côté entièrement non-fini → colonne écartée.
- **Carnet croisé** (bid ≥ ask) : donnée finie pathologique → colonne CONSERVÉE (honnête, §3 —
  on n'efface pas une pathologie réelle ; le flag `CROSSED_BOOK` du carnet est propagé). Rendu
  sans crash (chevauchement vert/rouge).
- **Carnet vide** : aucune colonne (§3) → panneau « PAS DE DONNÉES ».
- **Afflux massif** : niveaux tronqués à `BOOK_DEPTH`, colonnes bornées à `HEATMAP_COLS` ;
  frontend testé jusqu'à 500 colonnes → rendu Canvas < 500 ms, pas de saccade.
- **Resize 0×0** (panneau masqué) : le `useEffect` de dessin garde `box.w/h === 0` → aucun dessin,
  pas de crash ; réaffichage → redessine.
- **Colonnes malformées** (null / champs manquants / mauvais types) : `draw` garde `Array.isArray`
  par colonne et par côté → ignorées sans crash.
- Affordance de test DEV-only `window.__setHeatmap` (élaguée en prod par `import.meta.env.DEV`)
  pour forcer ces états. +4 tests backend (filtre non-fini, croisé, tout-non-fini, massif borné).

### /polish D-036 — diffusion en DELTA (payload allégé ~60×)
Le backend n'émet plus la fenêtre entière à chaque tick, mais **la seule colonne courante**
(`value = {column: {ts, bids, asks} | null}`, `heatmap.py::latest_column`). Le **frontend
accumule** les colonnes successives dans un tampon local (`bufferRef`, borné à `MAX_COLS=60`,
dédup par `ts` croissant) et calcule lui-même `max_size` sur la fenêtre. `accumulate_heatmap` +
l'état `_heatmap_cols` du moteur sont supprimés (le moteur est sans état pour ce bloc).
- **Gain** : bloc SSE ~**503 octets** (1 colonne, 20 niveaux) vs ~30 Ko (60 colonnes) → ~60×.
  Cohérent CLAUDE §6 (« events SSE partiels par bloc »).
- **Tradeoff assumé** : l'historique est côté client → au montage / après reconnexion, la fenêtre
  se **reconstruit en ~15 s**. `ts = now` (temps du tick) → une colonne par tick même si le carnet
  ne bouge pas (trame temporelle régulière).
- **Fraîcheur** : FRESH → accumule ; **STALE** → tampon conservé, grisé + « FIGÉ » ; **ABSENT** →
  tampon vidé (§3, la donnée a disparu) → « PAS DE DONNÉES ». Fenêtre calée à DROITE (récent au
  bord droit) pendant le remplissage.
- **Vérif** : 10 tests backend (colonne courante, ts=tick, None si STALE/ABSENT/vide, troncature,
  + /devil non-fini/croisé/massif conservés) ; 150 passed, ruff clean ; `tsc` + `vite build` OK ;
  essai Playwright réel : accumulation 8 → 20 colonnes en 3 s, Canvas dessiné, 1 canvas / 4 div,
  0 erreur JS + capture.

## D-037 · Footprint + imbalances (`s1_state.footprint` + Canvas)
Agrégation du Time & Sales par bougie/niveau (Bid×Ask), imbalances diagonales, POC. Décisions :
- **Schéma (MetaField)** `s1_state.footprint` — value `{candles: [{start_ts, end_ts, open, high,
  low, close, poc, total_volume, levels: [{price, bid_vol, ask_vol, imbalance ∈ ASK|BID|null}]}],
  tick, ratio, candle_seconds}`. Canal RAPIDE (`s1_state`). Lecture seule (§2.1).
- **Approche mathématique** (`app/footprint.py::build_footprint`, pur/déterministe) : BUY =
  agresseur à l'ASK (`ask_vol`), SELL = au BID (`bid_vol`) ; prix quantifié sur la grille de
  tick (`k = round(prix/tick)`). **Imbalance DIAGONALE** (ratio R, plancher M) : niveau `k` =
  **ASK** si `ask_vol[k] ≥ R·bid_vol[k−1]` ET `ask_vol[k] ≥ M` ; **BID** si `bid_vol[k] ≥
  R·ask_vol[k+1]` ET `bid_vol[k] ≥ M` (les deux → côté au volume dominant). **POC** = niveau au
  volume total max. Ratio = **AUTORITÉ** (spec : 300 % → 3.0) ; durée de bougie (60 s), plancher
  (1) = **v1 provisional** (config, à calibrer).
- **Ingestion** : le moteur accumule les prints NEUFS du tape (seq-dédup + re-baseline sur
  régression, comme le CVD D-029) dans un buffer borné (`FOOTPRINT_MAX_PRINTS=800`), puis
  `build_footprint` construit les bougies. Hot path O(prints), borné (§7). Fail-closed (§3) :
  tape non FRESH → pas d'accumulation, fraîcheur propagée ; prix/taille non-fini, côté inconnu →
  ignorés (jamais un volume inventé).
- **Frontend Canvas** (`FootprintImbalancePanel`) : colonnes = bougies, lignes = niveaux (axe
  prix partagé) ; chaque cellule `bid×ask` ; **surbrillance d'imbalance** (fond VERT ASK + ▲ /
  ROUGE BID + ▼ — couleur JAMAIS seule §3) ; **POC** marqué en OR (liseré) ; fine bougie OHLC
  (rappel de l'action des prix). Grille dimensionnée au CONTENU → défile (cellules lisibles),
  un seul `<canvas>` (aucun DOM par cellule). Lecture seule (§2.1). STALE→FIGÉ, vide→PAS DE
  DONNÉES. Câblé : registre `FP`, espace MICRO (bump `STORAGE_KEY` v7→v8), mnémonique `FP`.
- **Vérif** : 13 tests backend (agrégation Bid×Ask, POC, imbalance ASK/BID/vs-vide/sous-ratio,
  bucketing, OHLC, quantification, cap, fail-closed non-fini/côté) ; 163 passed, ruff clean ;
  `tsc` + `vite build` OK ; essai réel : engine agrège 1 bougie (POC 5450.5, imbalances ASK
  détectées), Canvas dessiné (1 canvas / 5 div, bid×ask + surbrillance + POC), 0 erreur JS +
  capture.
- **Hors-scope (une feature = un commit)** : superposition sur un vrai graphe chandelier
  multi-bougie complet ; agrégation Value Area ; empilement d'imbalances (stacked) ; survol →
  détail. (Le tape étant une fenêtre bornée, les bougies se remplissent au fil du temps.)

### /devil D-037 — anomalies de flux critiques
Attaques : division /0 du ratio · prix hors-grille · rafales à ts identiques · bougie à niveau
unique · (frontend) prix NaN/Inf, volume gigantesque, /0 de la taille de cellule.
- **Division par zéro (ratio)** : IMMUNE par construction — la formule est MULTIPLICATIVE
  (`ask ≥ ratio·bid[k−1]`), jamais une division. Diagonale à volume nul → condition vraie
  gatée par le plancher `min_vol`. Test dédié.
- **Rafale à timestamps identiques (bug OHLC → corrigé)** : `open` utilisait `<=` → écrasé par
  le DERNIER print de la rafale. Corrigé en `<` strict → `open` = 1er print de l'ordre d'entrée,
  `close` = dernier (`>=`). Test dédié.
- **Prix hors-grille** : `round(prix/tick)` snappe TOUT prix fini sur la grille ; deux prix
  aberrants lointains → niveaux épars, pas de crash (test snap). **tick ≤ 0** → `build_footprint`
  renvoie `[]` (fail-closed).
- **Bougie à niveau unique** (O=H=L=C, un seul prix) : POC = ce niveau, imbalance vs diagonale
  vide, OHLC égaux — aucun crash (test dédié).
- **Frontend blindé** (essai Playwright SSE gelé — **0 erreur JS**, UI réactive) : `fmt` gère
  non-fini (« · ») et gros volumes (k/M → cellule jamais débordée) ; garde `!(tick > 0)` capture
  0 ET NaN ; **fenêtre de prix bornée à `MAX_ROWS=400`** → un prix aberrant lointain n'explose
  jamais la hauteur du canvas (mesuré < 40 000 px) ; boucle de cellules ignore prix non-fini /
  hors-fenêtre ; OHLC dessiné seulement si fini. Aucune division locale de taille (cellules à
  dimensions FIXES). Hook DEV `window.__setFootprint` (élagué en prod) pour forcer ces états.
- **Vérif** : +5 tests backend (rafale OHLC, niveau unique, prix aberrant, diagonale nulle,
  tick 0/négatif) ; 168 passed, ruff clean ; essai Playwright 7 pathologies → 0 erreur JS.

### /polish D-037 — clarté cognitive & précision graphique du Canvas
Loop 5 sur le rendu (aucune logique métier touchée). Les 4 axes demandés :
- **1. Alignement au pixel** : toutes les coordonnées de tracé passent par `R = Math.round`
  (`yOf` renvoie un entier, remplissages sur bornes rondes) ; les traits 1 px (mèche OHLC,
  contour POC) sont posés sur la demi-grille (`R(x)+0.5`) → arêtes nettes à 100 % de zoom, sans
  flou d'anti-aliasing. Essai : front doré du POC = colonne franche (barre gauche 2 px + bords).
- **2. Échelle typographique adaptative + AJUSTEMENT AU PANNEAU** : `ResizeObserver` mesure le
  conteneur ; cellules bornées (`CW ∈ [40,132]`, `RH ∈ [12,26]`) qui **s'étirent** quand le
  panneau grandit et **défilent** quand c'est dense. La police est choisie par `measureText` sur
  la cellule la plus large (tient en largeur ET hauteur → séparateur/glyphe ▲▼ ne chevauchent
  jamais les chiffres) ; sous un seuil lisible, `showText` masque le texte plutôt que de le
  tasser. Correctif de conteneur : `h-full` sur la colonne flex (sinon le wrap s'effondrait à
  1 px — le canvas mesurait la boîte, pas l'inverse). Essai : panneau large → canvas 512 px,
  étroit → 290 px (les cellules suivent la largeur réelle).
- **3. Intensité visuelle (alpha ∝ volume)** : le fond d'imbalance module son opacité selon le
  volume du côté imbalancé rapporté au max de la bougie — `alpha = 0.12 + 0.32·min(1, vol/sideMax)`
  (plancher 0.12 pour rester visible, plafond 0.44 pour ne jamais noyer le texte). Plus
  l'imbalance est forte, plus la couleur est affirmée. Essai : fond fort (ask 300) alpha 112/255
  vs faible (ask 20) alpha 36/255 → dégradé mesuré ×3, texte lisible dans les deux.
- **4. POC au premier plan** : la barre + le contour OR sont dessinés **en DERNIER** dans chaque
  cellule (après fond d'imbalance ET texte) → le marqueur POC reste net même superposé à une
  imbalance active. Essai : niveau POC == imbalance ASK → or ET vert coexistent (or au-dessus).
- **Vérif** : `tsc --noEmit` + `vite build` OK ; essai Playwright `/polish` (SSE gelé, 4 axes
  validés au pixel) **0 erreur JS** + captures (live, POC/imbalance, dégradé alpha) ; ré-essai
  `/devil` (7 pathologies) → **0 erreur JS** (blindage préservé après réécriture du rendu).

## D-038 · CVD granulaire stratifié par taille (`s1_state.cvd_stratified` + Canvas)
CVD segmenté par STRATE DE TAILLE d'ordre (retail vs institutionnel) + divergence prix↔CVD
institutionnel. Décisions :
- **Schéma (MetaField)** `s1_state.cvd_stratified` — value `{size_threshold, series: [{ts, price,
  retail, institutional, total}…], divergence: {kind ∈ BULLISH|BEARISH, price_change, inst_change,
  bars} | null}`. Canal RAPIDE (`s1_state`). Lecture seule (§2.1). Distinct de `order_flow.cvd`
  (scalaire) et `cvd_by_level` (par PRIX, D-029) : ici l'axe est la TAILLE d'ordre.
- **Classification + maths** (`app/cvd_stratified.py::build_cvd_stratified`, pur/déterministe) :
  chaque print classé `institutional` si `size ≥ size_threshold`, sinon `retail` ; delta agresseur
  BUY = +size / SELL = −size ; agrégé par BUCKET temporel puis **cumulé chronologiquement par
  strate** (retail / institutional / total) ; `price` du point = dernier prix (ts max) du bucket.
- **Divergence (advisory §2.1)** : sur la fenêtre `lookback`, comparaison des DIRECTIONS prix vs
  CVD institutionnel avec **deadbands** (`min_price_move`, `min_delta_move` → jamais un faux
  signal) : prix ↓ + inst ↑ = **BULLISH** (accumulation cachée) ; prix ↑ + inst ↓ = **BEARISH**
  (distribution). N'annote jamais un ordre, ne bloque ni ne modifie l'exécution (§2.1).
- **Seuil retail/institutionnel `CVD_SIZE_THRESHOLD`** = **v1 provisional** (PLACEHOLDER §11 —
  pas d'AUTORITÉ dans /reference ; calibration owner: Sony ; défaut 10). Bucket (5 s), fenêtre de
  série (120 pts), lookback (12), deadbands = v1 provisional (config, à calibrer).
- **Ingestion** : le moteur accumule les prints NEUFS du tape (seq-dédup + re-baseline sur
  régression, comme CVD D-029 / footprint D-037) dans un buffer borné (`CVD_STRAT_MAX_PRINTS`),
  puis `build_cvd_stratified` construit la série. Hot path O(prints), déterministe, zéro LLM (§7).
  Fail-closed (§3) : tape non FRESH → pas d'accumulation, fraîcheur propagée ; prix/taille
  non-fini, côté inconnu → ignorés (jamais un delta inventé) ; JSON strict `allow_nan=False` OK.
- **Frontend Canvas** (`CvdStratifiedPanel`, code `CDS`) : 3 lignes de CVD cumulé (INSTITUTIONNEL
  violet épais / RETAIL gris fin / TOTAL clair tireté) sur ligne de base ZÉRO ; la STRATE est
  encodée par couleur ET style de trait ET libellé de légende (jamais la couleur seule §3) ; la
  PENTE porte le sens (montée = achat net). Bande + badge de divergence (VERT ⤴ accumulation /
  ROUGE ⤵ distribution). **INTERACTIF** : survol → réticule + infobulle (inst/retail/total/prix).
  Un seul `<canvas>` DPR-scalé, aucun DOM par point. STALE→FIGÉ, vide→PAS DE DONNÉES. Câblé :
  registre `CDS`, espace MICRO (bump `STORAGE_KEY` v8→v9), mnémonique `CDS`, hook DEV `__setCvdStrat`.
- **Vérif** : 16 tests backend (classification par seuil/inclusif, signe delta, cumul multi-bucket,
  bucketing, prix=dernier, divergence BULLISH/BEARISH/aligné/sous-deadband/point unique, vide,
  fail-closed non-fini/côté, cap max_points, seuil échoué) ; 166 passed, ruff clean ; `tsc` +
  `vite build` OK ; essai Playwright réel : engine agrège la série live (retail/inst/total,
  divergence détectée sur données réelles), multi-ligne dessiné (violet inst visible), survol →
  infobulle, BULLISH/BEARISH forcés → badge + bande, **0 erreur JS** + captures.
- **Hors-scope (une feature = un commit)** : 3+ strates (retail/mid/inst) ; profil de volume par
  strate ; corrélation glissante prix↔CVD ; export ; superposition sur le graphe de prix.

### /devil D-038 — anomalies de flux critiques
Attaques : flux massifs · taille == seuil (`>=`) · prix NaN/Inf · série de delta PLATE (variation
nulle → /0 de pente/divergence ?) · (frontend) valeurs non-finies, resize 0×0, survol hors cadre.
- **Backend division-free (pente/divergence)** : la divergence compare des DIRECTIONS
  (soustraction + deadbands), **jamais une division** → une série plate ne peut pas provoquer de
  /0 ; le seul quotient est `floor(ts/bucket_seconds)`, gaté `bucket_seconds > 0`. Tests :
  série plate delta-nul (30–40 pts) → divergence None, aucune erreur ; prix figé → pas de faux
  signal (deadband prix).
- **Flux massifs** : 50 000 prints → série bornée à `max_points`, **toutes valeurs finies**,
  < 0,15 s ; en live le moteur borne déjà le tampon à `CVD_STRAT_MAX_PRINTS`. Test dédié.
- **Seuil exact `>=`** : 9.99 → retail ; 10.0 (== seuil) → institutional ; 10.01 → institutional.
  Seuil ≤ 0 → tout institutionnel, aucun crash. Tests dédiés.
- **Prix/ts NaN/Inf** : filtrés en amont (`math.isfinite` + côté ∈ BUY/SELL) → jamais un delta
  inventé (§3). Test dédié.
- **Frontend — 2 bugs RÉELS trouvés & corrigés** (essai Playwright SSE gelé, **0 erreur JS**) :
  1. **Badge divergence — crash `.toFixed` sur `undefined`/non-fini** : une divergence forcée/
     corrompue sans `price_change` (ou avec `±Infinity`/`NaN`) faisait planter le rendu du badge
     (`undefined.toFixed(2)` → TypeError). Corrigé par `signed()` : non-fini/absent → « · »
     (jamais un « NaN » brut affiché §3). Test : divergence extrême (prix 1e12, Δ non-finis) +
     champs manquants → badge propre, 0 erreur.
  2. **Survol — index NaN sur panneau très étroit** : si `plotW ≤ 0` (largeur < gouttières),
     `(hoverX−PAD_L)/plotW` = ±∞/NaN → `series[NaN]` undefined → crash sur `.institutional`.
     Corrigé : garde `plotW > 0` + `Number.isFinite(rawI)` + point valide requis (le survol
     dégrade proprement plutôt que planter).
- **Chemins déjà sûrs confirmés** : valeurs de série non-finies (étendue Y les ignore + segment de
  ligne coupé) ; **resize 0×0** (retour anticipé `W<4 || H<4`) ; survol X extrême / hors cadre
  (index borné) ; série plate `ymax==ymin` (padding ±1, pas de /0) ; série non-tableau
  (`Array.isArray` → PAS DE DONNÉES honnête).
- **Vérif** : +7 tests backend (flux massif, seuil exact, plat delta-nul, prix figé, NaN/Inf,
  lookback > série, seuil ≤ 0) ; **191 passed**, ruff clean ; `tsc` + `vite build` OK ; essai
  Playwright 7 pathologies + balayage de survol hors cadre → **0 erreur JS**, UI réactive.

### /polish D-038 — réticule net, contraste, échelle dynamique
Loop 5 sur le rendu (aucune logique métier touchée). 3 axes :
- **1. Alignement au pixel (réticule + infobulle)** : réticule vertical sur la demi-grille
  (`R(x)+0.5`), points de survol à centres entiers (`R(x)`, `R(yOf)`), boîte + texte d'infobulle
  et étiquettes d'axe sur bornes entières → arêtes nettes, aucun flou d'anti-aliasing. (Les
  courbes de données restent lissées : l'anti-aliasing y est voulu pour des diagonales douces.)
- **2. Lisibilité des couleurs (fond sombre)** : la ligne RETAIL passait du gris « faint »
  `#67788f` (contraste ~2:1, sous le seuil) à un gris-bleu lisible `#94a3b8` ; contraste WCAG
  1.4.11 MESURÉ sur le fond réel du panneau — **inst 7.06 · retail 7.49 · total 12.81**, tous
  ≥ 3:1. Strate toujours encodée couleur ET style de trait ET légende (§3). Légende synchronisée.
- **3. Échelle dynamique douce** : la fenêtre Y est LISSÉE (`rangeRef`) — à chaque donnée, on
  vise l'étendue des 3 strates + 8 % de marge, on **EXPANSE instantanément** (jamais de rognage
  d'un pic RÉEL, §3) mais on **CONTRACTE en douceur** (easing 0.28) → l'axe respire, un pic
  n'écrase pas le graphe et l'axe ne snappe pas. Le survol/resize ne relancent pas le lissage
  (l'axe est stable au survol). Essai : pic ×40 → ligne repoussée instantanément (9→36 px) puis
  retour GRADUEL (35→9 px sur ~24 ticks), convergence au régime (Δ ≤ 3 px).
- **Vérif** : `tsc --noEmit` + `vite build` OK ; essai Playwright `/polish` (contraste ≥ 3:1
  mesuré, échelle instant-expand/eased-contract mesurée au pixel) **0 erreur JS** + captures
  (live, survol net).

## D-039 · Chaîne d'options (OMON) + Term Structure de volatilité (VTS)
Moniteur de chaîne d'options (Calls/Puts, IV, Grecques) + structure de vol VIX. Décisions :
- **Bloc `vol_surface` (canal LENT)** — 2 champs : `options_chain` + `term_structure`. Comme la
  vitesse du moteur Greeks est INCONNUE (§8-B2), la fraîcheur suit l'ÂGE réel de la donnée →
  STALE honnête, jamais un chiffre inventé (§3). Lecture seule (§2.1). 1 panneau = 1 champ (§1) :
  OMON lit `options_chain`, VTS lit `term_structure`.
- **`build_options_chain`** (`app/options_chain.py`, pur/déterministe) : agrège Calls/Puts par
  EXPIRATION puis STRIKE, porte IV + Grecques (delta, gamma, vanna, charm) ; MONEYNESS
  déterministe vs sous-jacent + bande ATM (CALL ITM si strike < U, PUT en miroir) ; strikes triés,
  expirations triées DTE croissant (bornées), strikes bornés aux plus proches du sous-jacent ;
  `atm_strike` = strike le plus proche. Fail-closed (§3) : strike non-fini → ligne ignorée ; IV/
  grecque non-finie → None ; sous-jacent non-fini → moneyness None.
- **`build_term_structure`** : ordonne VIX9D/VIX/VIX3M/VIX6M par jours, classe l'état CONTANGO
  (front < back), BACKWARDATION (front > back), FLAT (|Δ| ≤ eps) ; `< 2` points finis → état None
  (jamais un faux régime). Advisory (§2.1).
- **Bande ATM + eps FLAT** = **v1 provisional** (PLACEHOLDER §11 — pas d'AUTORITÉ ; à calibrer).
  Bornes d'affichage (4 échéances, 13 strikes) en config. Ténors VIX = jours CBOE standards.
- **Mock (§4, « un mock propre est un piège »)** : chaîne synthétique (smile actions — IV↑ puts
  OTM, delta logistique, gamma pic ATM, vanna/charm petits) + structure VIX (contango normal,
  bascule backwardation en régime tendu). Pathologies injectées : IV/grecque NaN rare, patte
  manquante → le moteur les écarte SEUL. Émise via `greeks_engine`/`cboe` ; le moteur lit + classe.
- **Frontend** : `OptionsChainPanel` (OMON, code `OMON`) DIVISÉ en deux — SKEW/SMILE Canvas (IV
  Call sky / Put rose vs strike, marqueur ATM or) + GRILLE haute densité (Call/Put, IV + grecque
  SÉLECTIONNABLE Δ/Γ/Vanna/Charm, ligne ATM surlignée, moneyness par position+libellé, §3) ;
  INTERACTIF (onglets d'échéance + sélecteur de grecque). `TermStructurePanel` (VTS, code `VTS`) :
  courbe 4 ténors Canvas + badge CONTANGO ↗ / BACKWARDATION ↘ / FLAT (glyphe+texte+couleur, §3).
  Câblés : registre, `SLOW_BLOCKS` SSE, espace MACRO (bump `STORAGE_KEY` v9→v10), mnémoniques
  `OMON`/`VTS`, hook DEV `__setVolSurface`.
- **Vérif** : 16 tests backend (moneyness ITM/ATM/OTM, atm proche, IV/greeks portés, tri, cap DTE/
  strikes, fail-closed strike/greek/sous-jacent, contango/backwardation/flat, ordre, filtre
  non-fini, insuffisant) ; 189 passed, ruff clean ; `tsc` + `vite build` OK ; essai Playwright réel :
  chaîne live (underlying, 4 échéances × 13 strikes, smile, pathologie IV « · »), skew 2 lignes,
  grille + bascule échéance/grecque, VTS courbe contango, **0 erreur JS** + captures.
- **Hors-scope (une feature = un commit)** : surface 3D IV ; Greeks agrégés (net GEX/DEX par
  strike) ; historique de skew ; pin risk ; smile arbitrage-free ; survol d'infobulle sur le skew.

### /devil D-039 — conditions limites
Attaques : sous-jacent 0/négatif/NaN · chaîne géante 500+ strikes · IV/temps nul-non-fini (/0
grecques/moneyness) · expirations corrompues · (frontend) IV NaN au skew, sauts de strikes, resize
0×0, bascule rapide onglets/grecques (crash `.toFixed`/index).
- **Builders division-free** : `build_options_chain` ne CALCULE aucune grecque (elle les PORTE) et
  le moneyness est une comparaison — **aucune division** → un IV/temps nul ne peut pas provoquer de
  /0. Le seul risque était le sous-jacent bidon → durci.
- **2 bugs RÉELS backend trouvés & corrigés** :
  1. **Sous-jacent ≤ 0** (0/négatif) était classé contre un 0 bidon (tous calls OTM). Corrigé :
     `underlying > 0` requis, sinon `underlying=None` → moneyness None (indécidable honnête §3).
  2. **`raw` non-liste** (`None`, dict) → `TypeError` à l'itération. Corrigé : garde `isinstance
     list` dans les deux builders → structure vide, jamais un crash.
- **Chaîne géante** : 600 strikes → bornage aux `max_strikes` plus proches (tri O(n log n)), fini.
  Expirations corrompues (non-dict, `strikes` non-liste, entrée non-dict) → écartées ligne par
  ligne. `dte` non-fini → None (tri non cassé). Tests dédiés.
- **2 durcissements frontend** (essai Playwright SSE gelé, **0 erreur JS**) :
  1. **`exp.rows` non-tableau** → `.map`/`for…of` planterait le skew et la grille. Corrigé par
     garde `Array.isArray` (rows non-tableau → vide).
  2. **Point de term structure à valeur non-finie/absente** → NaN dans l'étendue + `.toFixed` sur
     `undefined`. Corrigé : la courbe VTS ne garde que les points ENTIÈREMENT finis (comme le
     builder), `noData` honnête si aucun.
- **Chemins déjà sûrs confirmés** : IV/greeks non-finis au skew (étendue les ignore + segment
  coupé) ; `num`/`pct`/`signed` gèrent non-fini/undefined (« · », jamais `.toFixed` cru) ; index
  d'échéance borné (`Math.min(expIdx, exps.length−1)`) ; resize 0×0 (retour `W<4||H<4`) ; bascule
  rapide onglets+grecques → 0 crash ; chaîne géante (200 strikes) rendue sans planter.
- **2e passe (durcissement + audit)** : **strikes DUPLIQUÉS** dans une échéance (donnée
  corrompue) produisaient 2 lignes → collision de clé React (`key={strike}`) en aval. Corrigé :
  dédup par strike dans `build_options_chain` (dict, dernière occurrence gagne) → 1 ligne/strike,
  clé unique. Audit confirmé : la **boucle lente est résiliente** (`while True` + `try/except` →
  log + reprise à la cadence suivante → fail-closed, le schéma vieillit vers STALE ; une exception
  de tick datasource ne tue jamais la boucle, RUNTIME_LOOPS) ; le mock calcule des grecques avec
  divisions par `underlying` mais mean-reverte ~5000 (jamais 0) et toute exception serait
  rattrapée par la boucle ; chaîne à 50 échéances → bornée aux 4 plus proches (DTE). Tests dédiés
  (dédup last-wins, cap 4/50 échéances).
- **Vérif** : +9 tests backend au total (sous-jacent ≤ 0, chaîne géante, dte non-fini, expirations
  corrompues, raw non-liste, term structure géante, dédup strikes, cap échéances) ; **215 passed**,
  ruff clean ; `tsc` + `vite build` OK ; essais Playwright : 6 pathologies + martèlement onglets/
  grecques + viewport minuscule (1re passe) et live 13 strikes DISTINCTS + martèlement ×3 (2e
  passe) → **0 erreur JS**, UI réactive.
- **3e passe (audit, aucun correctif)** : nouveaux angles (pattes non-dict/absentes, moneyness
  poubelle, ATM hors-plage, IV 1e12/1e-12, jours identiques, `expirations` non-tableau, `value`
  non-objet) → **0 erreur JS**. Builders **stateless** (aucun `self._` — pas de race/backpressure,
  §2). Convergence : la boucle `/devil` est stoppée (CLAUDE §13, pas de brute-force).

### /polish D-039 — lisibilité grille dense + repères skew/term structure
Loop 5 sur le rendu (aucune logique métier touchée). Améliorations :
- **Mur de la monnaie (grille OMON)** : les cellules ITM portent un fond TEINTÉ discret (côté call
  sky, côté put rose) → la zone in-the-money se lit d'un coup d'œil. Redondant avec la clarté du
  texte (ITM clair / OTM estompé) ET la position (jamais la couleur seule §3). Ligne ATM = fond or
  + glyphe ◄.
- **Marqueur ATM libellé (skew)** : la ligne verticale or du strike ATM porte désormais sa VALEUR
  (`5000`) en bas → le centre du smile est nommé. Coordonnées alignées au pixel (marqueur `R(x)+0.5`,
  libellés d'axe `R(yOf)`), libellé ATM borné pour ne pas déborder.
- **Contraste call/put (fond sombre)** : mesuré WCAG sur le fond réel — **call(sky) 8.97 · put(pink)
  7.25**, tous ≥ 3:1 (objet graphique 1.4.11).
- **Courbe VTS teintée par état** : contango → VERT, backwardation → ROUGE, plat/indéterminé → gris.
  Renfort du badge (état porté par 4 canaux : badge texte + glyphe ↗/↘ + pente réelle + teinte —
  couleur jamais seule §3). Points/libellés déjà alignés au pixel.
- **Vérif** : `tsc` + `vite build` OK ; essai Playwright `/polish` (contraste ≥ 3:1 mesuré, marqueur
  ATM libellé 134 px or, 24 cellules ITM ombrées, courbe contango verte 893 px / backwardation
  forcée rouge 862 px) + martèlement onglets/grecques → **0 erreur JS** + captures (OMON, VTS).

## D-040 · Moteur Macro & Risk Guard (`macro_calendar` + `macro_risk`, câblé Phase 0)
Calendrier des publications éco TRADABLES + garde de risque déterministe. Décisions :
- **Bloc DISTINCT d'`econ_calendar` (D-027)** — clarifié avec l'humain : EC reste le calendrier
  macro/géo SYSTÉMIQUE (tiers 1/2/3, reset CVD D-029) ; le nouveau `macro_calendar` = publications
  TRADABLES (impact HIGH/MED/LOW, consensus/previous/actual, ÉCART de surprise). Zéro modification
  de D-027 (§1 : deux angles distincts, pas de duplication).
- **Champs** : `macro_calendar` (LENT) value `{events: [{ts, name, country, currency, impact,
  consensus, previous, actual, surprise}]}` ; `macro_risk` (RAPIDE) value `{regime ∈ NORMAL|
  WARNING|EXECUTION_PAUSED, event | null, seconds_until, in_window}`. Le régime + countdown sont
  RAPIDES (en phase avec Phase 0) ; le calendrier est LENT (données changent lentement).
- **Risk Guard déterministe** (`app/macro_risk.py::compute_macro_risk`, pur) : EXECUTION_PAUSED si
  un HIGH est dans le BLACKOUT symétrique `|ts − now| ≤ pause` ; WARNING si un HIGH approche
  (`pause < Δ ≤ warn`) ; NORMAL sinon. MED/LOW n'enclenchent jamais le garde.
- **VERROU UNIQUE (§2.2)** — clarifié avec l'humain : le garde EST câblé à Phase 0 via la règle
  déterministe `MACRO_BLACKOUT` (CRIT) qui appelle **le même** `compute_macro_risk` → Phase 0
  BLOCKED en blackout. `macro_risk` (projection) et la règle Phase 0 partagent l'algorithme : une
  seule logique, jamais deux verrous concurrents. EXECUTION_PAUSED = projection de Phase 0 BLOCKED.
- **Fenêtres** (pause ±15 min, warn 30 min) = **v1 provisional** (config). Calendrier ABSENT →
  aucun HIGH connu → NORMAL (le blackout est un signal POSITIF, pas un défaut fail-closed — noté).
- **Fail-closed (§3)** : ts non-fini / impact invalide / name vide → événement écarté ; nombre
  non-fini → None (jamais une surprise inventée) ; raw non-liste → vide. JSON strict `allow_nan=False`.
- **Mock (§4)** : grille de releases (ISM/CPI/FOMC/ECB/NFP/Retail) autour de `now` — une HIGH dans
  le blackout (exerce le garde + Phase 0) ; `actual` connu seulement après publication ; pathologie
  (release cassé) écartée par le moteur.
- **Frontend** : `MacroCalendarPanel` (MCAL, zone A, `S1 + S2`) — grille haute densité chronologique,
  compte à rebours dérivé client, jauge d'impact HIGH/MED/LOW (couleur + points ●●● + texte, §3),
  consensus/previous/actual + surprise SIGNÉE (▲ vert / ▼ rouge), lignes HIGH en blackout surlignées
  (⏸). Badge de régime `MacroRegimeBadge` dans la **Zone 0** (lit `macro_risk`) : glyphe + event +
  countdown + régime (« ⏸ CPI publiée +6m11s · EXECUTION_PAUSED ») à côté du Phase 0 GÉANT — couleur
  jamais seule (§3). Câblés : registre, SSE (`macro_risk` FAST, `macro_calendar` SLOW), espace DÉFAUT
  (bump `STORAGE_KEY` v10→v11), mnémonique `MCAL`, hook DEV `__setMacro`.
- **Vérif** : 18 tests backend (calendrier : surprise/tri/impact/fail-closed/grâce ; risk guard :
  NORMAL/WARNING/PAUSED avant-après blackout, MED/LOW ignorés, priorité, driver, fail-closed ;
  **câblage Phase 0** : MACRO_BLACKOUT bloque / ne bloque pas) ; **231 passed**, ruff clean ; `tsc`
  + `vite build` OK ; essai Playwright réel : 5 releases live (CPI/FOMC/NFP, jauges, surprise ▲+0.3,
  blackout ⏸), badge Zone 0 **EXECUTION_PAUSED** + countdown, **Phase 0 BLOQUÉ** par le blackout,
  **0 erreur JS** + captures.
- **Hors-scope (une feature = un commit)** : historique des surprises ; scoring d'impact pondéré ;
  filtre par devise ; révisions (actual révisé) ; auto-ack de sortie de blackout ; feed réel.

### /devil D-040 — conditions limites
Attaques : annonces simultanées/chevauchantes (HIGH + LOW même seconde) · releases corrompues
(champs absents, types invalides, strings au lieu de floats) · désync d'horloge · absence totale ·
bornes exactes du blackout (t−15m, t, t+15m).
- **Bornes du blackout — INCLUSIVES à ±pause, aucun trou/chevauchement** : `|Δ| ≤ pause` →
  PAUSED (t−15m, t, t+15m pile) ; `pause < Δ ≤ warn` → WARNING ; au-delà / `Δ < −pause` → NORMAL.
  Δ=pause n'est jamais compté deux fois (blackout `≤` a priorité, warning exige `>`). Tests dédiés.
- **Simultané HIGH + LOW même ts** : seuls les HIGH pilotent le garde (LOW/MED ignorés) ; deux HIGH
  au même ts → régime déterministe et stable (`min` par |Δ|). Tests dédiés. Pas de dédup calendrier
  (CPI + PPI à 8h30 sont deux vraies publications ; clé React = index, pas de collision).
- **1 bug RÉEL frontend trouvé & corrigé** : une entrée `events` null/non-objet (release corrompue)
  faisait planter `e.impact` avant le fallback `IMPACT[…] ?? LOW`. Corrigé : filtre
  `e && typeof e === 'object'` → entrées corrompues écartées, jamais un crash.
- **Amélioration backend (« strings au lieu de floats »)** : `_num` parse désormais les strings
  numériques PROPRES (« 3.4 » → 3.4) mais rejette unités/garbage/bool/inf/nan → None (recouvre les
  feeds à strings sans deviner d'unité ni fabriquer §3). `ts` reste STRICT (string ts → événement
  écarté, inutilisable sans parsing de date). Tests dédiés (propre parsé, « 3.4% »/« N/A » → None).
- **Absence totale / désync** : calendrier None/non-liste → NORMAL, aucun crash (le blackout est un
  signal POSITIF) ; la règle Phase 0 et la projection dégradent identiquement. Countdown client
  dérivé de `serverNow` (offset horloge corrigé) ; un ts figé/périmé n'invente jamais de countdown.
- **Chemins déjà sûrs confirmés** (essai Playwright SSE gelé, **0 erreur JS**) : régime inconnu →
  style NORMAL ; `event` null → nom masqué ; `value`/`event`/`events` non-objet → PAS DE DONNÉES ;
  `seconds_until`/`ts` NaN → « · »/« — » (jamais un `.toFixed` cru) ; surprise 1e9 → formatée.
- **Vérif** : +9 tests backend (bornes exactes ×2, simultané HIGH+LOW, deux HIGH stables, strings
  parsées/garbage, bool→None, ts string écarté, absence) ; **242 passed**, ruff clean ; `tsc` +
  `vite build` OK ; essai Playwright 6 pathologies → **0 erreur JS**, UI réactive.

### /polish D-040 — densité MCAL, badge Zone 0, lisibilité des surprises
Loop 5 sur le rendu (aucune logique métier touchée). 3 axes :
- **Densité & alignement (MCAL)** : numériques ALIGNÉS À DROITE (`text-right` explicite), jauge
  d'impact CENTRÉE, `actual`/`surprise` en gras (le résultat prime). **Hiérarchie passé/à venir**
  nette : séparateur « ▸ MAINTENANT » (or) inséré au basculement chrono, passé estompé (opacity-40),
  **prochaine échéance** surlignée (fond `term-grid`). Nom tronqué proprement (`truncate` + title).
- **Visibilité badge Zone 0** : critique = attention immédiate, calme = discret. EXECUTION_PAUSED →
  fond `risk-red/20` + bordure + **icône pulsée** (`animate-pulse`) ; WARNING → fond `risk-yellow/15`
  + bordure ; NORMAL → **sans fond ni bordure** (vert estompé, label masqué) → ne surcharge pas.
  Régime encodé couleur + glyphe (⏸/△/📅) + texte (§3).
- **Lisibilité des surprises (WCAG)** : ▲ dépasse consensus (vert) / ▼ sous consensus (rouge),
  **gras + fond teinté** (0.10) → colonne de « beats/misses » lue en une fraction de seconde ;
  contraste MESURÉ sur fond réel **▲ 9.99 · ▼ 6.94** (≥ 4.5:1, texte WCAG 1.4.3) ; glyphe + signe +
  couleur + infobulle (« dépasse le consensus ») — jamais la couleur seule (§3).
- **Vérif** : `tsc` + `vite build` OK ; essai Playwright `/polish` (contraste ≥ 4.5:1 mesuré,
  séparateur MAINTENANT, badge PAUSED fort `bg 0.2`+bordure / WARNING `0.15` / NORMAL transparent)
  → **0 erreur JS** + captures (MCAL, badges PAUSED/WARNING/NORMAL).

## D-041 · Volume Profile dynamique (`s1_state.volume_profile` + Canvas)
Profil volumétrique auto-calculé (POC / Value Area 70 % / VAH·VAL / LVN / veille). Décisions :
- **Champ `s1_state.volume_profile`** — DISTINCT de `structure.vpoc/vah/val/lvn` (scalaires fournis
  par la SOURCE) : ici la DISTRIBUTION complète est auto-calculée par le terminal depuis le tape.
  value : `{tick, va_pct, total_volume, poc, vah, val, levels: [{price, volume}], lvn: [prix],
  previous: {poc, vah, val} | null}`. Canal RAPIDE (`s1_state`). Lecture seule (§2.1).
- **Algorithme** (`app/volume_profile.py::build_volume_profile`, pur/déterministe) : agrège le
  volume par niveau (grille de tick), **POC** = volume max (égalité → prix bas) ; **Value Area
  70 %** : depuis le POC, étend vers le voisin au plus gros volume jusqu'à `va_pct · total`
  (convention Market Profile) → **VAH/VAL** = bornes ; **LVN** = minima locaux stricts `≤ ratio ·
  vol POC` (lacune à 0 = LVN fort). Grille CONTIGUË bornée à `VP_MAX_LEVELS` autour du POC (prix
  aberrant lointain ne l'explose pas). VA 70 % = AUTORITÉ de facto ; ratio LVN = v1 provisional.
- **Accumulation session** : le moteur accumule le volume par niveau dans un dict (borné par le
  nombre de NIVEAUX, pas de prints — comme le CVD par niveau D-029), seq-dédup. Au changement de
  journée : snapshot POC/VAH/VAL → `previous` puis reset (projection de la veille). `previous`
  retombe sur les niveaux fournis par la source (`session_prev`) tant qu'aucun snapshot propre
  (cold start honnête). Fail-closed (§3) : tape non FRESH → pas d'accumulation, fraîcheur propagée.
- **Frontend Canvas** (`VolumeProfilePanel`, code `VP`) : histogramme HORIZONTAL — axe Y = prix,
  axe X = volume (barres → droite) ; **surbrillance stricte** : bande Value Area (sky), barre +
  ligne POC (OR), niveaux VEILLE (prev POC/VAH/VAL, tiretés violets + libellés yPOC/yVAH/yVAL),
  LVN (◄ ambre) — chaque repère = couleur + glyphe/position + libellé (jamais la couleur seule §3).
  Un seul `<canvas>` DPR-scalé. STALE→FIGÉ, vide→PAS DE DONNÉES. Câblés : registre `VP`, espace
  MICRO (bump `STORAGE_KEY` v11→v12), mnémonique `VP`, hook DEV `__setVolProfile`.
- **Vérif** : 13 tests backend (POC + égalité, VA 70 % symétrique/asymétrique, LVN minima/lacune,
  grille contiguë, quantification tick, niveau unique, total, fail-closed non-fini, vide, prix
  aberrant borné) ; **255 passed**, ruff clean ; `tsc` + `vite build` OK ; essai Playwright réel :
  profil live (38 niveaux, POC 5449.75, VA 5446.75–5450.25, 10 LVN, veille projetée), Canvas
  histogramme + VA sky + POC or + veille violet + LVN ambre, **0 erreur JS** + capture.
- **Hors-scope (une feature = un commit)** : profils composites multi-sessions ; TPO/Market Profile
  par lettres ; naked POC (POC non-testés) ; split VA au-dessus/en-dessous ; delta par niveau.

### /devil D-041 — conditions limites
Attaques : distribution plate/uniforme (aucun POC net) · pic unique · prix aberrants · volumes
négatifs/nuls · reset de session + accumulation massive · Canvas 0×0/étiré + niveaux non-finis ·
afflux massif de ticks.
- **Backend robuste (aucun bug — +7 tests)** : distribution PLATE → POC = prix bas déterministe,
  aucun LVN strict, VA cohérente ; pic unique → POC seul ≥ 70 % → VA = {POC} ; volume ≤ 0 / bool
  ignoré ; tick ≤ 0 ou entrée non-dict → profil vide (fail-closed §3) ; **massif 5000 niveaux** →
  borné à `VP_MAX_LEVELS`, valeurs finies. L'accumulation moteur est bornée par le NOMBRE DE
  NIVEAUX (dict, pas de prints) → un afflux massif de ticks ne fait grossir que ~centaines de
  niveaux (crash-test structurellement impossible). Reset de session : snapshot POC/VAH/VAL →
  `previous` puis clear au changement de jour (dict + seq re-baseline).
- **1 bug RÉEL frontend trouvé & corrigé** : un profil à NIVEAU UNIQUE (`pmax == pmin`, début de
  session) faisait retourner `draw` (division `/(pmax−pmin)` évitée) → **canvas VIDE sans message**
  (`levels.length > 0` → pas de « PAS DE DONNÉES »). Corrigé : cas `flat` → barre CENTRÉE, jamais
  un canvas muet.
- **Chemins déjà sûrs confirmés** (essai Playwright SSE gelé, **0 erreur JS**) : niveaux
  NaN/Inf/null/non-objet filtrés (`Number.isFinite` + typeof) ; POC/VAH/VAL/veille non-finis gardés
  (`Number.isFinite` avant tout tracé) ; LVN hors-plage/NaN ignoré ; `levels` non-tableau/vide →
  PAS DE DONNÉES ; prix aberrant 1e9 → hauteur bornée ; resize 0×0 (`W<4||H<4`) et étiré → OK.
- **Vérif** : +7 tests backend (plate, pic unique, vol ≤ 0, tick ≤ 0, non-dict, massif 5000, bool) ;
  **255 passed**, ruff clean ; `tsc` + `vite build` OK ; essai Playwright 8 pathologies (niveau
  unique, non-finis, scalaires non-finis, plate, massif+aberrant, non-tableau/vide, resize extrême)
  → **0 erreur JS**, UI réactive.

### /polish D-041 — Retina/DPR, hiérarchie POC/VA, tooltip acheteur/vendeur
Trois axes demandés : (1) rendu Retina/High-DPI net, (2) contraste & ergonomie Value Area + POC +
veille, (3) tooltip de survol (prix, volume, part % session, split acheteur/vendeur).
- **DPR exact (crispness)** : buffer canvas = `round(cssW × devicePixelRatio)` + `setTransform(dpr…)` ;
  remplissages sur bornes ENTIÈRES (`Math.round`), traits 1px sur demi-pixels (`R(y)+0.5`). Essai :
  `c.width === round(cssW × dpr)` **vrai** en live, étiré 2400×1400, et minuscule (largeur exacte ;
  hauteur repliée proprement par la garde `H<4`, aucun crash).
- **Hiérarchie visuelle** (jamais la couleur seule §3 — position + libellé aussi) : POC (barre + trait
  OR épais, 1er plan) > Value Area (barres SKY + bande + **bornes VAH/VAL tracées**) > hors-VA (slate
  atténué) ; veille = traits VIOLET tiretés libellés `yPOC/yVAH/yVAL` ; LVN = `◄` AMBRE.
- **Tooltip de survol** (interactif, réticule horizontal + surbrillance de la barre, bornes entières) :
  `prix`, `volume` (compact k/M), **`part` = % du volume total de session**, et — si la source le
  fournit — `ach`/`vend` (split acheteur/vendeur). Tag POC / VALUE AREA / LVN en tête. Boîte COMPACTE
  (9px, interligne 11) → tient dans un panneau court, `ach`/`vend` jamais rognés (couverture 8/8 au
  balayage vertical). Bascule côté / clamp vertical pour ne jamais déborder du canvas.
- **Split acheteur/vendeur — donnée RÉELLE, jamais inventée (§3)** : le tape porte `side` (BUY|SELL) ;
  extension ADDITIVE & rétrocompatible de `build_volume_profile(…, buy_by_price=None)` (défaut absent
  → aucun `buy`/`sell`, 0 test cassé), engine accumule `_vp_buy` par niveau, vendeur = total − acheteur
  (borné ≥ 0, fail-safe). Sans donnée source, le tooltip **omet** ach/vend (essai : teal ABSENT confirmé)
  plutôt que d'afficher un faux split. +4 tests (split, absence par défaut, clamp, non-fini ignoré).
- **Vérif** : **266 passed** (Redis up), ruff clean ; check d'intégration réel engine→builder
  (buy+sell = volume, source-backed, freshness propagée) ; `tsc` + `vite build` OK ; essai Playwright
  (SSE gelé) — DPR exact, POC/VA rendus, tooltip 8/8 positions, split omis sans source, resize extrême
  borné, **0 erreur JS** ; capture à l'appui.

## D-043 · Moteur de Robustesse & Walk-Forward (analyse OFFLINE, `WalkForwardEngine`)
Nouveau module de validation quantitative de la stabilité des stratégies sur l'historique
réconcilié. **Deux forks d'architecture tranchés avec l'opérateur (AskUserQuestion) :**
1. **Surface analytics OFFLINE, pas un bloc de schéma.** Walk-Forward / Heatmap / Monte Carlo sont
   de la RECHERCHE sur l'historique réconcilié, pas un état temps-réel. Les forcer en blocs
   ContextSchema trahirait `CLAUDE §1` (« un panneau = un bloc ») et `§6` (cadences). **Exception §1
   assumée** : ils vivent comme PROJECTIONS/vues sur l'event store (précédent RECAP/PNL/Sharpe),
   servies par endpoint GET, jamais poussées en SSE live.
2. **Réel d'abord, heatmap différée (§3/§8).** WFE + Monte Carlo se branchent sur une donnée RÉELLE
   (`projections._reconciled_r_multiples`). La **heatmap de stabilité paramétrique** (Seuil Imbalance
   × Spread) suppose un backtest balayé par paramètres qui **n'existe pas** (terminal live, pas
   backtester) → **différée** jusqu'à une source réelle (export optimiseur NT8 ou vrai harnais de
   backtest). Remplir la heatmap avec une grille inventée violerait « no signal without data » (§3)
   et « ne pas afficher un faux nombre autoritaire » (§8). Aucun mock autoritaire.

### Tranche 1 (`/feature`) — moteur de calcul Walk-Forward
`backend/app/walk_forward.py` : classe **`WalkForwardEngine`** pure et déterministe (aucun LLM,
aucune source live) sur une série de rendements ordonnée dans le temps.
- **Fenêtres glissantes** IS/OOS : `window` trades/fenêtre (0 → toute la série), `step` (0 → non
  chevauchant), part In-Sample `is_frac` (défaut 0.70) bornée pour garantir n_oos ≥ 1.
- **WFE** = (profit OOS / n_oos) ÷ (profit IS / n_is) — **normalisé par trade** (le déséquilibre
  70/30 ne biaise pas le ratio). Verdict **`OVERFIT_DETECTED`** si WFE agrégé (médiane des fenêtres
  valides) < seuil (0.50, spec D-043), sinon `ROBUST`.
- **FAIL-CLOSED (§3/§8)** : rendement non-fini / bool ignoré ; **IS non profitable → WFE `None`**
  (`IS_UNPROFITABLE`, jamais un ratio fabriqué) ; données insuffisantes → **`INSUFFICIENT_DATA`**
  (jamais un faux nombre autoritaire). Résultats typés Pydantic (`WalkForwardResult`/`Window`).
- **Branchement source réelle** : `projections.walk_forward(store)` exécute le moteur sur les
  R-multiples RÉCONCILIÉS (`_reconciled_r_multiples`, ordre chronologique append-only), paramètres
  depuis `config.WF_*` (70/30 = AUTORITÉ de facto Pardo ; window/step/min = `v1 provisional`).
- **Vérif** : 13 tests (WFE normalisé, seuil strict, rolling+step, IS non profitable→None, insuffisant,
  non-fini/bool ignorés, fenêtre unique, déterminisme, vide, + 2 projection sur store stub réconcilié) ;
  **261 passed**, ruff clean.
### Tranche 2 (`/feature`) — simulateur Monte Carlo du Max Drawdown
`backend/app/monte_carlo.py` : **`MonteCarloSimulator`** pur, typé Pydantic, sur la série
réconciliée.
- **Bootstrap AVEC REMISE** : chaque simulation tire `len(série)` trades avec remise (5 000–10 000
  simulations, `MC_N_SIMS`). Fonction pure `max_drawdown(returns)` = MaxDD (magnitude ≥ 0) de la
  courbe d'équité, **pic incluant le 0 initial** (une perte d'ouverture compte → pas de biais).
- **Distribution** : P50/P95/P99 du MaxDD (percentile par interpolation linéaire) + `mean_max_dd` +
  **`prob_exceed` = P(MaxDD ≥ seuil)** où le seuil = `risk.max_drawdown_r_day` (réglage, source
  unique — pas de doublon). Python pur (numpy absent), hors hot path (§7).
- **Répétable** : `seed` optionnel (`MC_SEED`, défaut None = entropie). Cas dégénérés déterministes
  (tout-gagnant → MaxDD ≡ 0 ; tout-perdant → MaxDD ≡ N) → tests EXACTS sans flakiness.
- **FAIL-CLOSED (§3/§8)** : non-fini/bool ignoré ; série < plancher → `INSUFFICIENT_DATA`
  (percentiles/proba `None`) ; seuil ≤ 0/non-fini → `prob_exceed` None (jamais fabriqué).
- **Branchement source réelle** : `projections.monte_carlo(store)` sur `_reconciled_r_multiples`,
  seuil lu dans `settings`, params `config.MC_*`.
- **Vérif** : 11 tests (MaxDD pur, tout-gagnant/perdant exacts, percentiles ordonnés, répétabilité
  seed, convergence vers ~(0.5)¹⁰, insuffisant, non-fini/bool, seuil invalide, + 2 projection stub) ;
  **272 passed**, ruff clean.
- **À venir** (chacune `/feature`→`/devil`→`/polish`→`/done`) : endpoint GET + vue frontend
  « ROBUSTESSE » (Canvas) exposant WFE + Monte Carlo ; heatmap paramétrique **quand** une source de
  backtest réelle existera. Note : l'import NT8 existant est **CSV** (`trade_reconciliator`), le
  cahier D-043 cite du JSON → parseur découplé à prévoir.

### /devil D-043 — pathologies backend (Monte Carlo & Walk-Forward)
Attaques : séries 0/1 trade, Inf/NaN/types mixtes, **charge 10 000×10 000**, seuils DD aberrants
(négatif/nul/absent/Inf), distributions à queue lourde (cygnes noirs).
- **2 bugs RÉELS trouvés & corrigés :**
  1. **Hang CPU (mesuré)** : 10 000 trades × 10 000 sims = 1e8 itérations Python pur → **> 125 s**
     (worker d'endpoint synchrone « pendu »). Corrigé : **borne `MC_MAX_WORK` (2e6)** → réduit
     `n_sims` pour tenir le budget, `capped=True` reporté (jamais silencieux). **125 s → 0,60 s**,
     `n_sims=200`. Le cas réel (≤ 200 trades réconciliés) garde les 10 000 sims.
  2. **Overflow silencieux → faux 0** : `max_drawdown([1e308,1e308,-1e308])` renvoyait **0.0** car
     `inf−inf=nan` et `nan>mdd` est False (valeur inventée, §3 violé). Corrigé : `max_drawdown`
     renvoie `inf` sur overflow ; le simulateur **exclut** toute sim non-finie (tout exclu →
     `INSUFFICIENT_DATA`, jamais un p95 fabriqué) ; WF renvoie `wfe=None` (`UNDEFINED`) si `inf/inf`.
- **Mémoire : aucune fuite** (pic 0,05 MB — `dds` = `n_sims` floats, bornée par les sims pas le
  produit).
- **Chemins déjà sûrs confirmés** : 0/1 trade → INSUFFICIENT_DATA ; Inf/NaN/str/None/bool/list →
  filtrés (`_finite`) ; seuil négatif/nul/None/Inf → `prob_exceed=None` (jamais fabriqué), mais la
  distribution reste calculée ; fat-tails → P50 ≤ P95 ≤ P99 monotones, la queue extrême (cygne noir
  −100 R) est **captée par P99** ; réglage `risk.max_drawdown_r_day` corrompu/absent → seuil None
  (pas de crash de l'endpoint).
- **Vérif** : +9 tests /devil (0/1 trade, types mixtes, seuils aberrants, borne CPU, overflow, fat-tail
  MC ; overflow/types/vide WF) ; **281 passed**, ruff clean.

## D-015 · Un opérateur par instance (AUTORITÉ `CLAUDE §9`)
`VITE_OPERATOR` (ou `?operator=YOUSSEF`) fixe l'instance ; défaut `SONY`. Tous les events
portent `operator`.
