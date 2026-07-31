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

### /polish D-043 — nettoyage & choix de conception scellés
Nettoyage sans changement de comportement (281 passed avant/après, ruff clean) : docstrings et
nommage vérifiés ; tags process « /devil » des commentaires → **rationale durable** (le POURQUOI
reste, la référence au loop part) ; **double calcul du WFE éliminé** dans `WalkForwardEngine.run`
(`wfe` calculé une seule fois, branche sur `math.isfinite`) ; **typage complété de bout en bout**
(`returns: Iterable[Any] | None`, `_finite(x: object)`, `params: dict[str, Any]`, `max_drawdown:
Iterable[float]`). Trois choix de conception **scellés** :
1. **Borne CPU `MC_MAX_WORK` (2e6).** Le bootstrap est en O(`n_sims × n_trades`) Python pur (numpy
   absent) : 10 000×10 000 = 1e8 → hang. Plutôt qu'un timeout opaque, on **réduit `n_sims`** pour
   tenir le budget et on **reporte** `capped=True` + le `n_sims` réellement exécuté (jamais une
   troncature silencieuse §8). Le cas réel (≤ 200 trades réconciliés) garde ses 10 000 sims.
2. **Overflow IEEE 754 explicite.** Une somme d'équité qui déborde donne `±inf`, et `inf−inf = nan`
   avec `nan > x` toujours `False` → un drawdown se **masquerait en faux 0**. On détecte le
   non-fini (`max_drawdown` renvoie `inf` ; le simulateur exclut la sim ; WF renvoie `wfe=None`
   `UNDEFINED`) plutôt que d'émettre un `0`/`nan` trompeur.
3. **Fail-closed strict (§3/§8) — un seul principe partout.** Au moindre doute — série < plancher,
   rendement non-fini/bool, seuil ≤ 0/absent, IS non profitable, overflow, tout exclu — la sortie
   est `INSUFFICIENT_DATA` / `None` / `IS_UNPROFITABLE` / `UNDEFINED`, **jamais un nombre fabriqué**.
   Le contrat de type l'impose : chaque champ numérique est `float | None`.

### Tranche 3 (`/feature`) — endpoint `GET /analyses/robustness` + vue « ROBUSTESSE »
Exposition des deux moteurs sur les trades réconciliés, en surface **analytics OFFLINE** (fetch
endpoint, pas un bloc SSE — §1, comme PNL/RECAP).
- **Backend** : `projections.robustness(store)` consolide `walk_forward` + `monte_carlo` en un payload
  typé ; `GET /analyses/robustness` l'offloade (`asyncio.to_thread`, calcul CPU-borné hors de la
  boucle d'événements). **Fail-closed** : trades insuffisants → verdicts `INSUFFICIENT_DATA` en
  **HTTP 200**, jamais une 500 (§3).
- **Frontend** : vue `RobustnessView` (types miroirs locaux, `api.analysesRobustness`, poll 15 s +
  anti-race). GAUCHE = verdict Walk-Forward (badge **ROBUSTE** ✓ vert / **SURAJUSTEMENT** ⚠ rouge /
  IS non profitable ∅ / DONNÉES INSUFFISANTES), WFE, strip par fenêtre. DROITE = distribution Monte
  Carlo : échelle P50/P95/P99 avec **trait OR du seuil** challenge + zone de danger, et la
  **probabilité d'invalidation** (bande faible ✓ / modérée ⚠ / élevée ▲). Code couleur §3 STRICT :
  glyphe + texte + position, jamais la couleur seule ; OR = seuil de référence. Câblée `ViewKey`
  `ROBUST` + App.tsx + CommandBar (mnémonique `ROBUST`, alias ROBUSTESSE/WFE/MC…).
- **Vérif** : 3 tests d'intégration (consolidation stub, fail-closed vide, endpoint 200 + contrat) →
  **284 passed**, ruff clean ; `tsc` + `vite build` OK ; essai Playwright (endpoint réel → fail-closed
  « DONNÉES INSUFFISANTES » ; payloads interceptés → ROBUSTE et SURAJUSTEMENT rendus, P50/P95/P99 vs
  seuil, proba, **0 erreur JS**) ; captures à l'appui.
- **À venir** : heatmap paramétrique **quand** une source de backtest réelle existera (export
  optimiseur NT8 ou harnais de backtest) — jamais une grille inventée (§3/§8).

### /devil D-043 tranche 3 — pathologies de rendu de la vue ROBUSTESSE
Attaques : percentiles extrêmes/identiques (P50 = P95 = P99), 200 fenêtres Walk-Forward, rafale de
rafraîchissements, WFE négatif/non-fini.
- **4 défauts RÉELS trouvés & corrigés :**
  1. **Étiquettes P50/P95/P99 superposées** — sur distribution dégénérée (perte totale en un jour →
     P50 = P99, ou stratégie sans drawdown → tous à 0) les 3 étiquettes se rendaient au même point :
     **3 chevauchements sur 3 paires** (mesuré). Corrigé : le **trait reste à la position VRAIE**
     (honnêteté §3), seule l'**étiquette** glisse (écart minimal 8 %, recalage dans le cadre) →
     **0 chevauchement**, valeurs exactes toujours lisibles dans les tuiles.
  2. **« 0k sims » sur un run borné** — `fmtNum(n_sims/1000, 0)` arrondissait 200 sims à `0k`,
     effaçant l'information au moment précis où elle compte (budget CPU atteint). Corrigé : compte
     **exact** sous 1000 (« 200 sims (borné) ») + infobulle expliquant la réduction.
  3. **Bande de fenêtres non bornée** — 200 fenêtres = mur de 11 rangées (pas de débordement de div,
     mais croissance illimitée et illisible). Corrigé : **48 dernières** affichées + « N plus
     anciennes masquées » (jamais une troncature silencieuse §8).
  4. **Ordre des fenêtres annoncé À L'ENVERS** — l'UI disait « récent → ancien » alors que le moteur
     produit `start` CROISSANT, donc `windows[0]` couvre les trades les **plus anciens** (vérifié sur
     série témoin). L'opérateur lisait sa dégradation temporelle inversée. Corrigé : « ancien →
     récent ».
- **Backpressure corrigée** : chaque rafraîchissement déclenche un calcul Monte Carlo complet côté
  serveur ; 30 clics simultanés émettaient **30 requêtes**. Garde « en vol » (bouton désactivé +
  requête ignorée si une est en cours) → **1 requête** pour 30 clics (mesuré).
- **Chemins déjà sûrs confirmés** : WFE **négatif** (cas RÉEL — le moteur en produit) affiché
  correctement ; percentiles/WFE **infinis** (JSON `1e400`) → ni `NaN` ni `Infinity` dans le DOM,
  **aucun style CSS invalide** (les gardes `Number.isFinite` + `|| 1` sur l'échelle tiennent) ;
  aucun débordement horizontal (panneau ni body).
- **Vérif** : essai Playwright 5 pathologies → **0 chevauchement, 48 cases bornées, 1 requête sur 30
  clics, 0 erreur JS** ; `tsc` + `vite build` OK ; **284 passed**, ruff clean (backend inchangé).

### /polish D-043 tranche 3 — robustesse du contrat de réponse + honnêteté du périmé
Nettoyage (aucun log de debug ni code mort ; tags process « /devil » des commentaires → rationale
durable) ET **3 défauts trouvés en cours de revue, corrigés** — ils dépassaient le cosmétique :
1. **Écran blanc TOTAL sur réponse partielle (critique).** Un payload sans `walk_forward` (ou sans
   `monte_carlo`, ou un JSON mutilé) provoquait `Cannot read properties of undefined (reading
   'verdict')` : `root.innerText.length = 0` — **tout le terminal mourait**, Zone 0 et Phase 0
   comprises, à cause d'une simple hoquet backend sur une vue d'analyse secondaire. Corrigé : la
   **forme est validée avant tout rendu** (`normalize()`), bloc absent/non-objet → objet fail-closed
   `INSUFFICIENT_DATA` (§3). Mesure : **11 erreurs JS → 0**, panneau vivant dans les 5 cas.
2. **Chiffres périmés présentés comme courants.** Après un premier succès, un échec ultérieur (HTTP
   500) laissait les anciens percentiles à l'écran **sans le dire** — un drawdown périmé se lisait
   comme courant (§3). Corrigé : bandeau **PÉRIMÉ** (glyphe ⚠ + texte + heure du dernier succès +
   action « relancer avec maj ») et panneau atténué ; les données restent visibles mais **marquées**.
3. **« IS NaN% »** quand `is_frac` manque : repli sur la convention 70/30 (jamais un NaN affiché).
- **Vérif** : régression complète de l'essai `/devil` (0 chevauchement, 48 cases bornées, 1 requête
  sur 30 clics, WFE négatif/infini propres) + probe contrat (bloc manquant ×2, champs manquants,
  500-après-succès, JSON invalide) → **0 erreur JS** ; `npm run typecheck` + `vite build` OK ;
  **284 passed**, ruff clean ; capture du bandeau PÉRIMÉ à l'appui.

### /done D-043 — lacune comblée à la clôture : 500 non maîtrisée sur l'endpoint
La checklist de clôture a testé un chemin jamais couvert : **la projection qui LÈVE** (store
illisible, base verrouillée). L'endpoint renvoyait une **500 non maîtrisée** alors que le cahier de
la tranche 3 exigeait un fail-closed sans 500. Corrigé — et les deux causes restent **distinctes**,
jamais confondues (§3) :
- **trades insuffisants** → `INSUFFICIENT_DATA` en **200** (condition de donnée) ;
- **calcul impossible** → **503 maîtrisée** avec motif (`type` de l'exception seulement, message
  interne non exposé). Choix assumé : on ne le maquille PAS en `INSUFFICIENT_DATA` — cela dirait
  « pas assez de trades » alors que la cause est une panne ; l'UI affiche « PÉRIMÉ », honnête sur la
  vraie cause. Écart documenté vs l'exemple littéral du cahier (« renvoyer INSUFFICIENT_DATA »).
- **+1 test** (503, motif présent, message interne non exposé) → **285 passed**, ruff clean.
- **Angles restants vérifiés à la clôture** : démontage pendant un fetch → **0 erreur JS** ; resize
  320→2400 px → panneau **sans débordement**. À 320 px le body déborde de 509 px, **identiquement
  sur TERMINAL/PNL/RECAP/ROBUST** → propriété **pré-existante** de la coquille (largeurs minimales
  Zone 0 / barre de commande), hors périmètre D-043 ; le terminal dense ne cible pas 320 px.

## D-042 · Liquidity Heatmap L2 & Footprint — Delta, bougies tick-based, fusion carnet
**Collision de spec constatée et tranchée avec l'opérateur (AskUserQuestion).** Le cahier D-042
tranche 1 demandait un nouveau `footprint_engine.py` agrégeant tape BUY/SELL par niveau et par
bougie avec imbalances à seuil paramétrable — or **c'est déjà livré** : `footprint.py` (D-037,
imbalances diagonales, ratio `FOOTPRINT_IMBALANCE_RATIO=3.0`, POC, OHLC, fail-closed) et
`heatmap.py` (D-036, colonne L2 courante, colonne `None` si carnet non FRESH). Un second moteur
aurait dupliqué l'agrégation : deux jeux de seuils à maintenir, divergence garantie.
**Décision : ÉTENDRE `footprint.py`** (une seule source de vérité) avec le réellement neuf.

### Ce qui manquait vraiment (vérifié avant de coder)
1. **Delta** : la bougie n'avait **aucun champ `delta`**, ni par niveau ni globale.
2. **Bougies TICK-BASED** : seul le bucket temporel existait.
3. **Fusion carnet L2** : `footprint.py` **ignorait totalement** le carnet (tape uniquement).

### Implémentation (additive, rétrocompatible — 0 régression sur les 19 tests D-037)
- `delta` par NIVEAU (`ask_vol − bid_vol`, agresseur net) et par BOUGIE (somme) ; `n_prints`.
- `ticks_per_candle > 0` → N prints par bougie ; prints **ordonnés chronologiquement d'abord**
  (déterminisme : le tampon arrive dans l'ordre d'accumulation, pas forcément trié), `start_ts`/
  `end_ts` = ts du premier/dernier print. `0` = bucket temporel (défaut, D-037 inchangé).
- **Fusion L2 — choix de conception honnête (§3)** : le carnet est un instantané **COURANT**.
  L'attacher aux bougies **passées** fabriquerait une association historique fausse (le carnet
  d'il y a 10 min n'est pas celui d'alors). Il n'enrichit donc **QUE la bougie en formation**, en
  `bid_liq`/`ask_liq` par niveau ; chaque bougie porte `book_state ∈ LIVE|ABSENT`.
- **Fail-closed (§3)** en cascade : carnet absent / non-dict / listes corrompues / **toutes entrées
  invalides** → `ABSENT` sans aucun champ de liquidité ; entrée non-finie → ignorée par niveau ;
  et côté moteur, le carnet n'est transmis **que s'il est FRESH** (gelé/absent → aucun mur exposé).
- **Câblage** : `engine._build_footprint(tape, order_book, now)` passe le carnet et
  `config.FOOTPRINT_TICKS_PER_CANDLE` (défaut 0, PLACEHOLDER v1 provisional).

### Vérif
- **+11 tests** (delta niveau/bougie + intégrité, signe du delta, bougies tick-based avec ordre
  chronologique et déterminisme, OHLC tick-based, carnet limité à la bougie en formation,
  appariement par prix, absent explicite, carnet invalide/gelé, tailles non-finies, rétrocompat) →
  **297 passed**, ruff clean.
- **Essai manuel réel** (moteur live, Redis relancé) : `book_state=LIVE`, delta `+78` sur 79 prints,
  niveaux montrant **exécuté** (`bid_vol/ask_vol/delta`) **et liquidité au repos** (`bid_liq/ask_liq`
  — ex. vente exécutée face à 99 contrats à l'ask), **intégrité `delta_bougie == Σ delta_niveaux`
  vraie**, 15/24 niveaux en imbalance, **bougies passées toutes `ABSENT`** (aucune rétro-attribution).
- **Gate moteur prouvé** : carnet FRESH → `LIVE` avec `bid_liq` ; **STALE et ABSENT → `ABSENT`**,
  aucun champ de liquidité (§3).
- **À venir** : miroir TS + rendu frontend (delta par bougie, murs L2 sur le Canvas footprint).

### /devil D-042 — ticks désordonnés, carnets corrompus, intégrité du delta
Attaques : séries tick-based désordonnées/incomplètes, `ticks_per_candle` extrême, carnets
corrompus/aberrants, intégrité du delta sur gros volumes et prints simultanés.
- **3 défauts RÉELS trouvés & corrigés :**
  1. **Carnet 100 % aberrant déclaré « vivant ».** Un carnet ne contenant que des prix ≤ 0 passait
     `book_state = LIVE` et affirmait alors **0 liquidité** sur des niveaux réels — une **affirmation
     fausse, pire qu'une absence** (§3). `_book_maps` exige désormais `price > 0`, comme la
     validation DOM du moteur ; un carnet entièrement aberrant retombe sur `ABSENT`. Un carnet
     PARTIELLEMENT corrompu garde ses entrées saines (testé).
  2. **Crash du hot path sur print non-dict** (`None`/`str`/nombre dans la liste) : `p.get` levait
     `AttributeError` et aurait tué la boucle rapide. **Défaut PRÉ-EXISTANT à D-037** (vérifié sur
     `7b05fec~1`) que le refactor avait conservé — corrigé : entrée non-dict écartée seule.
  3. **Débordement publié en `inf`.** Des volumes absurdes faisaient déborder la somme →
     `delta`/`total_volume` = `inf`, affiché comme une mesure réelle. La bougie corrompue est
     désormais **retirée** (pas de donnée plutôt qu'une fausse, §3) ; les bougies saines de la même
     série sont conservées.
- **Chemins déjà sûrs confirmés** : tri chronologique **stable et déterministe** en mode tick
  (série désordonnée + prints incomplets → 4 valides sur 6, découpage identique à chaque appel) ;
  `ticks_per_candle = 10⁹` → une seule bougie (aucune boucle folle) ; `≤ 0` → repli propre sur le
  bucket temporel ; liste vide → aucune bougie. **Intégrité du delta EXACTE** (`delta_bougie ==
  Σ delta_niveaux`, bit à bit — même ordre d'accumulation) vérifiée sur **120 prints simultanés à
  gros volumes** (1e6) sur 60 niveaux, et en mode tick.
- **Vérif** : +8 tests /devil → **38 tests footprint**, **323 passed** (Redis relancé : les 18 tests
  jusque-là skippés s'exécutent), ruff clean ; hot path moteur re-vérifié (carnet mêlant prix
  aberrant et valide → aberrant ignoré, `bid_liq` correct, intégrité conservée).

### /polish D-042 — notes de conception durables + typage strict
Nettoyage sans changement de comportement (38 tests footprint / 323 verts avant comme après) :
- **Docstring de module réécrit** : il ne décrivait plus que D-037 (bucket temporel, imbalances)
  alors que le module porte désormais le delta, les bougies tick-based et la fusion L2. Les trois
  arbitrages sont désormais des **notes de conception** en tête de module — pourquoi le tri
  chronologique est obligatoire en mode tick (le tampon amont n'est pas trié), pourquoi l'identité
  `delta_bougie == Σ delta_niveaux` est exacte **bit à bit** (même ordre d'accumulation), et pourquoi
  le carnet n'enrichit que la bougie en formation (instantané courant, pas d'histoire).
- **Commentaires de passe `/devil` convertis** : ils racontaient le bug (« `p.get` levait
  `AttributeError` », « serait sinon déclaré vivant ») ; ils énoncent maintenant la **règle**
  (garbage is not data ; un carnet sans entrée exploitable retombe sur ABSENT). Aucun tag process ne
  subsiste dans le code applicatif.
- **Typage strict** : alias `Print = tuple[float, float, float, str]` pour le print validé ;
  `_new_bucket`/`_add` typés dessus ; `_valid(p: Any)`, `_book_maps(book: Any)`, et surtout
  `prints: Sequence[Any]` **délibérément** — la source peut livrer des entrées corrompues et chacune
  est validée puis écartée isolément, plutôt que de faire confiance au type déclaré (le mensonge
  `list[dict]` avait précisément masqué le crash non-dict).
- **Vérif** : aucun log de debug ni code mort ; **323 passed**, ruff clean ; check d'intégration
  moteur (carnet FRESH → `LIVE`, delta et intégrité corrects).

### Tranche 2 (`/feature`) — miroir TS + rendu Canvas (delta, murs L2)
Le panneau `FP` (`s1_state.footprint`, D-037) rend désormais les champs de la tranche 1.
- **Types TS** : `FootprintLevel` + `delta`, `bid_liq?`/`ask_liq?` (**optionnels** — présents
  seulement si le carnet est vivant : absent = pas de donnée, jamais « zéro mur ») ;
  `FootprintCandle` + `delta`, `n_prints`, `book_state` (`BookState = 'LIVE' | 'ABSENT'`) ;
  `FootprintValue` + `ticks_per_candle`.
- **Delta** : en-tête du panneau = delta de la **bougie en formation** (`▲/▼ Δ ±N`, DOM) ; en-tête
  de CHAQUE colonne du Canvas = heure + delta de la bougie (`HEAD_H` 15 → 27, deux lignes). Signe
  **et** glyphe portent le sens — la couleur n'est jamais seule (§3).
- **Murs L2** : bande dédiée à droite du Canvas, **bougie en formation UNIQUEMENT**. Le **côté est
  encodé par la POSITION** (moitié gauche = bid/support, moitié droite = ask/résistance) avec un
  séparateur central, pas seulement par la teinte — SKY, distincte du vert/rouge (agresseur) et de
  l'or (POC). Longueur ∝ liquidité relative. **Vérifié par mesure de pixels** : bid seul → 960 px à
  gauche / 0 à droite ; ask seul → 0 / 960.
- **FAIL-CLOSED (§3)** : la bande n'apparaît que si `book_state === 'LIVE'` **ET** qu'au moins une
  liquidité finie > 0 existe. Sinon **rien n'est dessiné** et l'absence est **DITE** en légende
  (« L2 carnet absent — murs non affichés ») : une bande vide se lirait « aucun mur » alors qu'on
  n'en sait rien.
- **Déjà livré, non retouché** : la surbrillance des imbalances (fond gradué + ▲/▼) et le POC or
  existaient depuis D-037 — vérifié à l'essai plutôt que réimplémenté.
- **Vérif** : essai Playwright **RED → GREEN** sur 4 scénarios (carnet LIVE → murs + delta + légende ;
  `ABSENT` → aucun mur et absence annoncée ; imbalances/POC conservés ; LIVE sans liquidité → aucun
  mur inventé), **0 erreur JS** ; probe d'encodage de position ; **essai sur flux réel** (delta
  `▲ Δ +149`, 1570 px de murs, légende vivante) ; `tsc` + `vite build` OK ; **323 passed** (backend
  inchangé) ; captures à l'appui.

### /devil D-042 tranche 2 — L2 aberrant, clignotement du carnet, delta extrême, resize
Attaques : liquidités L2 gigantesques (1e12)/négatives/non-finies, bascule rapide `book_state`
LIVE↔ABSENT, delta massif (1,23e9) et nul (0 print), redimensionnement extrême + Retina.
- **1 défaut RÉEL trouvé & corrigé — saut de grille au clignotement du carnet.** La largeur du
  canvas incluait la bande L2 **conditionnellement** (`walls ? L2_W : 0`) : à chaque bascule
  LIVE↔ABSENT — situation NORMALE dès que le carnet passe STALE — toute la grille se décalait
  latéralement. Mesuré : 12 bascules rapides → **2 largeurs distinctes (314 et 216 px)**. Corrigé :
  la bande L2 est **TOUJOURS réservée** (colonne stable) ; seul son CONTENU varie → **1 seule
  largeur (348 px)** sur 12 bascules.
- **Corollaire (§3)** : une colonne réservée mais vide se lirait « aucun mur ». Quand le carnet est
  indisponible, la colonne affiche un **tiret neutre par niveau** + la légende « L2 carnet absent —
  murs non affichés ». Le vide est EXPLIQUÉ, jamais muet.
- **Chemins déjà sûrs confirmés** : liquidités **1e12 / négatives / NaN / Infinity** → barres bornées
  à la demi-bande, canvas borné, **DPR exact** (les gardes `Number.isFinite` + `> 0` tiennent) ;
  **delta 1,23e9** → texte 34 px dans une colonne de 132 px (aucun débordement), **delta 0** rendu
  sans glyphe directionnel (ni ▲ ni ▼ : pas de sens inventé) ; resize 2400×1400 et 1600×950 →
  **DPR exact**, murs peints, canvas borné.
- **Hors périmètre, signalé** : à 360×300 le panneau se replie (canvas 1×1, aucun crash) — la
  coquille du terminal déborde déjà à cette largeur sur TOUTES les vues (mesuré au `/devil` D-043),
  ce n'est pas un défaut introduit ici et le terminal dense ne cible pas ce format.
- **Vérif** : essai Playwright 4 axes, **0 erreur JS** ; `tsc` + `vite build` OK ; **323 passed**
  (backend inchangé) ; captures LIVE et ABSENT à l'appui.

### /polish D-042 tranche 2 — lisibilité du rendu + fiabilité de l'instrument d'essai
Nettoyage **sans changement de comportement** (essais rejoués : mesures identiques à l'avant-refactor
— 864 px de murs, géométrie 348 px stable sur 12 bascules) :
- **Docstring de module réécrit** : il ne décrivait que D-037 alors que le panneau porte désormais le
  delta et les murs L2. Les arbitrages deviennent des notes durables — pourquoi la bande L2 est
  toujours réservée (sinon la grille saute au clignotement du carnet), pourquoi le côté est encodé par
  la position, pourquoi un delta nul ne reçoit aucun glyphe directionnel.
- **Bloc anonyme `{ … }` supprimé** : la bande L2 était dessinée dans un bloc nu au milieu de `draw`,
  qui se lit comme une erreur de syntaxe. Extrait en fonction nommée **`drawL2Strip`** au contrat
  explicite (géométrie, bougie en formation, murs) — la fonction porte aussi le filtrage des niveaux
  visibles, dupliqué auparavant dans les deux branches.
- **Formateurs dédupliqués** : `fmt` (volume) et `fmtSignedCompact` (delta) répétaient la même
  logique k/M ; extraite dans `compact()`. Le signe reste porté par `fmtSignedCompact` seul.
- **Dernière référence de passe `/devil`** convertie en énoncé de règle.
- **Instrument d'essai fiabilisé (leçon de session)** : un run avait produit des résultats
  entièrement trompeurs — le `kill` visait un PID périmé, le SSE live écrasait chaque état forcé, et
  les mesures ressemblaient à une régression du refactor. Les essais gèlent désormais le flux par
  `pkill` (exception gérée) **et vérifient que l'état forcé s'est appliqué**, sinon ils échouent
  bruyamment plutôt que de conclure sur du vide.
- **Vérif** : **323 passed**, ruff clean ; `tsc` + `vite build` OK ; **deux essais Playwright rejoués
  en régression** (feature 4/4, devil 4 axes) → **0 erreur JS**, valeurs identiques.

## D-044 · Moteur Black-Scholes — pricing, Grecques, inversion d'IV
**Deux contradictions de spec tranchées avec l'opérateur (AskUserQuestion)** avant d'écrire une
ligne :
1. **Le cahier demandait un « module de calcul vectorisé en TypeScript » côté backend** — or `§4`
   fixe le backend en **FastAPI/Python**, et `§1` veut qu'un panneau lise **un champ du schéma**.
   Un pricing en TS l'aurait déplacé dans le navigateur : Grecques hors du `ContextSchema`, chaque
   instance (Sony / Youssef) calculant les siennes (divergence possible entre les deux opérateurs),
   et non testables en pytest. **Décision : moteur en Python**, comme tous les moteurs déterministes
   déjà livrés (Phase 0, footprint, walk-forward, Monte Carlo).
2. **Grille OMON en Canvas** — la grille est déjà une **table HTML** dense/monospace/tabulaire.
   La réécrire en Canvas ferait perdre la sélection de texte et l'accessibilité pour un gain nul à
   ~20 lignes ; le 60 FPS compte sur la **courbe de skew**, déjà en Canvas DPR-exact (D-039).
   **Décision : garder la table et l'enrichir** (Theta/Vega).

**Ce qui manquait vraiment (vérifié avant de coder)** : `options_chain.py` (D-039) ne fait que
**RELAYER** l'IV et les Grecques de la source `greeks_engine` — **aucun pricing n'existe**, ni
Black-Scholes, ni inversion d'IV, et **ni Theta ni Vega** (pattes : `iv, delta, gamma, vanna, charm`).

### Tranche 1 (`/feature`) — `backend/app/black_scholes.py`
Pur, déterministe, hors hot path (§7). Numpy étant absent, « vectorisé » = **batch sur la chaîne
entière en un appel** (`price_chain`), chaque ligne isolée.
- **Pricing** BSM européen call/put ; **Grecques** Delta, Gamma, **Theta** (par an), **Vega** (pour
  σ+1.0), **Vanna** (∂Delta/∂σ) — **conventions figées dans le module** pour que l'affichage ne les
  réinvente jamais.
- **IV : Newton-Raphson** (départ Brenner-Subrahmanyam) avec **repli BISSECTION** bornée `[1e-6, 5]`
  dès que Newton sort des bornes ou que le vega s'effondre — déterministe.
- **FAIL-CLOSED (§3)** : entrée non-finie, `S/K/T/σ ≤ 0`, type inconnu → `None` ; prix **hors bornes
  d'arbitrage** (sous l'intrinsèque, ou > `S` pour un call / > `K` pour un put) → `None` ; **IV
  introuvable → toutes les Grecques `None`** (on ne price jamais sur une vol inventée) ; ligne de
  chaîne corrompue écartée seule.
- **Garde d'IDENTIFIABILITÉ (trouvée en cours de test, non demandée)** : sur une option très ITM la
  valeur temps est **nulle en float64** — le prix est bit-identique pour σ = 0.1 et σ = 0.4. Le
  moteur renvoyait pourtant une vol (0.528) : c'était **fabriquer une précision absente de la
  donnée**. Un prix collé à l'intrinsèque (à quelques ULP) renvoie désormais `None`.
- **Vérif** : **22 tests** (prix call/put vs valeurs manuelles, parité put-call, 5 Grecques vs
  référence, delta put = delta call − 1, gamma/vega identiques call/put, aller-retour d'IV sur 4
  vols et 3 strikes, repli bissection, déterminisme, 8 cas fail-closed, batch avec lignes corrompues)
  → **345 passed**, ruff clean. **Essai réel** : smile complet (7 strikes ES, 30 j) pricé puis
  inversé — **smile retrouvé à ~1e-14**, gamma maximal à l'ATM, **vanna changeant de signe** de part
  et d'autre de l'ATM, parité put-call vérifiée sur toutes les lignes.
- **À venir** : câblage au `ContextSchema` (Theta/Vega dans `OptionLeg`, calcul moteur au lieu du
  relais source) puis affichage dans la table OMON — tranche 2.

### /devil D-044 — pathologies de marché extrêmes
Attaques : `r`/`σ` absurdes ou négatifs, `T → 0`, strikes aberrants, prix violant la parité
put-call ou l'intrinsèque.
- **3 crashes NON MAÎTRISÉS trouvés & corrigés.** Le module promet `None` sur donnée invalide (§3)
  — il ne validait que la **finitude**, jamais la **magnitude**, et **levait** sur trois chemins :
  `math.exp` déborde (`OverflowError`) dès `r·T ≲ −710` ; `σ·√T` s'annule par underflow →
  `ZeroDivisionError` ; `S/K` sous-déborde à 0 → `math.log(0)` (`ValueError`). Une seule ligne de
  chaîne aux paramètres absurdes aurait emporté toute la chaîne. Corrigé par un noyau `_core`
  gardé, plus une garde **par Grecque**.
- **Correctif d'abord INCOMPLET — c'est le balayage exhaustif qui l'a montré.** Après la première
  correction, un balayage de **17 150 combinaisons** de magnitudes signalait encore **432 crashes et
  40 valeurs non-finies émises** : `_core` était gardé, mais pas les formules de Grecques, dont
  `gamma = pdf/(S·σ·√T)` divise par un dénominateur qui sous-déborde à 0. Chaque Grecque est
  désormais évaluée isolément → `None` si indéfinie (jamais `0.0`, qui se lirait comme une mesure,
  ni `inf`). Le prix aussi est validé fini avant d'être renvoyé.
- **Comportements corrects confirmés** (aucun défaut) : `σ = 1000` → le call vaut le sous-jacent ;
  **`r = −0.5`** (taux négatifs = réalité de marché, pas une aberration) → parité put-call vérifiée
  avec le facteur d'actualisation > 1 ; **`T` = 1 seconde** → gamma explosif mais **borné** (112) et
  vega effondré (0.007), aucun `inf` ; strikes `10·S` et `0.01·S` → prix finis ; prix sous
  l'intrinsèque ou hors bornes → `None`.
- **Vérif** : +12 tests /devil dont **deux balayages exhaustifs en non-régression** (18 230
  combinaisons : **0 crash, 0 valeur non-finie, 0 vol aberrante**) → **357 passed**, ruff clean ;
  smile réel toujours retrouvé à **1,5e-13**.

### /polish D-044 — bornes de magnitude promues en contrat documenté
Nettoyage **sans changement de comportement** (34 tests verts et smile à 1,5e-13 avant comme après) :
- **Les bornes de magnitude deviennent le contrat central du module**, sous forme d'un **tableau en
  tête de fichier** : pour chaque expression (`K·e^{−rT}`, `σ·√T`, `ln(S/K)`, `pdf/(S·σ·√T)`), la
  rupture (`OverflowError`, underflow → division par zéro, domaine) et son seuil. Elles n'étaient
  documentées que dans `_core`, alors qu'elles conditionnent tout le module — et c'est précisément
  cette dispersion qui avait laissé `gamma` sans garde. Les docstrings de `_core` et de `g()`
  renvoient au tableau au lieu de le répéter.
- **`_kind` → `_is_kind`** : la fonction renvoyait `str | None` mais n'était jamais utilisée que
  pour sa None-ité (`_kind(kind) is None`) ; elle est désormais un prédicat booléen lisible.
- **Tests** : `import itertools` hissé en tête de fichier (il était local à deux fonctions) ; les
  récits de passe convertis en **règles** — le commentaire de section énonce le contrat (« la
  finitude ne suffit pas, ce sont les magnitudes qui cassent ») et la docstring du balayage explique
  **pourquoi il est conservé** : un garde posé sur le noyau ne protège pas les formules de Grecques,
  qui ont chacune leur dénominateur.
- **Vérif** : aucun code mort, aucun log de debug, aucun tag process restant ; typage strict
  (`_finite(x: Any)`, `_is_kind(k: Any) -> bool`, `Sequence[Any] | None`, retours `float | None`) ;
  **357 passed**, ruff clean.

### Tranche 2 (`/feature`) — câblage du moteur dans OMON + affichage
**Hypothèse tranchée sans blocage** (§12) : la source ne fournissait **que** des IV et des Grecques,
**aucun prix** — Newton-Raphson n'aurait rien eu à inverser. Un vrai feed d'options porte des prix,
donc le `MockDataSource` en **émet désormais** (générés par le modèle à l'IV de son smile, si bien
que l'inversion doit retrouver exactement ce smile — vérifiable de bout en bout).
- **`charm` ajouté au moteur** pour que la provenance d'une ligne soit **uniforme** (sinon 5 Grecques
  calculées + 1 relayée dans la même patte). Formule fermée facile à écrire avec un signe faux :
  **validée contre la dérivation numérique de delta** — et le validateur a effectivement attrapé une
  **inversion de signe** dans ma première écriture.
- **Enrichissement ADDITIF avec PROVENANCE explicite** (`greeks_source`), pour qu'un calcul ne passe
  jamais pour une donnée de marché ni l'inverse (§3) : `INVERTED` (prix présent → IV inversée puis
  les six Grecques), `SOURCE_IV` (pas de prix exploitable → Grecques calculées à l'IV source, l'IV
  source étant conservée telle quelle), `RELAY` (ni prix ni IV → valeurs source relayées, le reste
  `None`). Prix aberrant → **repli sur `SOURCE_IV`**, jamais une vol fabriquée.
- **Changement de contrat assumé** : les Grecques ne sont plus RELAYÉES mais CALCULÉES — c'est l'objet
  du livrable (valeurs identiques pour les deux opérateurs). Le test historique qui vérifiait le
  relais a été **réécrit** pour énoncer le nouveau contrat plutôt que contourné.
- **Frontend** : `OptionLeg` porte `theta`, `vega`, `greeks_source` ; le sélecteur de Grecque de la
  table OMON gagne **Θ/j** et **V/pt** — le moteur fixe ses conventions (theta/an, vega pour σ+1.0)
  et **l'affichage convertit vers les unités d'un opérateur** (par jour, par point de vol), le
  libellé le disant. Badge de **provenance** dans l'en-tête du panneau. Le fail-closed d'affichage
  était **déjà en place** (`num()` rend `·` sur non-fini) — vérifié à l'essai, pas réimplémenté.
- **Taux sans risque** : `config.RISK_FREE_RATE` (0.045, `v1 provisional` — à brancher sur une vraie
  courbe OIS le jour venu), passé par l'engine.
- **Vérif** : +6 tests de chaîne + 2 de charm → **365 passed**, ruff clean ; `tsc` + `vite build` OK ;
  **essai réel bout en bout** : **52/52 pattes call avec IV INVERSÉE** depuis le prix, Theta/Vega
  présents partout ; essai Playwright — Θ/j et V/pt affichent 13 valeurs réelles chacun, badge
  « IV inversée du prix », **0 erreur JS** ; capture à l'appui.

### /devil D-044 tranche 2 — données hybrides, prix aberrants, sauts en direct
Attaques : chaîne mêlant `INVERTED`/`SOURCE_IV`/`RELAY`, prix négatifs ou sous l'intrinsèque,
rafale de mises à jour en direct sur le sélecteur Θ/Vega.
- **1 défaut RÉEL trouvé & corrigé — le badge de provenance MENTAIT.** Il n'inspectait que
  `r.call`. Sur une chaîne **asymétrique** (tous les calls `RELAY`, tous les puts `INVERTED`) il
  affichait « valeurs source relayées » pendant que la colonne Θ des puts montrait des Grecques
  **calculées** (−2,19 / −2,20) — exactement l'ambiguïté que la provenance devait supprimer (§3).
  Corrigé : le badge agrège les **deux pattes** ; la chaîne asymétrique affiche désormais
  « IV inversée (partiel) ».
- **Backend : aucun défaut** (7 cas sondés) — prix valide → `INVERTED` ; IV seule → `SOURCE_IV` ;
  ni l'un ni l'autre → `RELAY` ; **prix négatif**, **prix sous l'intrinsèque** (call ITM à 1,0) et
  **prix non-fini** → repli propre sur `SOURCE_IV`, jamais une vol fabriquée ; ligne asymétrique
  étiquetée correctement patte par patte ; **aucune valeur non-finie émise**.
- **Chemins déjà sûrs confirmés** : chaîne hybride → **tirets neutres exactement là où la patte est
  `RELAY`**, aucun effet de bord visuel ; **12 mises à jour rapides** → 12 jeux de valeurs distincts,
  **0 NaN/Infinity**, toujours 13 lignes ; `expIdx` **déjà borné** (`Math.min(expIdx, len−1)`) donc
  une chaîne qui rétrécit en direct ne sort pas de plage — suspicion levée sans correctif.
- **Vérif** : essai Playwright 3 axes, **0 erreur JS** ; **365 passed**, ruff clean ; `tsc` +
  `vite build` OK.

### /polish D-044 tranche 2 — unités d'affichage homogènes, provenance en design note
- **Défaut de cohérence trouvé & corrigé — deux colonnes voisines à des ÉCHELLES différentes sans
  le dire.** La tranche 2 convertissait theta et vega en unités d'opérateur (`Θ/j`, `V/pt`) mais
  laissait **vanna et charm bruts sous un libellé sans unité** (« Vanna », « Charm »). Le moteur les
  produit pourtant dans les mêmes conventions brutes que leurs voisines — charm **par an** comme
  theta, vanna **pour σ+1.00** comme vega — donc un opérateur lisant `Θ/j = −1,90` à côté de
  `Vanna = −1,269` ne pouvait pas savoir que la seconde est *par 100 points de vol*. Corrigé :
  `G_SCALE` étend la conversion (vanna `/100`, charm `/365`), les libellés deviennent **`Vanna/pt`**
  et **`Charm/j`**, et les décimales suivent (4 chiffres). **Règle durable** : le libellé de colonne
  PORTE l'unité — jamais un nombre dont l'échelle est implicite. Delta et gamma, sans dimension
  temporelle ni vol, passent tels quels.
- **Provenance hybride promue en design note durable** (docstrings `options_chain.py` **et**
  `OptionsChainPanel.tsx`) : tableau `INVERTED` / `SOURCE_IV` / `RELAY` — entrée disponible → ce que
  portent réellement les Grecques ; décision **patte par patte** ; badge frontend qui **agrège les
  deux pattes** et se dégrade en « (partiel) » dès qu'une chaîne est asymétrique. Le badge résume ce
  qui est **à l'écran**, pas le cas nominal.
- **Rien à élaguer côté debug** : ni `console.*`, ni `print`/`logging`, ni TODO/FIXME dans les deux
  fichiers. Les marqueurs `/devil :` du dépôt sont la **convention durable** (explication de la
  garde, pas trace temporaire) ; les hooks `window.__set*` restent **`import.meta.env.DEV`** et sont
  élagués du bundle de production.
- **Vérif** : essai Playwright OMON **live + régression** — badge live « IV inversée du prix », les
  **6 grecques** parcourues sans une seule valeur non-finie affichée, entêtes portant l'unité,
  hybride → tirets exactement sur `RELAY`, asymétrie → « IV inversée (partiel) », 12 mises à jour
  rapides → 12 jeux distincts / 0 NaN / 13 lignes, **0 erreur JS**. **365 passed**, ruff clean,
  `tsc` + `vite build` OK.

## D-045 · TradeManifest — contrat-pont LSR v1.2 → Cholismo (émetteur semi-automatique)
Le moteur **Liquidity Sweep Reversion v1.2** est un moteur TypeScript AUTONOME, externe à ce dépôt
(88 tests, `strict` + `noUncheckedIndexedAccess`). `backend/app/trade_manifest.py` sérialise sa
sortie APPROUVÉE en un objet stable ; `frontend/src/types/trade_manifest.ts` en est le miroir.

**Décisions de conception :**
- **§2.1 — divergence assumée d'avec le doc d'intégration LSR.** Son driver d'exemple fait
  `broker.submit(plan.executionPlan)` ; Cholismo, en tant que driver, **ne le fait pas et ne peut
  pas le faire**. Le manifeste est une **PROPOSITION enregistrée et affichée** — « semi-automatique »
  = automatique jusqu'au ticket, manuel au déclenchement (Go/No-Go humain). Aucune fonction du
  module n'ouvre de socket ni n'appelle un courtier.
- **camelCase — exception délibérée et bornée (§5).** Le ContextSchema est 100 % snake_case
  (81 champs) ; ce manifeste n'en fait PAS partie : il naît côté TypeScript (moteur LSR) et arrive
  tel quel au frontend. Le garder camelCase de bout en bout supprime toute couche de traduction sur
  le seul contrat qui traverse les trois mondes (moteur → Python → UI). Identifiants en anglais (§5).
- **Horloge INJECTÉE, jamais lue** — même règle que le moteur (« `now` et `state` sont injectés »).
  Péremption déterministe et rejouable : borne d'échéance **INCLUSE** (à l'instant pile = périmé,
  fail-closed), `remaining_ms` borné à 0, horloge **non finie ou non entière → périmé / refus**
  (un doute sur l'heure ne rend jamais un ticket actionnable, §3). Epoch **ms entier**, comme
  `Date.now()`.
- **Fail-closed intégral (§3)** : statut ≠ `APPROVED` → rien ; prix non fini / mal typé (`bool`
  exclu explicitement — `True` n'est pas un prix ni « 1 contrat ») → rien ; contrats non entiers
  strictement positifs → rien ; **géométrie revérifiée à la frontière** (LONG : stop < entrée < TP ;
  SHORT symétrique ; niveau collé à l'entrée = incohérent) même si le moteur la teste déjà — on ne
  fait pas confiance à l'amont ; TTL invalide → rien. Jamais un ticket dégradé.
- **`id` = SHA-1 tronqué du contenu** : rejouer le même plan à la même ms redonne le même id
  (idempotence face à un journal append-only, clé React stable) ; contenu ou instant différent → id
  différent.
- **`v1 provisional`** : la forme du plan lue (`status`, `direction` LONG/SHORT→BUY/SELL,
  `executionPlan.{entryType,entryPrice,stopLoss,takeProfit,contracts}`) est reconstituée du doc
  d'intégration v1.2, le `types.ts` du moteur n'étant pas dans le dépôt. Point de couture unique :
  `_execution_fields()`. `DEFAULT_TTL_MS = 3000` (spec).
- **Vérif** : 57 tests dédiés (contrat de fil, péremption, 30+ chemins fail-closed paramétrés,
  idempotence) — **422 passed** au total, ruff clean, `tsc` + `vite build` OK ; essai manuel réel :
  plan MNQ SHORT → JSON émis par Python **collé tel quel** dans un fichier TS et validé
  `tsc --strict --noUncheckedIndexedAccess` (sémantique de péremption identique des deux côtés).

**Hors périmètre de cette tranche** (à câbler ensuite) : persistance du manifeste dans le journal
event-sourced, panneau d'affichage avec compte à rebours TTL, et le branchement du moteur LSR
lui-même (externe).

### Tranche 2 — Alerte frontend : dérive d'horloge, lock UI, overlay (devil-driven)
`store/manifest.ts` + `panels/TradeAlertOverlay.tsx` + event SSE `trade_manifest` (canal rapide) +
hook DEV `__pushManifest`. Trois exigences /devil intégrées dès la conception :
- **Dérive d'horloge — le frontend ne compare JAMAIS le `timestamp` backend à son `Date.now()`.**
  Le compte à rebours démarre à la RÉCEPTION de l'événement SSE, sur `performance.now()` (horloge
  MONOTONE locale, insensible aux sauts NTP). Prouvé dans l'essai : un manifeste daté **epoch 0
  (1970)** vit exactement ses 3 s à l'écran. Le rAF recalcule depuis le delta réel à chaque frame :
  un onglet en arrière-plan (rAF suspendu) n'étire pas le TTL — au retour, l'échéance vraie
  s'applique immédiatement. Le `timestamp` backend reste une donnée d'affichage.
- **Lock UI — garde STRUCTURELLE, pas seulement clavier.** Espace → transition unique
  `ARMED → LOCKED` dans le store (`lock()` no-op sinon) : quoi que fasse le clavier, il n'existe
  qu'une transition (lockCount vérifié = 1 sous rafale Espace/G/V/Échap). Une fois LOCKED, toute
  touche est ignorée et l'overlay reste figé jusqu'à la fin du TTL.
- **Clavier MODAL en phase capture** : pendant une alerte, les touches simples ne fuient jamais
  vers les raccourcis globaux (V ne change pas la vue, G ne poste pas de GO — prouvé) ; les
  combinaisons Ctrl/Cmd/Alt du navigateur passent. ARMED : Espace valide, Échap refuse.
- **Overlay** : direction en couleur VIVE mais jamais seule (§3) — flèche + « ACHAT · LONG » /
  « VENTE · SHORT » massifs ; STOP/OBJECTIF en très gros corps ; barre TTL qui se vide + restant
  numérique ; « AUCUN ORDRE ENVOYÉ » affiché en permanence (§2.1). Fin de TTL (même LOCKED) ou
  Échap → **démontage silencieux** (fail-closed : un signal périmé n'est plus actionnable).
- **Fail-closed à la réception** : la frontière re-vérifie le manifeste (champs, finitude,
  direction, TTL > 0, géométrie stop/TP) même si le backend garantit déjà — 6 malformés injectés,
  0 affiché. **Anti-substitution** : un manifeste reçu pendant qu'une alerte est affichée est
  IGNORÉ — le ticket ne change jamais sous le doigt de l'opérateur entre sa lecture et son Espace.
- **Vérif** : essai Playwright 6 axes (drift 1970, contenu §3, Échap, lock+rafale, malformés,
  anti-substitution) → tout vert, **0 erreur JS** ; `tsc` + `vite build` OK ; captures à l'appui.
- **Hors périmètre restant** : persistance de l'ACK dans l'event store (l'enregistrement est
  aujourd'hui l'état verrouillé du store frontend + `lastLockedId`), émission backend de l'event
  SSE `trade_manifest` (le listener est câblé, le moteur LSR est externe).

### /devil — rafales, mort-nés, gel de thread + journalisation des issues (tranche 3)
Quatre attaques, quatre protections — dont un **changement de comportement assumé** :
- **STRICT DROP sous rafale, verrouillé.** Pas de file LIFO/FIFO : un signal reçu pendant qu'une
  alerte est affichée est définitivement jeté — après un Échap, RIEN ne ressort d'une file
  (10 manifestes en rafale, 0 réapparition). En microstructure on ne trade pas le passé :
  setup raté = on attend le prochain.
- **MORT-NÉS — le comportement de la tranche 2 est CORRIGÉ.** Avant : un manifeste daté epoch 0
  vivait ses 3 s (preuve d'indépendance au timestamp backend). Désormais l'admission calcule
  l'**âge de transit** = `Date.now() + clockOffset·1000 − timestamp` — PAS une comparaison naïve
  d'horloges : `clockOffset` (server_ts − client_ts) est MESURÉ en continu via `session_identity`
  (canal rapide), ce qui neutralise la dérive entre machines ; le reste est du transit réseau.
  Transit ≥ TTL → jeté AVANT tout rendu (**0 frame**), non journalisé (jamais montré à l'humain,
  ce n'est pas sa performance). Un manifeste admis vit toujours son TTL PLEIN depuis la réception
  (spec tranche 2) : l'âge résiduel à l'expiration est donc borné à < 2×TTL — assumé, documenté.
- **GEL DE THREAD — garde dans le STORE, pas dans le rendu.** Un thread principal figé 2,6 s
  (busy-wait) fait arriver l'Espace en file AVANT la frame rAF suivante : `lock()` re-vérifie
  l'échéance au moment de l'action et refuse (→ TIMEOUT journalisé, overlay démonté, lockCount 0).
  Le rAF seul aurait laissé une fenêtre de validation d'un ticket mort.
- **JOURNALISATION DES ISSUES (event store, append-only §2.5).** Kind `manifest_outcome` :
  `ACK` / `REJECT_USER` / `TIMEOUT` + **`reaction_time_ms`** (affichage → action humaine, la
  mesure de la performance d'exécution post-session). Contrat strict : reaction_time OBLIGATOIRE
  (fini, ≥ 0, ≤ TTL) pour ACK/REJECT_USER, **INTERDIT pour TIMEOUT** — pas d'action humaine, on
  n'invente pas une latence (§3). `POST /manifests/outcome` + `GET /manifests/outcomes`
  (projection : événements + comptes + médianes par issue, calculées UNIQUEMENT sur les latences
  réellement mesurées). Tir sans attente côté frontend (l'UI ne bloque jamais sur le réseau) ;
  échec réseau → `lastError` visible. Une seule issue par manifeste (transitions du store) :
  fin de TTL d'une alerte LOCKED = simple démontage, l'ACK est déjà journalisé.
- **Migration SQLite** : le CHECK de `journal_entries` est figé dans le DDL des bases existantes →
  reconstruction à l'identique à l'ouverture (événements copiés VERBATIM, seq préservés, triggers
  anti UPDATE/DELETE recréés aussitôt). L'append-only porte sur les ÉVÉNEMENTS, pas sur le DDL.
  Couvert par test (base pré-D-045 fabriquée, legacy intact, nouveau kind accepté, UPDATE refusé).
- **Vérif** : essai Playwright 5 axes (rafale, mort-né, TTL-à-réception, gel, journal ACK 804 ms /
  REJECT 404 ms / TIMEOUT null) → tout vert, **0 erreur JS** ; **432 passed** (10 tests API +
  migration), ruff clean, `tsc` + `vite build` OK.

### /polish — robustesse réseau du POST d'ACK + jauge compositor-only (clôture)
- **Un POST d'ACK qui échoue ne laisse JAMAIS l'UI verrouillée sur une promesse morte.** Deux
  bornes : échec rapide (backend injoignable → le proxy répond 5xx) et **AbortSignal.timeout
  (2,5 s)** pour la requête qui PEND sans répondre — le trou réel : `request()` n'avait aucun
  timeout. Chemin d'échec : bannière **« ⚠ ÉCHEC RÉSEAU — ACK NON JOURNALISÉ »** sur l'overlay
  (icône + texte, §3), `lastError` en Zone 0 (persiste après démontage), démontage auto ~1,8 s.
  **Adaptation §2.1 du message demandé** (« ORDRE NON ENVOYÉ ») : ce terminal n'envoie jamais
  d'ordre — ce qui a échoué est la JOURNALISATION de l'ACK, et le message dit exactement ça.
  Un échec sur REJECT_USER/TIMEOUT (overlay déjà démonté) reste visible via `lastError`.
- **Jauge parfaitement fluide — CSS `transform: scaleX`, compositor-only.** UNE écriture de style
  (FLIP : ancrage du point de départ par reflow, puis `transition: transform <left>ms linear` vers
  `scaleX(0)`) : zéro layout par frame, zéro travail JS pour la barre — rien ne perturbe l'œil
  pendant la lecture du L2. Bonus : le compositeur continue d'animer même si rAF est suspendu
  (onglet en arrière-plan). rAF ne pilote plus que l'échéance et le texte (re-render ~10/s, React
  saute les setState identiques). Mesuré : scaleX échantillonné strictement décroissant au rythme
  exact du TTL (0,075/300 ms sur un TTL de 4 s), largeur constante.

### Résumé d'architecture D-045 (clôture)
```
Moteur LSR v1.2 (TS, externe)          Cholismo backend (Python)              Cholismo frontend (TS)
  evaluateLsr() → plan APPROVED  ──→  trade_manifest.py                     types/trade_manifest.ts
                                       manifest_from_lsr_plan()               (miroir strict + helpers)
                                       · statut APPROVED seul relayé   SSE  store/manifest.ts
                                       · géométrie revérifiée         ────→  · admission : validité +
                                       · id SHA-1 idempotent          `trade_manifest`  géométrie + MORT-NÉ
                                       · fail-closed intégral          (canal rapide)   (transit ≥ TTL → 0 frame)
                                                                              · STRICT DROP (pas de file)
  event store (SQLite append-only)                                            · ARMED → LOCKED (unique)
   journal `manifest_outcome`    ←──  POST /manifests/outcome  ←── fetch ──  · ARMED → REJECT_USER/TIMEOUT
   ACK / REJECT_USER / TIMEOUT        GET  /manifests/outcomes                · LOCKED → FAILED (POST KO)
   + reaction_time_ms                  (projection : médianes/issue)         panels/TradeAlertOverlay.tsx
```
Règles transverses : horloge INJECTÉE partout (backend : `now_ms` paramètre ; frontend : TTL depuis
la réception sur `performance.now()`, transit corrigé du `clockOffset` mesuré) ; §2.1 aucun chemin
vers un courtier, l'humain tranche ; §3 fail-closed à chaque frontière (jamais un ticket dégradé,
jamais une latence inventée) ; contrat camelCase borné au manifeste (né côté TS, hors ContextSchema).
Restent externes : le moteur LSR lui-même et l'émission backend de l'event SSE (listener câblé).

## D-046 · Câblage de l'émission LSR — microstructure → evaluate_lsr → SSE
Première couche du moteur **Liquidity Sweep Reversion** DANS le backend (`app/lsr_engine.py`) :
```
boucle sweep (1 s, hors hot path §2.8)
  _assemble_sweep ──→ liquidity_sweep.alert (D-028)
  _maybe_emit_lsr(now)
      build_lsr_inputs(schema, now) → LsrInputs     stateless, microstructure SEULE, FRESH only
      evaluate_lsr(inputs) → plan | None            pur, déterministe, rejet = SILENCE (§3)
      manifest_from_lsr_plan(plan) → TradeManifest  garde D-045 (le dernier mot)
      broadcaster.publish("fast", "trade_manifest", …, replay=False)
```
- **ISOLATION stricte** : la couche LSR ne lit QUE tape / order flow / carnet / VPOC / alerte de
  sweep. Le couplage news T1 est une exigence INTERNE du détecteur D-028 (en amont) ; les
  frontières compte (F1/F2/F8), volatilité (F3) et calendrier (F5) du doc LSR = autres couches.
  Le RiskSizer /5 exige un `AccountState` → **1 contrat, v1 provisional** (`LSR_CONTRACTS`).
- **Gates v1 provisional** (`config.LSR_*`, « 1re passe » à figer sur 60 trades) : déclencheur =
  alerte FRAÎCHE et ORIENTÉE (`BID_SWEEP`→LONG / `ASK_SWEEP`→SHORT ; sans direction =
  inorientable → rejet) ; B1 absorption ; B2 bascule des agressifs ≥ 0,60 côté réversion ; F4
  spread ≤ 2 ticks (doc : 1 sur MES réel — 2 = calibration MOCK, env-overridable) + profondeur
  top-3 ≥ 150 des deux côtés ; A3 stop = **extrême RÉEL du sweep** (min/max des prints, jamais
  une distance fabriquée) ∓ buffer ; A1 entrée LIMIT = extrême ± offset ; A2 TP borné [3,5] ticks
  visant VPOC ∓ marge — VPOC du mauvais côté ou pas de place → rejet. Grille `PRICE_TICK`.
- **`replay=False` sur `trade_manifest`** : le cache de replay SSE hydrate les abonnés neufs avec
  l'ÉTAT des blocs — un manifeste est un ÉVÉNEMENT ; re-livrer un ticket d'avant la connexion
  serait un zombie (et un ticket encore dans son TTL serait ré-affiché → double ACK possible).
- **Dédup à DEUX étages — leçon du /devil LIVE.** La 1re version dédupliquait sur `alert.ts` :
  or le détecteur régénère `ts` à chaque tick d'une condition persistante → un 2e manifeste
  émis pour le MÊME sweep (attrapé par l'essai live). Corrigé : identité d'ÉVÉNEMENT
  `trigger|direction` (même composition que `_sweep_last_key` D-028) + reset quand la condition
  se lève. Puis 2e leçon live : le mock déclenche des sweeps quasi EN CONTINU en alternant
  BID/ASK — la clé seule laisserait spammer. Ajout de la **fenêtre anti-FOMO F7-like**
  (`LSR_REARM_COOLDOWN_S = 90`, doc LSR `f7FomoWindowMs`) : une émission max par fenêtre,
  quel que soit l'événement.
- **Démo end-to-end sur le VRAI stack** (aucun code de prod modifié) : source `sierra_chart`
  coupée (levier TASKS 2.4) → injecteur écrit le setup microstructure dans Redis (rafale
  vendeuse → `BID_SWEEP` dv=−50, absorption, agressifs 0,72, carnet 70×3 serré, VPOC 5451) →
  l'engine assemble → D-028 couple la news T1 du mock → LSR émet → **l'overlay s'arme dans le
  navigateur SANS aucune injection frontend** : LONG MES, entrée 5448,25 / stop 5447,50 /
  TP 5449,50 (géométrie exactement prédite) → Espace → **ACK journalisé (392 ms)** dans l'event
  store. Dédup vérifiée : 45 s de condition persistante, UN manifeste.
- **Vérif** : 17 tests dédiés (géométrie LONG/SHORT, chaque gate en silence, pureté/non-mutation,
  FRESH-only, pipeline+dédup+F7+replay) — **449 passed**, ruff clean ; essai live 4 axes, 0 erreur
  JS, capture à l'appui.
- **Hors périmètre restant** : RiskSizer /5 + modif VIX (couche compte), A1 annulation anti-chasse
  (runtime d'ordre — n'existe pas, §2.1), calibration des seuils sur trades réels.

### /devil — pathologies de microstructure (carnet croisé, flux contradictoires, F7 vs inversion)
Attaques sur `evaluate_lsr` : **4 trous réels trouvés et corrigés**, 2 comportements confirmés.
- **Carnet croisé/verrouillé — DÉJÀ sûr, désormais prouvé.** `bid ≥ ask` échoue F4 (`best_ask >
  best_bid` exigé) → géométrie jamais construite, silence. Note de conception : `CROSSED_BOOK` est
  un SIGNAL du détecteur D-028 (la dislocation s'observe) mais jamais un terrain d'exécution —
  signaler ≠ trader.
- **CORRIGÉ — `aggressor_ratio` hors [0,1].** Une part acheteuse est une fraction : un **1.7**
  corrompu passait la gate LONG (`≥ 0.60`) comme un flip « ultra-fort ». Borné strict ; 1.0 et 0.0
  restent légitimes (100 %/0 % acheteurs, testés).
- **CORRIGÉ — prints datés du FUTUR ancraient l'extrême A3.** La fenêtre n'était bornée qu'à
  gauche (`ts ≥ since`) : un print à `now+30` (désync d'horloge source) définissait le stop.
  Fenêtre `since ≤ ts ≤ now` — même leçon que D-028 sur les rafales.
- **CORRIGÉ — prix ≤ 0 traversaient la géométrie.** La garde D-045 vérifie l'ORDRE des niveaux,
  pas leur positivité : un extrême à −5000 aurait produit un ticket négatif COHÉRENT (stop <
  entrée < TP) donc accepté. Prints à prix ≤ 0 écartés de l'extrême ; VPOC ≤ 0 → rejet.
- **CORRIGÉ — profondeur de carnet NÉGATIVE.** `sum(top-3)` laissait un carnet corrompu passer F4
  par compensation (200 + (−30) ≥ 150). Chaque niveau doit être fini et ≥ 0, sinon carnet invalide.
- **Contradiction « volume d'absorption > delta cumulé » : NON REPRÉSENTABLE** avec les entrées
  actuelles — `absorption` est un BOOLÉEN dans le ContextSchema (pas de volume à croiser avec le
  CVD). Tracé hors-scope honnêtement ; à revisiter si la source réelle expose un volume d'absorption.
- **F7 vs sweep INVERSE — blocage AVEUGLE, par conception (testé).** `BID_SWEEP` valide → LONG
  émis ; `ASK_SWEEP` tout aussi valide 10 s après → **silence**. Deux sweeps opposés en 10 s =
  régime de chop/whipsaw — le piège exact que LSR refuse de trader (le B4 du doc est le
  discriminant anti-continuation ; F7 est l'anti-FOMO) ; et une proposition vient peut-être d'être
  ACKée — une position existe peut-être, invisible depuis cette couche (§2.1) → jamais le ticket
  contraire dans la fenêtre. Après la fenêtre, l'inverse redevient proposable (testé : SELL émis).
- **Vérif** : 6 tests /devil ajoutés (23 tests LSR) — **455 passed**, ruff clean.

### /polish — hygiène des logs (clôture D-046)
- **Le silence des rejets est STRUCTUREL, pas discipliné** : `evaluate_lsr` est une fonction pure
  qui ne contient AUCUN logger — un rejet naturel (gate rouge, carnet invalide, corruption de
  flux) ne peut pas spammer, par construction. Mesuré en réel : **45 s de churn organique**
  (le mock déclenche des sweeps en continu, gates majoritairement rouges) → **0 ligne** émise,
  5 lignes de log au total (démarrage uvicorn seul).
- **Seule l'ÉMISSION logge — une ligne INFO, actionnable** : direction, instrument, entrée/stop/TP,
  contrats, id du manifeste (corrélable au journal `manifest_outcome`). Mesuré : une émission
  forcée → exactement 1 ligne. La dédup et le cooldown F7 ne loggent pas non plus (un non-événement
  n'est pas un événement). Verrouillé par test `caplog` : 5 rejets consécutifs → 0 record ;
  émission → 1 record INFO et rien d'autre ; ré-évaluation dédupliquée → toujours 1.
- Les `log.exception` des boucles (fast/slow/sweep) restent : une EXCEPTION n'est pas un rejet
  naturel, c'est une panne — elle doit se voir.

### Résumé d'architecture D-046 (clôture)
```
    flux microstructure (mock/réel)          engine (asyncio)                       frontend
tape · carnet L2 · absorption ·        ┌─ fast loop (250 ms) : assemble s1_state
agressifs · VPOC   ──── Redis raws ──→ │   (hot path < 200 ms, JAMAIS de LSR ici)
                                       ├─ sweep loop (1 s, hors hot path §2.8) :
econ_calendar (news T1) ─────────────→ │   D-028 : anomalie ⊕ news → alert         SSE fast
                                       │   D-046 : build_lsr_inputs (FRESH only,   ────────→ overlay
                                       │           microstructure SEULE)                     D-045
                                       │           evaluate_lsr (pur, silencieux)            (TTL,
                                       │           dédup événement + fenêtre F7              lock,
                                       │           manifest_from_lsr_plan (garde)            ACK)
                                       │           publish trade_manifest                      │
                                       └─ event store append-only  ←── POST /manifests/outcome ┘
```
Frontières de responsabilité : détecteur D-028 = OBSERVER la dislocation (news couplée en interne) ;
couche LSR D-046 = ÉVALUER la réversion sur microstructure seule et PROPOSER ; garde D-045 =
revérifier le contrat ; overlay = AFFICHER, l'humain tranche ; event store = SE SOUVENIR. Les
couches compte (F1/F2/F8, RiskSizer /5), volatilité (F3) et news (F5) restent externes — services
séparés. Aucun ordre nulle part (§2.1).

## D-047 · Couche Compte & RiskSizer — frontières de risque prop-firm EOD
`backend/app/risk_sizer.py` + miroir `frontend/src/types/account.ts` (snake_case : l'état naît
côté Python — chaque contrat garde la convention de son lieu de naissance, cf. D-045).

**Tranche 1 — la couche PURE (State & RiskSizer), spec mathématique du doc LSR v1.2 :**
- **`AccountState` stateless** : `current_equity`, `day_start_equity`, `drawdown_floor`
  (STATIQUE en intraday — le recalcul EOD Trail à la clôture est le travail du driver, hors
  couche), `daily_loss_limit`. **F1 STRUCTUREL** : `account_type` n'admet que
  `EOD_TRAILING | EOD_STATIC` — le modèle Apex « Intraday Trail » est NON-REPRÉSENTABLE par
  construction (pas une garde à l'exécution : le type refuse).
- **Buffer = distance vers la mort** : `min(equity − floor, equity − (day_start − DLL))`. Sur
  Apex 50K EOD à l'ouverture : `min(2500, 1000) = 1000` → **le DLL est la frontière
  contraignante** (l'exemple exact du doc — sizing mécaniquement plus serré que sans DLL).
- **Règle stricte du 1/5e** : risque alloué = `buffer / RISK_BUFFER_DIVISOR` (5, config).
  Contrats = `floor(risque / (ticks_de_stop × valeur_tick))` — floor, jamais d'arrondi haut.
  `INSTRUMENT_SPECS` : constantes contractuelles CME (MES 1,25 $/tick ; MNQ 0,50 $/tick).
- **F8 fail-closed, ZÉRO exception** : la fonction rend TOUJOURS un `SizerResult` — taille < 1
  ou buffer ≤ 0 → `REJECTED / INSUFFICIENT_BUFFER` ; entrée corrompue (non-finie, ticks ≤ 0,
  valeur de tick ≤ 0, diviseur invalide) → `REJECTED / INVALID_INPUT`. `contracts` n'existe QUE
  sur APPROVED — jamais un 0 déguisé en taille (§3).
- **Preuve demandée, exécutée** (essai réel, assertion de monotonie) — Apex 50K, pertes
  successives intra-journée, stop 8 ticks MES : **20 → 15 → 10 → 5 → 2 → 1 → F8** (buffer 20 $
  < 1 contrat) → REJECTED, puis buffer 0 et négatif → REJECTED. Second scénario : lendemain
  difficile (day_start 48 200) → le FLOOR devient contraignant, blocage à 40 $ du plancher —
  le coupe-circuit mord AVANT la mort du compte.
- **Piège documenté (trouvé par l'essai)** : `apex_eod_account(preset, current_equity=X)` SANS
  `day_start_equity` = sémantique « jour neuf » (`dayStart ?? equity`, héritée du doc) — le DLL
  y est toujours plein. Pour simuler des pertes intra-journée, fixer `day_start_equity`.
  Mon premier script d'essai est tombé dedans : table fausse (buffer 1000 constant), corrigée.
- **Montants Apex = ordres de grandeur publics À VÉRIFIER le jour de l'achat** (doc ; plus de
  reset depuis mars 2026 — un breach impose le rachat : F8 a une valeur monétaire directe).
- **Hors périmètre de cette tranche** (documenté, pas oublié) : câblage dans `_maybe_emit_lsr`
  — il exige une SOURCE de compte réelle (équité live) qui n'existe pas ; la brancher
  aujourd'hui en obligatoire tuerait toute émission, et un compte inventé violerait la §3. Le
  pipeline live garde `LSR_CONTRACTS = 1` jusqu'à la tranche « source de compte ». Modif VIX
  du sizing (F3) = couche volatilité, également hors périmètre.
- **Vérif** : 14 tests TDD (preset, F1 structurel, deux frontières du buffer, 1/5e, floor
  strict, frontière exacte 1 contrat, dégradation monotone jusqu'à F8, corruption sans
  exception, pureté) — **470 passed**, ruff clean, `tsc` + `vite build` OK.

### /devil — gaps fatals, corruption d'état, plafond de plausibilité
Attaques sur `size_position` : **2 trous réels corrigés**, 2 comportements confirmés, 1 leçon
d'arithmétique flottante.
- **Gap d'ouverture fatal — DÉJÀ sûr, prouvé** : équité qui ouvre sous le plancher (jour neuf à
  47 000) ou déjà au-delà du DLL (gap à 48 800 sur day_start 50 000) → buffer ≤ 0 → F8
  instantané, aucun calcul de taille. Équité EXACTEMENT au plancher (buffer 0) → rejet aussi.
- **CORRIGÉ — grandeurs de compte nulles/négatives.** Équité/ouverture ≤ 0, DLL ≤ 0 passaient en
  `INSUFFICIENT_BUFFER` (issue sûre, raison mensongère) et surtout : **un `drawdown_floor`
  NÉGATIF (corrompu) ÉLARGISSAIT le buffer** — `to_floor = equity − (−500) = 50 500` → APPROVED
  sur un état corrompu, la corruption devenait du LEVIER. Désormais : toute grandeur de compte
  nulle/négative (floor < 0) → `INVALID_INPUT`.
- **CORRIGÉ — plafond de plausibilité `SIZE_SANITY_CAP`** (`RISK_MAX_CONTRACTS = 100`,
  v1 provisional, compte cible Apex 50K en micros). Une équité corrompue mais finie (10M) produit
  un buffer fini, un risque fini et un `floor()` de **400 000 contrats** — ticket parfaitement
  COHÉRENT pour la garde D-045 (elle vérifie l'ordre des niveaux, pas la vraisemblance d'une
  taille). Au-delà du plafond, la taille n'est pas un signal (§3).
- **Tick immense vs micro-buffer — DÉJÀ sûr, prouvé** : valeur de tick à 5 000 $ (erreur de
  config) → `floor()` = 0 → `INSUFFICIENT_BUFFER`, `contracts=None` — jamais un « ordre de
  0 contrat » qu'un courtier pourrait avaler.
- **Leçon flottante (documentée par test)** : à `1e308`, l'ABSORPTION fait s'effondrer la branche
  DLL (`1e308 − 1e9 == 1e308` → buffer 0) → le rejet arrive par `INSUFFICIENT_BUFFER` AVANT le
  plafond. Deux chemins, un même verdict fail-closed.
- **Invariant global balayé** (9 équités × 7 stops × 7 valeurs de tick, valides et corrompus) :
  `APPROVED ⟺ contracts entier ≥ 1` ; `REJECTED ⟺ contracts est None` ; **zéro exception** sur
  toute la grille.
- **Vérif** : 8 tests /devil (22 sizer) — **478 passed**, ruff clean, `tsc` OK.

### /polish tranche 1 — contrat écrit à jour
Le docstring du module était en retard d'une passe /devil (2 raisons de rejet citées sur 3) :
les trois chemins (`INSUFFICIENT_BUFFER`, `INVALID_INPUT` avec le piège du floor négatif,
`SIZE_SANITY_CAP`) et l'invariant `APPROVED ⟺ contrats ≥ 1` sont désormais le contrat écrit.
Aucun débris de debug. Tranche 1 scellée (DONE).

### Tranche 2 — Source de Compte & Câblage : la boucle compte → sizer → manifeste est fermée
`app/account_provider.py` (port + mock strict) + `size_plan` (risk_sizer) + injection engine.
- **Port `AccountDataProvider`** : `current(now) -> AccountState | None` — horloge INJECTÉE
  (règle commune D-045/046/047), le provider est seul juge de la fraîcheur de sa photo. `None`
  couvre TROIS réalités traitées pareil : jamais connecté, déconnecté, photo périmée
  (> `ACCOUNT_MAX_AGE_S` = 15 s, v1 provisional) — **une équité fossile n'est pas une équité**.
- **`MockAccountProvider` strict** : simule le flux NinjaTrader/broker — `push(state, ts)`
  (mise à jour d'équité datée), `disconnect()`, périmé → None. Le mode `always_fresh` est la
  couture du stack DÉMO uniquement (broker simulé qui répond toujours, câblé dans `main.py`
  avec l'Apex 50K jour neuf) ; un provider réel prend le même siège sans toucher l'engine.
- **`size_plan(plan, account)`** : le stop en ticks est dérivé de la GÉOMÉTRIE du plan
  (`|entrée − stop| / tick_size`) — une seule source de vérité, jamais un paramètre à part.
  Nouveau plan aux contrats remplacés (entrée jamais mutée) ; sizer en rejet, instrument hors
  specs, plan malformé → None.
- **Câblage `_maybe_emit_lsr` — « on ne trade jamais à l'aveugle »** : pas de provider, provider
  None, ou sizing rejeté → AUCUNE émission, silence (cohérent avec l'hygiène des logs D-046 :
  un rejet naturel ne logge rien). L'ancien `LSR_CONTRACTS = 1` ne sert plus au live : la taille
  vient du compte.
- **Prouvé en live (essai end-to-end rejoué)** : overlay armé par le backend avec
  **« MES 53 contrats »** — buffer 1 000 (DLL contraignant, jour neuf) → risque 200 $ → stop
  3 ticks × 1,25 = 3,75 $/contrat → floor(53,33) = 53 ; ACK journalisé (140 ms) ; dédup tenue ;
  la ligne INFO d'émission porte la taille dimensionnée.
- **Vérif** : 16 tests T2 (fraîcheur/déconnexion du provider, size_plan, 5 chemins de
  non-émission engine) + tests D-046 mis à niveau (un compte sain est désormais une PRÉCONDITION
  d'émission) — **494 passed**, ruff clean.

### /devil T2 — flapping, antidaté, chute en vol : 4 trous corrigés, 3 comportements confirmés
- **CORRIGÉ — ts daté du FUTUR** (désync d'horloge broker) : `now − ts` négatif → la photo
  restait « fraîche » indéfiniment. Son heure réelle est inconnue → None (même leçon que les
  prints D-046/le tape D-028).
- **CORRIGÉ — ts NON FINI** : `now − nan > max_age` est FAUX → une photo au ts NaN passait la
  garde de fraîcheur. Fraîcheur stricte : ts absent, non-fini, futur, ou trop vieux → None.
- **CORRIGÉ — provider qui LÈVE** (socket morte en pleine lecture) : le port dit « rendre None »
  mais un provider réel cassé peut lever — sans garde, `log.exception` à CHAQUE tick de flapping
  (violation de l'hygiène D-046) . Coupure = rejet naturel = silence (try/except → None,
  vérifié par caplog : 5 lectures levées → 0 record).
- **CORRIGÉ — mauvais type** (dict au lieu d'AccountState, provider bâclé) : AttributeError
  dans la boucle sweep → garde `isinstance` → silence.
- **Confirmés par test** : flapping ms (alternance connecté/déconnecté à chaque lecture) → zéro
  crash, émissions bornées à UNE par la dédup/F7 ; push antidaté (> ACCOUNT_MAX_AGE_S à
  l'arrivée) → mort-né, émission bloquée ; **chute d'équité EN VOL** (passage sous le DLL pile
  entre l'approbation d'evaluate_lsr et le sizing) → attrapée : la lecture du compte est APRÈS
  l'évaluation (une seule lecture, vérifiée — la photo la plus fraîche possible au moment de
  décider) → buffer mort → F8 in extremis, silence.
- **Risque résiduel assumé (tracé)** : une chute survenant APRÈS la lecture mais AVANT l'affichage
  (fenêtre de quelques ms) est indétectable par construction — les lignes suivantes sont le
  Go/No-Go humain et le DLL côté broker.
- **Vérif** : 7 tests /devil (23 provider/câblage) — **501 passed**, ruff clean.

### /polish final + Résumé de clôture D-047 (tranches 1 et 2 scellées)
Hygiène : zéro débris (TODO/FIXME/print), docstrings au niveau des passes /devil (fraîcheur
stricte du provider et couture `size_plan` désormais dans le contrat écrit).

**Attestation fail-closed — vérifiée par TEST, pas par déclaration :**
| Frontière | Chemin d'échec | Verdict |
|---|---|---|
| Provider absent/None/périmé/futur/NaN | pas d'émission | 5 tests |
| Provider qui LÈVE ou rend un mauvais type | silence, 0 log | 2 tests (caplog) |
| Buffer ≤ 0, gap d'ouverture, équité au plancher | `INSUFFICIENT_BUFFER` | 6 tests |
| Corruption (non-fini, ≤ 0, floor négatif, tick ≤ 0) | `INVALID_INPUT` | 5 tests |
| Taille implausible (équité corrompue finie) | `SIZE_SANITY_CAP` | 1 test |
| Chute d'équité en vol (sous DLL pendant l'évaluation) | F8 in extremis | 1 test |
| Invariant global (grille 9×7×7 valide+corrompu) | APPROVED ⟺ contrats ≥ 1, zéro exception | 1 balayage |

**Attestation de pureté mathématique — vérifiée par grep + test :** aucune horloge
(`time.time`/`datetime`/`perf_counter`) dans `risk_sizer.py`, `account_provider.py`,
`lsr_engine.py`, `trade_manifest.py` (grep = zéro occurrence) ; `now` TOUJOURS injecté ;
mêmes entrées → mêmes sorties (tests de pureté) ; entrées jamais mutées (testé sizer + plan).
Latence mesurée : `size_plan` **5,3 µs médian** (max 119 µs / 5 000 appels) — invisible sur la
cadence sweep, et hors hot path de toute façon.

**Chaîne complète au scellement** : microstructure → sweep (D-028) → evaluate_lsr (D-046) →
compte frais (provider) → RiskSizer 1/5e (D-047) → garde D-045 → SSE → overlay → ACK humain →
event store. Prouvée en live : « MES 53 contrats » dimensionné depuis le buffer Apex,
ACK 140 ms. Un seul mode dégradé subsiste, VOULU : sans source de compte, le terminal
n'émet AUCUNE proposition — on ne trade jamais à l'aveugle.

## D-048 · NT8FileAccountProvider — la source de compte RÉELLE (exports NinjaTrader)
`app/account_provider.py` (+ `NT8_ACCOUNT_FILE`/`NT8_ACCOUNT_POLL_SECONDS` en config, câblage
`main.py` avec start/stop propre au lifespan).

**Décisions de conception :**
- **Deux étages pour tenir deux contrats à la fois** : le port D-047 exige un `current(now)`
  SYNCHRONE (boucle sweep) et l'I/O ne doit JAMAIS geler l'event loop → une boucle de poll async
  exécute la lecture BLOQUANTE dans un thread (`asyncio.to_thread`) et alimente un cache
  `(AccountState, mtime)` ; `current(now)` applique la règle de fraîcheur D-047 sur ce cache.
  PROUVÉ par test : lecture bloquée 300 ms (façon antivirus/verrou Windows) → un ticker
  concurrent sur le même event loop continue de tourner (≥ 15 ticks pendant le blocage).
- **Horodatage = mtime du fichier**, pas le ts interne des lignes : même horloge que `now`
  (le FS du backend) → zéro dérive inter-machines, et si NT8 cesse d'écrire, le mtime fige et
  `ACCOUNT_MAX_AGE_S` périme le compte NATURELLEMENT. Un refresh raté ne ressuscite ni ne
  re-timbre le cache — il vieillit par son mtime d'origine (testé : rotation du fichier →
  cache mort à l'échéance, jamais ranimé).
- **Format v1 provisional** (convention côté exporteur NT8, un fichier/jour de session) :
  lignes `epoch;equity[;day_start]` appendées. Dernière ligne VALIDE gagne ; `day_start`
  explicite (3e champ) sinon déduit de la PREMIÈRE ligne valide ; floor/DLL du preset Apex
  (NT8 ne les connaît pas — le recalcul EOD reste au driver de fin de session).
- **TAIL-SAFETY — leçon du RED** : une écriture déchirée en plein vol (`49600.0` tronqué en
  `4`) parse comme une équité VALIDE de 4,0 $ — un float tronqué reste un float. Règle : seule
  une ligne TERMINÉE par `\n` compte ; la dernière ligne sans newline est l'écriture en cours,
  ignorée. Parsing tolérant ligne à ligne : garbage, `;;;`, nan/inf, équité ≤ 0 → ligne écartée.
- **FAIL-CLOSED I/O, silence ABSOLU (vérifié caplog)** : introuvable, verrouillé (répertoire à
  la place du fichier = même famille OSError qu'un verrou exclusif), vide, aucune ligne valide →
  None, **zéro ligne de log** — un échec d'I/O attendu est un rejet naturel (hygiène D-046).
  La boucle de poll ne logge que l'exception INATTENDUE (une panne doit se voir).
- **Prouvé en réel, chaîne complète** : scribe simulant NT8 (append `epoch;equity` chaque
  seconde), backend démarré avec `NT8_ACCOUNT_FILE` → overlay armé avec **« MES 26 contrats »**
  — dimensionné par l'équité DU FICHIER (49 500, day_start 50 000 déduit → buffer 500 →
  100 $ → floor(26,67) = 26), ACK journalisé 226 ms, dédup tenue, 0 erreur JS.
- **Vérif** : 12 tests (parsing nominal/déchiré/corrompu, day_start explicite et déduit, mtime
  périmé/vieillissant/jamais ressuscité, silence I/O caplog ×3, event loop jamais gelé,
  conformité au port via l'engine complet) — **513 passed**, ruff clean.

### /devil — rotation, mtime fantôme, floods, concurrence : lecture FENÊTRÉE
Le monstre de la passe était l'axe mémoire : **`readlines()` chargeait le fichier ENTIER à chaque
poll** — un flood de 10 Mo (ou 1 Go) mangeait la RAM et le CPU du worker toutes les secondes.
- **CORRIGÉ — lecture FENÊTRÉE, O(72 Ko) quel que soit le fichier** : tête bornée (8 Ko — le
  day_start vit dans les premières lignes) + queue bornée (64 Ko — la dernière ligne valide vit à
  la fin), balayage de la queue À REBOURS. En fenêtre décalée, le fragment INITIAL est écarté
  (potentiellement coupé en plein milieu de ligne) comme le fragment final (tail-safety).
  Mesuré : flood de 10 Mo sur une ligne → lecture < 0,5 s, équité de la queue, day_start de la
  tête. **Conséquence assumée et TESTÉE** : queue illisible (300 Ko de déchets en fin de gros
  fichier) → l'état RÉCENT est illisible → None — jamais une vieille équité du MILIEU repêchée
  comme récente.
- **CORRIGÉ — day_start indéterminable → None** : tête illisible SANS day_start explicite → un
  day_start inventé (= équité courante) simulerait un JOUR NEUF, le DLL repartirait plein — la
  corruption deviendrait du levier (la leçon D-047, encore). Un day_start EXPLICITE (3e champ)
  suffit même à tête illisible — recommandation exporteur : toujours l'écrire.
- **CORRIGÉ — BOM UTF-8** : sans strip, la PREMIÈRE ligne (celle du day_start déduit) était
  avalée → day_start faux. Le BOM est ignoré au parsing.
- **Confirmés par test** : troncature à 0 → cache intact qui VIEILLIT puis meurt, reprise
  automatique des écritures ; suppression ENTRE stat et open (course réelle, monkeypatch) →
  OSError attrapée, silence absolu ; **mtime dans le futur** → jamais « infiniment frais »
  (règle D-047 héritée) ; UTF-16 → déchets → None sans crash ; octets nuls → ligne écartée ;
  **écritures 100+/s pendant le poll** (thread concurrent, 400 appends) → zéro exception, chaque
  lecture rend une ligne COMPLÈTE réellement écrite, convergence sur la dernière.
- **Vérif** : 9 tests /devil (21 NT8) — **522 passed**, ruff clean.

### /polish + Résumé d'architecture D-048 (clôture)
Hygiène : zéro débris ; **UNE seule ligne de log dans tout le module** (l'exception inattendue de
la boucle de poll — une panne se voit, un rejet naturel jamais) ; contrat écrit au niveau des
passes /devil (lecture fenêtrée, fail-closed sur en-tête, tail-safety dans le docstring de classe).

**Les trois choix d'architecture qui portent le module :**
1. **I/O FENÊTRÉ, deux étages** — boucle de poll async → `asyncio.to_thread` → lecture bornée
   tête 8 Ko + queue 64 Ko (O(72 Ko)/poll quel que soit le fichier, queue balayée à rebours) →
   cache `(AccountState, mtime)` ; `current(now)` SYNC applique la fraîcheur D-047 sur le cache.
   L'event loop ne gèle jamais (prouvé : lecture bloquée 300 ms, ticker concurrent vivant), le
   port D-047 est inchangé, l'engine n'a pas bougé d'une ligne.
2. **FAIL-CLOSED SUR EN-TÊTE** — le day_start se déduit de la tête du fichier ; tête illisible
   sans day_start explicite → None (un day_start inventé = jour neuf simulé = DLL plein = la
   corruption devient du levier). Le mtime (horloge du FS backend, jamais le ts interne des
   lignes) fait vieillir le cache naturellement — un refresh raté ne le ressuscite jamais.
3. **TAIL-SAFETY** — seules les lignes TERMINÉES par `\n` comptent (une écriture en vol n'a pas
   son newline, et un float tronqué reste un float : « 49600.0 » déchiré en « 4 » = 4 $ valides) ;
   en fenêtre décalée, le fragment initial est écarté comme le final. Sous 400 appends
   concurrents : zéro exception, toujours une ligne complète réellement écrite.

Chaîne prouvée en réel de bout en bout : export NT8 simulé → provider fenêtré → RiskSizer →
manifeste « MES 26 contrats » dimensionné par l'équité DU FICHIER → overlay → ACK 226 ms.

## D-050 · MacroNewsProvider & Porte F0 — hard lock macro sur le calendrier économique
`app/macro_news.py` (+ config `MACRO_NEWS_*`/`NEWS_*`, champ `LsrInputs.news_state`, porte F0
en tête d'`evaluate_lsr`, câblage engine/main avec start/stop au lifespan).

**Décisions de conception :**
- **AMENDEMENT D-046 (isolation), tranché par le propriétaire de la spec** : l'isolation disait
  « aucune donnée news dans la couche LSR ». La Porte F0 la traverse — mais l'état news entre
  comme un **CHAMP D'ENTRÉE** (`news_state`), calculé par le provider et injecté par l'engine :
  `evaluate_lsr` reste PURE (zéro I/O, aucune horloge). La pureté est préservée, l'isolation
  stricte est amendée en connaissance de cause.
- **États et fenêtres** (config env, minutes) : WARNING = [T−15, T−2) — advisory, la porte
  laisse passer ; **HARD_LOCK = [T−2, T+2] bornes INCLUSES** (le doute penche vers le verrou) ;
  plusieurs événements → le plus sévère gagne. Cas exacts de la spec vérifiés : T−3m WARNING,
  T−1m/T+1m HARD_LOCK, T+3m NORMAL.
- **`SAFETY_UNKNOWN` bloque aussi** : cache jamais initialisé, FOSSILE (> `MACRO_NEWS_MAX_AGE_S`
  = 6 h, extension doctrine), au ts futur, ou provider qui LÈVE (garde engine) — couche câblée
  mais AVEUGLE = « on ne trade jamais à l'aveugle » (précédent D-047). Un calendrier fetché avec
  succès et VIDE est un état CONNU (semaine calme) → NORMAL, pas UNKNOWN. `news_state=None` =
  couche NON câblée (stack démo, `MACRO_NEWS_FEED_URL` vide) → la porte n'existe pas ; la
  protection de facto reste le couplage news du détecteur D-028 + le blackout humain Phase 0.
- **Parser Forex-Factory JSON pur et défensif** : USD × HIGH seulement (casse tolérée), entrée
  corrompue écartée LIGNE À LIGNE (non-dict, date illisible, date NAÏVE — fuseau inconnu §3,
  titre absent), flux illisible → None (l'appelant CONSERVE son ancien cache). Dates ISO avec
  offset → UTC.
- **Worker deux étages** (même architecture que D-048) : poll async 3600 s, fetch injectable
  (tests) ou urllib en `to_thread` (accepte `file://` — utile en local) ; `get_state(now)` SYNC
  et PUR, horloge injectée. Fetch raté/illisible → cache conservé, qui vieillit vers
  SAFETY_UNKNOWN par son `fetched_ts` d'origine (jamais re-timbré).
- **Leçon du harnais (2 itérations)** : mes tests timbraient le cache à `time.time()` réel puis
  évaluaient à un T0 du passé → la garde « cache du futur » rendait SAFETY_UNKNOWN. La garde
  avait raison, le harnais avait tort — cache timbré AVANT le plus ancien instant évalué.
- **Prouvé en réel (2 runs, feed `file://` local)** : MÊME setup microstructure parfait injecté —
  événement USD High à **T+60 s → 0 manifeste, 0 ligne de log** (F0 silencieuse) ; événement à
  **T+2 h → 1 manifeste émis** (53 contrats). La porte verrouille et déverrouille exactement.
- **Vérif** : 17 tests TDD (parser ×4, fenêtres exactes + bornes + sévérité + vide/unknown/
  fossile, worker ×3, F0 ×3 dont priorité absolue sur la microstructure, intégration engine
  lock/normal) — **539 passed**, ruff clean.

### /devil — fuseaux/DST, cascades, payloads empoisonnés, frontières à la seconde
**2 trous réels corrigés, 3 familles confirmées, 1 erreur d'arithmétique de harnais.**
- **CORRIGÉ — flux obèse = flux EMPOISONNÉ, jamais tronqué.** Un tableau de 50 000 entrées
  n'est pas un calendrier (le réel hebdo FF < 200) — et le TRONQUER serait PIRE que le rejeter :
  si l'événement imminent est au-delà de la coupe, la porte s'ouvrirait à tort. Au-delà de
  `_MAX_FEED_ENTRIES` (5 000) → rejet ENTIER, cache préservé, en temps borné (mesuré < 0,5 s,
  la longueur est testée AVANT d'itérer). `get_state` reste O(petit) : jamais 50 000 événements
  en cache.
- **CORRIGÉ — lecture du fetch BORNÉE** (`_MAX_FEED_BYTES` = 2 Mo, +1 pour détecter le
  dépassement) : une réponse de 500 Mo derrière un 200 ne mange plus la RAM du worker — elle
  décode tronquée, échoue au parse, cache conservé.
- **Fuseaux/DST — conversion UTC exacte À LA SECONDE, prouvée** : offset exotique +05:30
  (18:00 IST → 12:30 UTC, verrou à T−2:00 pile en UTC, WARNING une seconde avant) ; bascule
  DST américaine (le même 08:30 mural en −04:00 été et −05:00 hiver = deux instants UTC séparés
  d'exactement 1 h de plus que les 7 jours) ; suffixe `Z` accepté (py3.11).
- **Cascade 5 événements espacés de 2 min** : les fenêtres [Ti−2, Ti+2] se touchent bord à bord
  (bornes incluses) → **HARD_LOCK continu balayé À LA SECONDE** de T0−2:00 à T4+2:00, WARNING
  juste avant l'entrée, NORMAL juste après la sortie — zéro trou d'air. (Mon harnais s'était
  trompé de borne de sortie — T4+4 min au lieu de T4+2 min : le verrou était continu, le test
  avait tort.)
- **HTML derrière un 200** (page Cloudflare, 404 déguisé, « Bad Gateway ») : 4 pages rejetées
  d'affilée, le cache initial tient.
- **Frontière de déverrouillage à la MILLISECONDE** : T+2:00.000 verrou (borne incluse),
  T+2:00.001 libre ; symétrique à l'entrée.
- **Vérif** : 7 tests /devil (24 macro_news) — **546 passed**, ruff clean.

### /polish + Résumé de clôture D-050 (scellé)
- **PRINCIPE ENREGISTRÉ — « Un flux obèse est un flux empoisonné »** : max **5 000 entrées**
  (`_MAX_FEED_ENTRIES`, un calendrier hebdo réel < 200) et max **2 Mo** de lecture au fetch
  (`_MAX_FEED_BYTES`) → au-delà, **fail-closed par CONSERVATION DU CACHE** — jamais une
  troncature (si l'événement imminent est au-delà de la coupe, la porte s'ouvrirait à tort),
  jamais une explosion RAM/CPU, l'ancien calendrier vieillit honnêtement vers SAFETY_UNKNOWN.
- **VISIBILITÉ OPÉRATEUR (Zone 0)** — jamais un verrou invisible : `extras.news_state`
  (bloc fast du schéma, `get_state` pur et O(petit), dans le budget §7) → badge `NewsGateBadge`
  en Zone 0, icône + texte, jamais la couleur seule (§3) : `● F0 · RAS` (dim) /
  `⚠ F0 · NEWS ≤ 15 MIN` (jaune) / `⛔ F0 · NEWS LOCK` (rouge, gras) /
  `? F0 · CALENDRIER INCONNU` (stale). Tooltip actionnable sur chaque état. Couche non câblée
  (`news_state` null) → RIEN d'affiché — honnête : la porte n'existe pas. **Prouvé en live** :
  backend verrouillé (feed `file://`, événement T+60 s) → `⛔ F0 · NEWS LOCK` visible en Zone 0,
  0 erreur JS, capture à l'appui.
- **Chaîne de gates au scellement** : `F0 news → sweep D-028 → B1/B2/F4 → géométrie A1/A2/A3 →
  compte frais (D-047/048) → RiskSizer 1/5e + F8 → garde D-045 → SSE → overlay → humain`.
- **Vérif finale** : **547 passed**, ruff clean, `tsc` + `vite build` OK.

## D-051 · Zone C HUD — Compte & « distance vers la mort » (panneau C5)
Bloc `account_state` du ContextSchema (canal RAPIDE) + `account_view()` pur + panneau C5 +
`lib/account.ts` (dérivations d'affichage) + **Vitest/RTL** installé (nouvelle capacité de test).

**Décisions de conception :**
- **`buffer_initial` = le buffer À L'OUVERTURE du jour** (`min(day_start − floor, DLL)`) —
  dénominateur de la jauge. Ni une constante (fausse dès le 2e jour de campagne), ni le buffer
  courant (qui afficherait toujours 100 %) : une grandeur **pure et sans état**, recalculable à
  chaque tick depuis le seul `AccountState`. Aucun historique à mémoriser.
- **`is_stale` et `DISCONNECTED` sont le MÊME état, assumé** : le port D-047 rend `None` pour
  *périmé* **et** pour *déconnecté* — je n'ai pas inventé une distinction que le contrat ne porte
  pas. Un seul verdict honnête (« pas de vue exploitable ») → l'UI affiche
  **« ⛔ CONNECTIVITÉ NT8 REQUISE »** avec un message actionnable, et **aucune grandeur**.
- **Ticket de référence pré-calculé** (`RISK_REFERENCE_STOP_TICKS = 3`, géométrie LSR typique
  sur MES) : l'opérateur voit sa capacité **avant** qu'une alerte tombe. `contracts` n'existe
  que sur APPROVED ; sinon un **badge de rejet explicite** (MARGE INSUFFISANTE / DONNÉES COMPTE
  INVALIDES / TAILLE INVRAISEMBLABLE) — jamais un « 0 contrat » qu'on pourrait lire comme valide.
- **Paliers de la jauge** (spec) : > 60 % `MARGE SAINE` · 30–60 % `MARGE RÉDUITE` · < 30 %
  `MARGE CRITIQUE` (clignotant) · **buffer ≤ 0 → la barre est REMPLACÉE** par
  `⛔ BLOQUÉ · MARGE ÉPUISÉE` (une barre à 0 % se confondrait avec « critique »). Bornes : 60 %
  et 30 % pile appartiennent au palier le PLUS PRUDENT (le doute penche vers la prudence, comme
  les bornes de verrou D-050).
- **§3 — jamais la couleur seule** : chaque palier porte un LIBELLÉ TEXTE + une ICÔNE, et les
  libellés sont deux à deux distincts (testé) ; le P&L porte une flèche ▲/▼ en plus de sa
  couleur ; les grandeurs absentes s'affichent en tiret neutre `·`.
- **`account_view` est PURE** (aucune horloge, aucune mutation, O(1)) : publiée à chaque tick
  fast sans coût mesurable. Une grandeur non finie n'est JAMAIS affichée (None), même si le
  reste de l'état est lisible.
- **DÉFAUT RÉEL trouvé par l'essai manuel, invisible aux tests** : le bloc arrivait bien en SSE
  (`APPROVED`, équité 50 000) mais **`account_state` manquait dans `FAST_BLOCKS` de `sse.ts`** —
  un event non écouté est silencieusement perdu, et le panneau fail-closait comme si la donnée
  n'existait pas. Les tests Vitest écrivent le store directement, le test backend vérifie le
  broadcaster : **aucun des deux ne pouvait voir le trou**. Corrigé + commentaire d'avertissement
  sur la liste. C'est exactement la raison d'être de l'essai manuel dans la Definition of Done.
- **Vérif** : **12 tests pytest** (`account_view` : nominal, buffer_initial contraint par le
  floor, 4 statuts de rejet, non-finies, DISCONNECTED, pureté, publication SSE) + **28 tests
  Vitest/RTL** (15 logique pure : ratio borné/null, paliers et bornes, §3 libellés distincts,
  formatage ; 13 composant : équité, P&L fléché, 4 états de jauge, singulier/pluriel, 3 badges
  de rejet, 3 chemins fail-closed) — **559 passed** backend, ruff clean, `tsc` + `vite build` OK.
  **Essai réel 4 états** (live 50 000/100 %/53 contrats, critique 18 % clignotant, buffer mort
  BLOQUÉ + rejet, déconnecté sans valeurs), **0 erreur JS**, captures à l'appui.
- **Placement** : C5 en tête de la colonne C de l'espace DÉFAUT et de l'espace DISCIPLINE — la
  survie du compte se lit avant tout le reste.

### /devil — payloads contradictoires, jauge indéterminable, débordements, flapping
**3 défauts réels corrigés, 2 comportements confirmés, 1 mesure de test corrigée.**
- **CORRIGÉ — le plus grave : un payload CONTRADICTOIRE affichait une taille REFUSÉE.** Le
  composant ne regardait que `contracts` : `{contracts: 26, status: INSUFFICIENT_BUFFER}` montrait
  « 26 contrats » alors que le RiskSizer avait rejeté — le pire mensonge possible sur ce panneau.
  Nouvelle garde pure `ticketDisplay()` : la taille n'est affichable QUE si **les deux** statuts
  (bloc ET ticket) valent APPROVED **et** que les contrats sont un entier > 0 ; sinon badge de
  rejet, et `INDÉTERMINÉ` quand la cause est inconnue (ticket absent, contrats fractionnaires,
  0, négatifs, non finis). Un statut inconnu du backend est affiché TEL QUEL, jamais masqué.
- **CORRIGÉ — une jauge indéterminable rendait une barre PLEINE (grise)**, lisible comme « 100 %
  de marge ». Remplacée par un bandeau `? MARGE INDÉTERMINABLE` : on affiche l'ignorance en
  toutes lettres (§3), jamais une barre qui rassure à tort.
- **CORRIGÉ — débordements aux valeurs à 9-10 chiffres** : formatage compacté au-delà du million
  (`1.00 G`, `−50.0 M` — compacter plutôt que tronquer : « 1,000,00… » serait un mensonge) +
  `min-w-0`/`truncate`/`shrink-0` sur toutes les lignes en flex. Et un défaut de CONFINEMENT
  dans le composant `Panel` PARTAGÉ : le groupe de droite de l'entête est `shrink-0`, donc un
  slot `right` long (le badge NT8 de C5) débordait de l'entête en colonne étroite et pouvait
  empiéter sur le voisin → `overflow-hidden` sur l'entête (confinement pur, aucun effet quand la
  place existe ; bénéficie à tous les panneaux).
- **`buffer > buffer_initial` est LÉGITIME, pas une corruption** — insight de la passe : une
  journée PROFITABLE augmente le buffer au-delà de son ouverture (équité 50 600 → buffer 1 600
  vs 1 000 à l'ouverture). Le bornage à 100 % est donc un choix d'AFFICHAGE (le P&L du jour
  porte déjà l'information de surplus), pas une garde anti-corruption. Un `buffer_initial`
  négatif, lui, est bien une corruption → indéterminable.
- **Flapping confirmé propre** : 30 bascules frais ↔ déconnecté à 10 Hz → **une seule hauteur de
  panneau** (222 px, aucun saut de layout), état final stable, **0 erreur JS**.
- **Débordements mesurés à 3 largeurs** (900/700/520 px de viewport, panneau jusqu'à ~137 px) :
  **0 débordement visible**. Correction de méthode : mon détecteur comptait d'abord les éléments
  TRONQUÉS comme des débordements — or `truncate` EST la correction (contenu clippé, pas
  répandu) ; seul un `overflow-x: visible` qui dépasse est un défaut.
- **Vérif** : 8 tests /devil en logique pure + 7 en RTL (**46 tests Vitest** au total) —
  **559 passed** backend, ruff clean, `tsc` + `vite build` OK ; essai visuel 3 axes, 0 erreur JS.

### /polish + clôture D-051 (scellé)
- **DÉFAUT de découvrabilité corrigé** : C5 était absent de la **CommandBar** — un opérateur qui
  tape `/` ne pouvait pas le trouver (le panneau n'existait que pour qui connaît déjà sa place).
  Ajouté à la liste des panneaux : `/` → `C5` propose « panneau C5 (zone C) » et focalise la
  zone C (vérifié en essai réel).
- **Latence perçue vérifiée** : le panneau suit le canal fast, l'équité est présente à chaque
  lecture (6 relevés à 300 ms) — aucune fenêtre de vide entre deux ticks.
- **Découvrabilité INTERNE au panneau** : la règle du 1/5e est expliquée à l'écran
  (« risque 100 $ (1/5) ») et le stop de référence est nommé (« stop réf. 3 ticks MES ») — le
  chiffre affiché est auditable par l'opérateur sans documentation.
- Hygiène : aucun débris (TODO/FIXME/console), `STATUS_LABEL` désormais encapsulé dans
  `ticketDisplay()` (le composant ne fait plus de logique de statut).
- **Vérif finale** : **46 Vitest** + **559 pytest**, ruff clean, `tsc` + `vite build` OK, essai
  réel (découvrabilité + suivi live), 0 erreur JS.

## D-052 · LsrLiveDriver — port Python durci du harnais push-driven
`backend/app/lsr_driver.py` — port du `LsrLiveDriver` TypeScript (moteur LSR v1.2, externe),
**durci par la revue de son original**. Il n'exécute rien et n'émet rien : il cadence une
fonction d'évaluation INJECTÉE sur des snapshots poussés et remet le résultat à des callbacks.

**PÉRIMÈTRE — pas câblé, et c'est délibéré.** Le chemin d'émission LIVE reste
`Engine._maybe_emit_lsr` (D-046), qui TIRE la microstructure du ContextSchema sur la cadence
sweep. Ce driver est l'autre modèle (on POUSSE des snapshots d'un flux temps réel Rithmic/NT8) :
il est fourni comme harnais pour ce jour-là. **Les deux ne doivent jamais tourner ensemble** —
deux chemins d'émission concurrents casseraient la source unique de vérité. Absent de `main.py`.

**Les cinq correctifs par rapport à l'original TypeScript :**
1. **La boucle « fail-safe » était en réalité fail-OPEN.** L'original gardait les snapshots
   indéfiniment : un feed mort le laissait réévaluer toutes les 250 ms sur des données
   FOSSILES — et avec un `now` frais, le moteur ne pouvait pas voir la différence. Ici chaque
   injection est ESTAMPILLÉE : marché ou compte périmé (ou daté du FUTUR, leçon D-050) → aucune
   évaluation ; order flow périmé → passé à `None` (mesure absente = fail-closed côté gates
   B1-B4 : c'est au moteur de refuser, pas au driver de relayer un fossile). Seuils :
   `LSR_DRIVER_MAX_AGE_S` (2 s, marché/flux) et `ACCOUNT_MAX_AGE_S` (15 s, doctrine D-047 réutilisée).
2. **Callbacks BORNÉS.** L'original appelait `onStateUpdated?.(...)` sans `await` ni `.catch`
   alors que le type autorise `Promise<void>` : un rejet devenait une *unhandled rejection*,
   fatale sous Node ≥ 15 — un Redis qui hoquette tuait le driver. Ici tout callback (sync ou
   coroutine) est awaité sous `try/except` : la boucle survit, l'échec est JOURNALISÉ (échec
   inattendu ≠ rejet naturel, hygiène D-046).
3. **Persistance AVANT avancement.** L'original faisait `this.runtimeState = nextState` puis
   lançait la persistance : une écriture ratée laissait la mémoire en avance sur le durable et
   le redémarrage repartait d'un état faux. Ici, persistance en échec → **l'état n'avance pas** ;
   le moteur étant déterministe, l'évaluation suivante recalcule le même état et réessaie
   (convergence sans file de retry — testé).
4. **Comparaison d'état STRUCTURELLE** (`!=`) au lieu de `JSON.stringify` ×2 par évaluation :
   exacte, **insensible à l'ordre des clés** (l'original déclenchait une FAUSSE mutation sur un
   simple changement d'ordre d'insertion — testé), sans allocation.
5. **APPROVED et ALERT sur DEUX callbacks distincts.** L'original les faisait sortir par le même
   `onPlanGenerated` : un `onPlanGenerated: p => broker.submit(...)` exécutait donc sur une
   simple ALERTE. Deux callbacks rendent l'erreur IMPOSSIBLE, pas seulement documentée.

**Aussi** : `start()` idempotent (l'original écrasait `this.timer`, fuyant le premier) ;
l'évaluation n'est plus déclenchée par CHAQUE injection mais par la cadence — backpressure : une
évaluation par tick est inutile (le détecteur de sweep tourne à la seconde) et non bornée ;
horloge INJECTABLE (le driver est le seul propriétaire d'horloge, et même là c'est contrôlable en
test) ; `record_trade_outcome(won, ts)` EXIGE l'horodatage, là où le défaut `Date.now()` de
l'original rendait les tests non déterministes. §2.1 : aucun ordre, la responsabilité courtier
reste hors du module comme dans l'original.

- **Leçon de mesure (mon erreur, corrigée)** : mon premier essai a compté « 33 évaluations
  pendant la coupure » et conclu à un échec. En recomptant : 7 + 33 = 40 évaluations × 50 ms =
  **exactement 2,0 s**, soit le seuil. La garde avait mordu au bon moment ; c'est l'assertion qui
  était fausse (je traitais toute la fenêtre de 3 s comme « périmée », alors que la donnée reste
  légitimement fraîche pendant ses 2 premières secondes). Essai corrigé pour mesurer la fenêtre
  POST-seuil : **0 évaluation**, reprise automatique au retour du feed.
- **Vérif** : 22 tests (péremption ×6 dont futur et horloge non finie, séparation APPROVED/ALERT,
  persistance ratée sans divergence + convergence à la reprise, ordre des clés, callbacks
  sync/async qui lèvent, évaluateur qui lève, `start()` idempotent, survie de la boucle,
  horloge injectée, horodatage obligatoire) — **581 passed**, ruff clean ; essai manuel sur vraie
  boucle asyncio avec le VRAI `evaluate_lsr`.

### /devil (Loop 4) — six failles trouvées dans mon propre port
Les cinq correctifs ci-dessus visaient l'original TS. Cette passe attaque **ma** version. Les six
tests ont d'abord été prouvés ROUGES sur le driver d'avant (relance ciblée sur le code stashé).

- **A. Écriture perdue → cooldown F6 effacé (la plus grave, fail-OPEN).** `evaluate` et
  `record_trade_outcome` faisaient tous deux un read-modify-write de `_state` avec un `await`
  (persistance) AU MILIEU. Une perte enregistrée pendant qu'une évaluation attendait Redis était
  **écrasée** par l'état calculé avant la perte : cooldown anti-revanche effacé, on retrade
  immédiatement après une perte — exactement le biais que D-035 mesure. Correctif : un **verrou
  unique** sérialise le cycle d'état. Asymétrie assumée — une évaluation concurrente est
  **droppée** (une en vol suffit ; deux émettraient deux fois le même ticket → strict drop D-045
  T3, sans log car c'est un rejet naturel), une issue de trade **attend son tour** : on ne perd
  jamais un cooldown. Le drop-plutôt-qu'attendre supprime aussi la fenêtre de péremption (on
  n'évalue jamais sur une fraîcheur vérifiée avant une attente).
- **B. Un callback qui ne rend JAMAIS la main pendait la boucle.** Le correctif 2 bornait les
  callbacks qui *lèvent*, pas ceux qui ne reviennent pas (socket Redis suspendue sans timeout
  client) : zéro évaluation, zéro log — **un driver mort ressemble à un driver calme**.
  `LSR_DRIVER_CALLBACK_TIMEOUT_S` (2 s) le traite en ÉCHEC visible → l'état n'avance pas, la
  tentative suivante réécrit. Résiduel assumé et mesuré : pendant la panne, la cadence tombe au
  plafond (une évaluation par timeout au lieu de 4/s) — dégradée, pas morte. Un callback
  **synchrone** bloquant (`time.sleep`) reste indéfendable : il gèle la boucle avant tout point
  d'attente. C'est un contrat de consommateur, pas un défaut du driver.
- **C. Pas d'état durable → pas d'émission.** Le correctif 3 empêchait la mémoire d'avancer sans
  le durable, mais **le plan sortait quand même**. Au redémarrage, l'état revenu en arrière
  laissait le même sweep ré-émettre → doublon de ticket. L'émission est désormais conditionnée à
  la cohérence de l'état (même doctrine que le journal D-045 : l'enregistrement précède l'acte).
- **D. Comparaison d'état qui LÈVE.** `next_state != self._state` n'est pas toujours booléen : un
  `ndarray` dans l'état lève « truth value of an array is ambiguous », et l'exception remontait à
  l'appelant hors de la boucle — contrat « ne lève jamais » rompu. Capturée : incomparable = non
  avancé = aucune émission. *Risque résiduel tracé* : un état portant un NaN **reconstruit** à
  chaque tick comparerait toujours inégal → une écriture durable par tick. Non détectable sans
  introspection profonde de l'état ; le contrat du moteur LSR est un état de compteurs et
  d'horodatages FINIS (`record_trade_outcome` refuse déjà un `ts` non fini).
- **E. Boucle tuée de l'extérieur.** `if self._task is not None: return` rendait `start()`
  idempotent *et impuissant* : après une annulation externe (arrêt d'un TaskGroup, balayage de
  shutdown) la tâche est `done()` mais non-None → le driver restait **mort en silence**. Une
  boucle morte se signale (WARNING avec la cause, lue sans lever) et se relance. Symétriquement,
  `stop()` ne propage plus l'exception d'une tâche déjà morte (`await task` la re-lève) : un arrêt
  gracieux n'explose plus au pire moment (RUNTIME_LOOPS §arrêt).
- **F. Horloge qui RECULE.** Un pas NTP arrière fait paraître tous les snapshots « datés du
  futur » : le driver se tait — correct (§3) — mais **indéfiniment et sans trace**. La régression
  ne bloque rien par elle-même (c'est la fraîcheur qui décide) ; elle est signalée **une fois par
  épisode**, reprise incluse : à 4 ticks/s, un log par tick serait un flood (hygiène D-046).
- **Ré-entrance (contrat documenté)** : un callback ne pilote pas le driver. `evaluate_now()`
  depuis un callback est droppé sans dommage (verrou tenu) ; `await record_trade_outcome(...)`
  s'auto-bloquerait — le plafond B le convertit en échec journalisé plutôt qu'en pendaison.
- **Vérif /devil** : +8 tests (écrasement du cooldown, drop de l'évaluation concurrente, callback
  pendu borné, émission refusée sans état durable, état incomparable, relance d'une boucle morte,
  `stop()` sur tâche morte, horloge qui recule) — **589 passed**, ruff clean. Essai réel sur
  boucle asyncio, horloge maîtrisée et persistance pathologique : sweep unique → 1 ticket et
  **0 log** (rejets naturels muets) ; perte pendant une persistance lente → `cooldown_until`
  conservé, **0 ticket sur un sweep NEUF** pendant la fenêtre, émission au-delà ; persistance
  pendue → **3 évaluations** (boucle vivante), 0 ticket, 2 timeouts journalisés, ticket émis au
  retour ; annulation externe → relance + signalement ; horloge −30 s → **1 alerte** (pas ~15) et
  1 reprise ; arrêt propre. **6 logs pour toute la session** — chacun une anomalie réelle.

### /polish (Loop 5) — dont une faille que le correctif /devil avait lui-même ouverte
- **`asyncio.wait_for` AVALE une annulation externe (3.11) — l'arrêt du terminal restait pendu.**
  Le plafond de callback (faille B) reposait sur `wait_for` ; or son code 3.11 fait
  `except CancelledError: if fut.done(): return fut.result()` — si la future interne vient de se
  terminer, l'annulation venue de l'extérieur est **consommée sans être relayée**. La boucle
  survivait donc à son propre `cancel()` et `stop()` attendait pour toujours. **Trouvé par l'essai
  réel, pas par un test** : l'essai calait une fois sur deux ; le dump de piles a montré la tâche
  vivante à `_poll_loop` avec `cancelling=1` — elle avait encaissé son annulation. Remplacé par
  `asyncio.timeout` (3.11+), qui distingue sa propre échéance d'une annulation externe. Test de
  course sur 30 arrêts déphasés : rouge dès la 1re itération avant, vert 3 fois sur 3 après.
- **`stop()` ne confisque plus l'annulation de l'appelant.** `except CancelledError: pass`
  avalait aussi le cas « c'est MOI qu'on annule » : pendant un shutdown, `await driver.stop()`
  rendait la main normalement et la séquence d'arrêt continuait comme si rien ne s'était passé
  (Loop H). Discriminé par `current_task().cancelling()`.
- **`stop()` depuis un callback** (« coupe tout ») : s'attendre soi-même lève « Task cannot await
  on itself ». L'annulation est posée, on ne s'attend pas.
- **Cadence à l'ÉCHÉANCE.** « Travail puis sieste fixe » donne une période réelle de
  `poll + travail` : la cadence annoncée (250 ms) devenait un mensonge silencieux. La boucle vise
  une échéance sur l'horloge **monotone** de l'event loop (pas l'horloge injectée, qui est murale
  et peut faire un pas NTP), **sans rattrapage** — une rafale de rattrapage évaluerait le passé.
  Mesuré dans le régime discriminant (travail ≈ période, persistance réelle à chaque tick) :
  **27 évaluations en 0,60 s**, plafond d'une par période = 30 jamais dépassé ; « sieste fixe »
  aurait plafonné à 15. *Erreur de mesure corrigée en route* : ma première version mesurait sans
  changement d'état — la persistance n'était donc appelée qu'une fois et la comparaison annoncée
  était fausse.
- **Logs actionnables** : `_safe_call` nomme le callback fautif (`persist_state`,
  `on_plan_approved`…). « La persistance a lâché » et « le ticket n'est pas parti » n'appellent pas
  la même intervention ; un log qui ne dit pas lequel oblige à deviner.
- **Découvrabilité** : `RUNTIME_LOOPS.md` §Loop D liste désormais les **instances réelles** de
  boucle de données du dépôt (engine, NT8, macro, driver LSR) avec leur cadence et leurs parades —
  une boucle absente de ce document est invisible pour `/loop-check`.
- **Cadence bornée une seule fois** (`__init__`) : une valeur de config absurde ne peut plus
  devenir un busy-wait.
- **Résiduel assumé** : `stop()` attend la boucle **sans plafond**. Les callbacks étant désormais
  bornés en durée, seule une coroutine qui *avale* `CancelledError` peut pendre l'arrêt — et
  plafonner ici laisserait vivre une tâche qui émet encore, ce qui est bien pire qu'un arrêt lent.
- **Vérif /polish** : +2 tests d'arrêt (course sur 30 arrêts, annulation de l'appelant) et
  +2 tests (cadence à l'échéance — prouvé discriminant : 8 évaluations en « sieste fixe » contre
  14 attendues —, `stop()` depuis un callback) → **593 passed**, ruff clean, essai réel relancé
  **5 fois de suite sans blocage** (avant : ~1 sur 2).

## D-053 · SENT & YLD — positionnement Long/Short et courbe des taux
Deux panneaux demandés (`LsrSentimentPanel`, `YieldDifferentialsPanel`). **Ils ne pouvaient pas
exister seuls** : CLAUDE §1 interdit un panneau non traçable à un champ du schéma, or ni le ratio
Long/Short ni les taux bruts n'existaient — et il n'y a **aucun fetcher de taux** dans le dépôt
(le seul fetcher est celui du calendrier macro D-050 ; `cascade.real_rates` est un niveau
composite unique, pas une courbe). Livré en **tranches verticales** : bloc de schéma +
alimentation + panneau, chacune traçable.

**Collision d'acronyme tranchée.** Dans ce terminal, « LSR » désigne le moteur **Liquidity Sweep
Reversal** (`lsr_engine`, `lsr_driver`, logs « LSR manifest émis »). Le fichier garde le nom
demandé `LsrSentimentPanel.tsx`, mais le mnémonique opérateur est **SENT** : surcharger LSR avec
« Long/Short Ratio » dans la même UI serait un piège de lecture en séance.

### Tranche 1 — `long_short_ratio` (canal LENT) → panneau SENT
- **Aucun signal dérivé** (§2.1) : le module normalise, il ne conclut pas. Pas de lecture
  contrarienne, pas de pondération — ce serait de la logique métier inventée (§11).
- **Refus assumés** (`app/sentiment.py`, pur — zéro horloge, zéro I/O) : somme ≠ 100 % (la venue a
  perdu une catégorie — afficher la jauge reviendrait à **inventer la part manquante**), doublon
  contradictoire (la 1re gagne, l'écart est compté), symbole vide, valeur non finie ou hors
  bornes. **Rien d'exploitable → `None` → bloc ABSENT**, jamais un objet vide qui se lit
  « connecté ». Flux obèse refusé EN ENTIER (doctrine D-050 : tronquer masquerait des
  instruments sans le dire).
- **Short à 0** : la ligne SURVIT (les pourcentages sont une donnée réelle), le ratio est retiré —
  jamais « ∞ » ni un nombre géant qui a l'air d'une mesure.
- **`dropped` affiché** : une ligne écartée par le moteur se VOIT à l'écran. Une donnée perdue en
  silence est un mensonge par omission.
- **§3 dans la jauge** : LONG à gauche / SHORT à droite, pourcentages ÉCRITS, libellés, flèches
  ▲/▼ sur la variation, badge texte DÉSÉQUILIBRE, libellé ARIA complet. La lecture ne dépend
  jamais de la seule couleur.

### Tranche 2 — `yield_curve` (canal LENT) → panneau YLD
- **Un spread ne se calcule jamais à partir d'un trou.** Un ténor absent/non fini fait disparaître
  *tous* les spreads qui en dépendent — et seulement ceux-là. Un différentiel affiché sur une patte
  manquante serait un chiffre inventé **qui a l'air d'une mesure** : la pire forme de mensonge dans
  un terminal. L'UI le dit franchement (« AUCUN DIFFÉRENTIEL CALCULABLE ») au lieu d'un blanc.
- **Spreads DÉRIVÉS, jamais alimentés** : les recevoir d'une source indépendante ouvrirait la
  porte à un différentiel qui contredit les taux affichés juste au-dessus. Source unique.
- **`inverted` seulement sur une PENTE** (deux ténors de la même courbe). Un différentiel
  transatlantique négatif n'est pas une « inversion » — l'étiquette serait un contresens. Et
  l'inversion est marquée comme un FAIT, pas comme une prévision de récession (§2.1).
- **Bornes de plausibilité [−5 %, +25 %]** : un taux à 900 % est une erreur d'unité, pas un régime.
  La borne écarte l'absurde **sans écarter l'inhabituel** — un Bund à −0,55 % est réel et passe.
- **0 bp ≠ absence** : « inchangé » est une information, l'absence de mesure n'en est pas une →
  tiret, jamais un zéro.
- Ténors : US02Y, US10Y, DE02Y, DE10Y. Spreads : pente US 10a−2a et différentiel US−DE 10a (le
  driver du couple EUR/USD, domaine Youssef).

- **Alimentation = le mock, et c'est explicite.** Les deux blocs sont nourris par `MockDataSource`
  (§4 : couture unique, mock volontairement SALE — doublon, catégorie perdue, patte de courbe
  manquante ou NaN injectés). **Aucun fetcher réseau n'a été inventé** : sans source, URL ni
  contrat choisis, le construire aurait été de la spéculation. La couture est prête — un
  `RatesProvider` façon D-050 (worker async + cache + `get_state` pur) se branche à la place du
  mock sans toucher aux panneaux. C'est la tranche suivante, à ouvrir quand la source est décidée.
- **Persistance des layouts bumpée v13** : sans ça, les espaces déjà persistés n'auraient JAMAIS
  affiché les nouveaux panneaux — une feature livrée morte (précédent v12/D-041).
- **Vérif** : 15 + 16 tests unitaires backend, 6 d'intégration (dont « aucun spread ne survit sans
  ses deux pattes » sur le flux réel), 15 + 14 tests RTL. **630 passed**, ruff clean, tsc + vite
  build verts, 75 tests Vitest (4 fichiers). Essai navigateur sur l'app réelle : blocs reçus sur le canal lent,
  panneaux rendus (pente INVERSÉE −23,5 bp, différentiel +169,1 bp), **aucun débordement**.
### /devil (Loop 4) — la jauge mentait sur l'extrême
- **Géométrie faussée par ses propres libellés (mesuré, pas supposé).** Les pourcentages étaient
  écrits DANS les bandes de la jauge ; la largeur minimale du texte imposait un plancher à chaque
  côté. Mesure au navigateur : pour une donnée à **100 / 0**, la jauge affichait **93,7 %** de
  long — une bande rouge représentant **0 %** occupait 6,3 % de la largeur. À 98/2, 93,7 % encore.
  Une jauge quantitative qui déforme l'extrême ment exactement là où elle sert (c'est le
  positionnement extrême qu'on regarde). Correctif : **la géométrie ne porte plus aucun texte**,
  les deux largeurs viennent directement de la donnée, les chiffres vivent à côté (§3 préservé :
  ils restent toujours écrits). Re-mesuré : **100,0 / 98,0 / 90,0 / 50,0 — écart 0,0 pt** sur les
  quatre cas. Défaut INVISIBLE en test unitaire : jsdom ne calcule pas de layout, seul le vrai
  navigateur pouvait le voir (même leçon que D-051).
- **Ordre d'affichage instable.** Les lignes suivaient l'ordre du flux : une venue qui réordonne
  ses instruments à chaque rafraîchissement les ferait SAUTER d'un tick à l'autre, impossible de
  verrouiller l'œil sur une ligne en séance. Tri déterministe par symbole, appliqué **après** la
  déduplication : il change l'affichage, jamais quelle ligne gagne.
- **Pedigree invisible.** Les drapeaux de pathologie (`LATE_FEED`, `CLOCK_DESYNC`) n'étaient
  rendus que dans le bandeau STALE : un bloc **FRESH mais horodaté de travers avait l'air
  impeccable**. Ils sont désormais dans l'entête des deux panneaux, quelle que soit la fraîcheur.
  YLD n'affichait par ailleurs **aucune source** — ajoutée.
- **Risque RÉSIDUEL assumé et tracé : l'erreur d'unité fractionnaire.** Un flux qui envoie
  `0.0405` (fraction) au lieu de `4.05` (%) passe toutes les bornes de plausibilité et s'affiche
  « 0,041 % · pente −0,2 bp » — plausible et faux d'un facteur 100. **Indécidable depuis la donnée
  seule** : un monde de taux quasi nuls a réellement existé, et un badge « unité douteuse » posé
  sur une vraie courbe ZIRP serait lui-même un mensonge. Mitigations retenues : contrat d'unité
  explicite dans le schéma (`value_pct` = pourcent), conversion confinée au provider (un seul
  endroit), et **source affichée** pour que l'opérateur puisse trancher. Vérifié à l'écran.
- **Clignotement du différentiel : comportement VOULU, mesuré.** Le mock retire une patte de
  courbe avec une probabilité `drop_p × 2` — 2 % des ticks lents en scénario calme (≈ 1 fois
  toutes les 12 min), 30 % en `vix_spike` (≈ toutes les 45 s). Le panneau bascule alors sur
  « AUCUN DIFFÉRENTIEL CALCULABLE ». C'est la vérité du flux : afficher la dernière valeur connue
  pour « stabiliser » l'affichage masquerait un feed cassé — précisément l'inverse de §3.
- **Vérif /devil** : +8 tests RTL (géométrie exacte, bande de 0 % strictement invisible, aucun
  texte dans les bandes, chiffres lisibles hors jauge, drapeaux en FRESH, venue, source) et
  +2 backend (ordre déterministe, le tri ne renverse pas la déduplication) → **632 passed**,
  ruff clean, **83 tests Vitest**, tsc + vite build verts. Deux hooks DEV (`__setLongShort`,
  `__setYields`) ajoutés pour forcer les positions extrêmes, invisibles en démo.

### /polish (Loop 5) — dire « attends » plutôt que « débogue »
- **« PAS DE DONNÉES » était exact mais trompeur à l'ouverture.** Le canal lent tourne à 15 s : un
  panneau qui en dépend affiche son écran vide pendant un tick entier, avec le MÊME message qu'un
  flux réellement mort. L'opérateur ne peut pas distinguer « attendre » de « déboguer ». Tant
  qu'aucun événement lent n'est arrivé (`useSlowChannelPending`), les deux panneaux disent
  **EN ATTENTE DU CANAL LENT · premier envoi sous 15 s** ; ensuite seulement, l'absence redevient
  une absence. Aucune valeur inventée, aucun état dur masqué (§3) — seule la CAUSE affichée devient
  juste. *Portée réelle mesurée* : le cache de rejeu SSE hydrate un nouvel abonné immédiatement,
  donc la fenêtre est courte en pratique ; elle reste entière au démarrage à froid du backend,
  exactement quand l'opérateur ouvre le terminal.
- **Vocabulaire de l'absence unifié.** Le panneau SENT mélangeait trois notations : « PAS DE
  DONNÉES » (bloc entier), « — » (sous-valeur) et « N/D » (ratio) — cette dernière unique dans tout
  le dépôt. Ramené à deux formes, avec l'explication en infobulle (« plus personne n'est short »)
  plutôt qu'un sigle de plus à apprendre.
- **Typographie des unités** : `−23,5bp` → `−23,5 bp` (espace insécable : l'unité ne quitte jamais
  son nombre en colonne étroite).
- **Vérifié à l'écran, pas déduit** : libellés `LONG 100,0` / `97,6 SHORT` — **aucun débordement**
  de boîte ; géométrie re-mesurée sur position extrême (100,0 % et 2,4 %) ; drapeau `LATE_FEED`
  visible dans l'entête d'un bloc FRESH ; aucun panneau ne déborde horizontalement.
- **Vérif /polish** : +2 tests RTL (attente distinguée de l'absence, sur les deux panneaux),
  assertions d'absence rendues explicites (canal vivant vs canal muet) → **85 tests Vitest**,
  632 backend, ruff clean, tsc + vite build verts.

- **Défaut PRÉ-EXISTANT trouvé au passage, hors périmètre** : avec une projection REST tronquée
  (ce que renvoie un backend qui redémarre), `CalibrationPanel` et `DecisionBlotter` **lèvent**
  (`q.progress_pct` / `decisions.length` non gardés) au lieu de fail-closer. Reproduit en
  interceptant `/calibration` et `/decisions` avec `{}`. Antérieur à D-053 (code d'Étape 5,
  commit 9180ded) — à traiter en `/bugfix`, pas dans un commit de feature.

## D-054 · Projection REST tronquée — un cast n'est pas une vérification
Bug trouvé pendant D-053 (`/devil`), corrigé par `/bugfix` dans un commit séparé — un défaut
pré-existant n'a rien à faire dans un commit de feature.

**Repro** : un backend qui redémarre répond **200 avec un corps partiel**. Reproduit en
interceptant `/calibration`, `/decisions`, `/orchestrator`, `/scenario`, `/sources` avec `{}`.
Symptômes : `Cannot read properties of undefined (reading 'progress_pct')` et `(reading 'length')`
→ **C4 et le Decision Log disparaissaient de l'écran, sans un mot**.

**Cause racine — pas le symptôme.** Les panneaux n'étaient pas fautifs : `refreshProjections`
**castait** les corps de réponse (`as Calibration`, `as unknown as BlotterRow[]`, `as never`) avant
de les pousser dans le store. Un cast TypeScript est **effacé à l'exécution** : il ne vérifie rien,
il ne fait que faire taire le compilateur. Le store se retrouvait donc à violer son propre type, et
le premier consommateur qui faisait confiance au type levait. Corriger les panneaux seuls aurait
laissé la porte ouverte à tous les futurs consommateurs.

**Correctif à la frontière** (`app/lib/projections.ts`) : chaque projection est vérifiée sur
**exactement ce que les consommateurs indexent** (`quantitative`/`behavioral`/`sharpe` pour C4,
`decisions` tableau pour Zone D, `sources` pour l'orchestrateur, `current`/`available` pour MOCK).
Ce n'est pas une validation de schéma complète : c'est un contrat d'usage, testable et minimal.
- Une projection inexploitable **n'entre pas** dans le store (§3 : absente, jamais reconstituée).
- Elle **n'écrase pas** non plus la dernière projection saine : une réponse cassée ne doit pas
  faire clignoter des jauges valides vers « chargement… ».
- Un `console.warn` nomme précisément laquelle des trois est cassée.

**« Chargement… » éternel = échec silencieux.** Une fois la frontière fermée, C4 restait bloqué sur
« chargement… » tant que le serveur répondait mal — le crash était corrigé, la panne toujours
invisible. Un drapeau `projectionsBroken` distingue **attendre** (rien reçu) de **être en panne**
(reçu et rejeté) : C4 affiche alors `PROJECTION INDISPONIBLE — réponse incomplète du serveur`.
Même règle que pour le canal lent (D-053 `/polish`).

**Zone D : ne jamais confondre « log vide » et « projection cassée ».** Afficher « aucun event — le
log est vide » sur une projection défaillante ferait croire à un journal vide alors qu'il ne l'est
pas. Les lignes **déjà reçues restent affichées** — le log est append-only, elles restent VRAIES ;
seule leur exhaustivité est douteuse.

**Prévention (Loop 2 §6) — deux autres occurrences du même défaut.** `scenario?.available.map()`
protège du `null` mais pas d'un objet partiel truthy : le panneau MOCK levait pareil. Et le test de
régression en a révélé une **troisième**, que je n'avais pas vue : `info.fields.join()` sur une
entrée de `sources` sans `fields`. Les trois sont corrigées et couvertes.

- **Vérif** : 17 nouveaux tests (frontière ×6, C4 ×8, Zone D ×6, MOCK ×5) — **112 tests Vitest**,
  632 backend, tsc + vite build verts. Repro d'origine rejoué au navigateur : **0 erreur page**,
  15 panneaux toujours rendus, navigation clavier intacte, C4 affichant `PROJECTION INDISPONIBLE`,
  et cas nominal (sans interception) inchangé.
- **Leçon transverse** : partout où une donnée externe entre dans le store par un `as`, le type
  ment. Les blocs SSE passent par `applyBlock` et sont tout aussi castés — ils n'ont pas explosé
  jusqu'ici parce que les panneaux lisent via `MetaValue`/optional chaining, mais le même durcissement
  leur reste applicable si un jour un panneau indexe en profondeur.

## D-055 · Order Flow in-house — Niveau 2 CALCUL
`backend/app/orderflow/calculator.py` : un flux BRUT (carnet L2/MBO + Time & Sales) → un
`OrderFlowSnapshot` portant les quatre portes B1-B4, le profil de volume et l'ATR 5/14.

**Le module MESURE, il ne décide pas.** Aucun seuil, aucun verdict, aucun ordre (§2.1) : la
comparaison reste au moteur (`evaluate_lsr`). Séparer la mesure de la décision permet de
recalibrer un seuil sans toucher à un calcul, et de tester un calcul sans simuler une décision.

**Ce qu'il remplace.** Les portes étaient jusqu'ici des PROXYS fournis par la source
(`absorption` booléen, `aggressor_ratio` déjà agrégé) — `lsr_engine` les nomme d'ailleurs
« B1-like »/« B2-like » pour cette raison. Elles sont désormais calculées CHEZ NOUS depuis les
ticks : vérifiables, indépendantes du fournisseur. **Le câblage du moteur sur ces valeurs est une
tranche SÉPARÉE** : brancher une mesure neuve sur le chemin d'émission live sans l'avoir observée
serait imprudent (et « une feature par commit »).

**Deux réutilisations plutôt que deux implémentations.** Le profil de volume est **délégué** à
`app/volume_profile.py` (D-041) — deux VPOC dans le même terminal finiraient par se contredire ;
l'essai vérifie l'identité stricte avec un appel direct au moteur D-041. Le tick, la VA 70 % et le
ratio LVN viennent de la config existante, pas d'un second jeu de constantes.

**Formules — `v1 provisional` assumé (§11).** Le doc LSR NOMME les portes, il n'en donne pas les
formules, et aucun `/reference/` ne fait AUTORITÉ ici. Chacune est donc une première passe,
isolée et documentée pour être discutée :
- **B1 `wall_refill_ratio`** = rechargé / consommé sur un niveau DÉSIGNÉ. Jamais écrêté à 1 : un
  mur reconstruit plus gros qu'il n'a été mangé est une défense agressive, pas une anomalie.
- **B2 `tape_aggressor_buy_fraction`** = volume acheteur / volume total, **pondéré par le volume**
  et non par le nombre de prints (un print de 100 lots ne pèse pas comme un de 1 lot — compter les
  prints donnerait 0,10 là où le flux est acheteur à 92 %).
- **B3 `rejection_delta_ratio`** = delta net des prints POSTÉRIEURS à l'extrême, normalisé par le
  volume total, borné [−1, 1]. L'extrême retenu est celui d'où le prix s'est le plus éloigné —
  sinon le signe serait arbitraire dès qu'il y a un haut ET un bas.
- **B4 `post_sweep_aggression_ratio`** = débit après le sweep / débit avant (volume par seconde de
  part et d'autre). C'est une VITESSE : 100 lots en 1 s ne se lit pas comme 100 lots en 30 s. Les
  débits se mesurent sur les deux moitiés de la FENÊTRE, pas sur l'écart entre prints — qu'un seul
  print ancien suffirait à fausser.
- **ATR** = moyenne des `n` derniers True Range (`max(H−L, |H−C_prev|, |L−C_prev|)`, donc les gaps
  comptent). Moyenne simple et non lissage de Wilder : le lissage exige de rejouer tout
  l'historique pour être reproductible ; sur fenêtre bornée, la moyenne simple est déterministe et
  vérifiable à la main.

**Fail-closed porte par porte (§3)** : chaque grandeur vaut `None` **avec son motif** dans
`missing`. Aucune valeur par défaut — ni 0, ni 1, ni 0,5. Quatre `None` muets ne diraient pas
POURQUOI ; c'est le motif qui rend l'absence exploitable.

- **Le piège central : « hors profondeur publiée » ≠ « taille nulle ».** Un carnet tronqué à 3
  niveaux ne dit RIEN du 8e. Ma première règle (« dans la plage publiée → 0 ») ratait justement le
  cas qui compte : le mur EST souvent le meilleur bid, sa disparition rétrécit la plage, donc le
  niveau retombait « hors plage » et le retrait du mur devenait invisible. La règle correcte est
  **côté-dépendante** : au-dessus du meilleur bid = vide RÉEL, sous le dernier niveau publié =
  INCONNU. Trouvé par le test, corrigé, testé dans les deux sens.
- **Aucune déplétion → B1 non calculable**, jamais 1,0 : affirmer « le mur a tenu » quand il n'a
  jamais été mis à l'épreuve serait inventer une défense.
- **Barre corrompue → ATR non calculé** : sauter une barre au milieu recollerait deux barres non
  adjacentes et fabriquerait un True Range qui n'a jamais existé.
- **B3 exige la même couverture de côté que B2** — trouvé par la matrice de dégradation de
  l'essai, pas par un test écrit d'avance : sur un tape sans côté agresseur, le delta vaut
  mécaniquement 0, et ce 0 se lisait comme « rejet neutre OBSERVÉ » alors que rien n'était observé.
- **Mes erreurs de test, corrigées** : quatre attentes fausses (prints datés hors de la fenêtre
  d'analyse, arithmétique B4 supposant une autre définition de la fenêtre, sémantique B3 — le
  calcul avait raison, mon `None` attendu avait tort). Notées ici parce qu'un test faux qui passe
  est pire qu'un test absent.
- **Vérif** : 41 tests unitaires (portes ×4 avec chaque chemin fail-closed, profil, ATR, bornes,
  pureté, immuabilité) — **673 passed**, ruff clean. **Essai de validation INDÉPENDANTE** (le
  module n'est pas testé avec ses propres formules) : B2 recalculé naïvement sur 400 tirages →
  écart max **0,00e+00** ; B3 borné et de signe conforme sur 388 échantillons ; B4 exact ; profil
  **identique** au moteur D-041 appelé directement ; ATR 5/14 exacts vs TR calculés à la main ;
  scénario de sweep réaliste (mur 200 → 30 → 170, réintégration acheteuse) → B1 0,82 · B2 0,706 ·
  B3 +0,706 · B4 10,69× · VPOC 4999,0, et matrice de dégradation prouvant que chaque porte tombe
  SEULE avec son motif.
### /devil (Loop 4) — six façons de faire mentir le calculateur
- **Carnet CROISÉ (bid ≥ ask) → B1 refusée.** Un carnet croisé est corrompu (pathologie réelle,
  déjà détectée ailleurs sous `CROSSED_BOOK`). Mesurer un rechargement de mur dessus produirait un
  nombre plausible à partir d'une donnée fausse. Les snapshots croisés sont écartés, et leur
  nombre est DIT dans `missing` — un carnet cassé qui disparaît en silence est un carnet perdu.
- **Volume dérisoire → B2/B3 non mesurées.** « 100 % acheteur » sur un lot n'est pas un flux
  acheteur, c'est du bruit présenté comme une mesure. Plancher `ORDERFLOW_MIN_VOLUME` (v1
  provisional, à calibrer par instrument : MES ≠ ES). Trois tests antérieurs utilisaient 10 lots
  et sont remontés au-dessus du plancher — leur intention (bornes, fenêtre, futur) est intacte.
- **Débordement de taille — la faille en DEUX temps.** Des tailles à 1e308 débordent en `inf`.
  Premier correctif : filet de finitude sur le RÉSULTAT de chaque porte. **Insuffisant, et c'est
  la relecture de la sortie d'essai qui l'a montré** : quand le TOTAL déborde, `known/total` vaut
  `nan` (donc passe le test de couverture) et `delta/total` vaut **0,0** — fini, donc publié, et
  lu comme « rejet neutre observé ». Un zéro fabriqué par débordement. Garde ajoutée en AMONT, sur
  les volumes agrégés de B2/B3/B4.
- **B3 : la jambe de rejet part de la DERNIÈRE touche de l'extrême**, pas de la première. Sur un
  double creux, partir de la première ferait compter la vente du second creux comme du rejet
  acheteur (+0,000 au lieu de +0,300 — mesuré).
- **Fenêtre d'analyse absurde (0, négative, non finie) → snapshot MOTIVÉ.** Une fenêtre vide
  rendait quatre `None` sans cause visible, et un snapshot muet ressemble à un marché calme.
- **Erreur de méthode corrigée en route** : après le changement de règle B3, mon recalcul naïf de
  référence utilisait encore la première touche — l'essai affichait « signe conforme 356/381 » et
  j'ai failli le lire comme une régression du module. Référence réalignée → **381/381**. Une
  référence de validation périmée est aussi dangereuse qu'un test faux.
- **Vérif /devil** : +9 tests (carnet croisé ×2, plancher de volume ×2, débordement ×3, double
  creux, fenêtre absurde) → **682 passed**, ruff clean. Essai relancé : B2 exact sur 393
  comparaisons, B3 **381/381**, profil toujours identique au moteur D-041, et matrice d'attaques
  où chaque ligne refuse de mesurer avec son motif.

### /devil (2e passe) — les surfaces que la première n'avait pas regardées
La première passe attaquait les VALEURS (croisé, plancher, débordement). Celle-ci attaque la
STRUCTURE des entrées : ordre, doublons, unité de grille, durée.

- **Carnets non triés → B1 mesurait entre les mauvaises bornes.** Les prints étaient triés, pas
  les snapshots de carnet : `sizes[0]`/`sizes[-1]` étaient le PREMIER et le DERNIER *reçus*, pas
  le plus ancien et le plus récent. Deux tampons concaténés, ou un feed qui double-livre, et le
  rechargement se calculait à l'envers. Vérifié : carnets inversés → B1 **0,8235 vs 0,8235**.
- **Prints dupliqués (rejeu, fenêtres qui se chevauchent) → volumes gonflés.** Dédup sur `seq`,
  l'identifiant EXPLICITE du flux. **Sans `seq`, on ne déduplique pas** : deux prints identiques
  sont indiscernables d'un vrai double passage au même prix — ce qui arrive tout le temps —, et
  dédupliquer « au contenu » effacerait du volume RÉEL. Vérifié : flux rejoué ×2 → volume 510 vs
  510, B3 +0,7059 vs +0,7059.
- **Tick de prix invalide → profil ni publié ni « vide ».** `build_volume_profile` rend un objet
  VIDE (et non `None`) sur un tick absurde ; publié tel quel il se lirait « connecté mais sans
  volume » — exactement le mensonge refusé en D-053/D-055. Un tick invalide n'a pas de sens
  physique : il empêche la mesure (profil ET B1), il ne la dégrade pas.
- **B4 sur quelques millisecondes → refusée.** Un sweep collé à `now` donnait un débit « après »
  mesuré sur 1 ms : du bruit multiplié par mille, publié comme une accélération. Plancher
  `ORDERFLOW_MIN_SPAN_S` des DEUX côtés (v1 provisional).
- **Tous les prints datés du futur → motif ACTIONNABLE.** Erreur de câblage classique (le `now`
  fourni est en retard sur le flux) : le motif « volume sous le plancher » envoyait chercher au
  mauvais endroit. Le calculateur nomme désormais la cause probable — l'horloge d'appel.
- **Mes attentes fausses, encore deux** : `tick=None` est le « non fourni » documenté de l'API
  (il retombe sur `PRICE_TICK`), pas une valeur invalide ; et j'ai cherché le mot « futur » dans
  un message qui dit « postérieur à `now` ». Les assertions suivent maintenant le comportement et
  le message RÉELS, pas ceux que j'imaginais.
- **Risque résiduel tracé** : `volume_profile` est un `dict` MUTABLE dans un snapshot par ailleurs
  gelé — un consommateur peut le modifier en place pour tous ceux qui tiennent le même objet. Un
  `MappingProxyType` le fermerait, mais casserait la sérialisation JSON du futur câblage SSE.
  Choix assumé : documenté ici plutôt que verrouillé au prix d'un blocage en aval.
- **Vérif 2e passe** : +7 tests (carnets désordonnés, dédup avec et SANS `seq`, tick invalide ×5,
  plancher de durée ×2, prints du futur) → **689 passed**, ruff clean, essai relancé avec quatre
  attaques structurelles, toutes refusées avec motif.

### /polish (Loop 5) — les trois surfaces réelles d'un module sans UI
- **Latence MESURÉE, pas supposée.** Charge réaliste (1 500 prints, 120 carnets sur 30 s) :
  **3,2 ms/appel**, soit **1,6 %** du budget hot path (§7). Session dense (6 000 prints) : 12,2 ms
  (6,1 %). **Borne maximale du module** (20 000 prints, 2 000 carnets) : 56,3 ms, soit **28 %** du
  budget — chiffre écrit ici parce qu'il fixe le coût d'un gros tampon pour le futur câblage :
  garder 20 000 prints n'est pas gratuit. Rien optimisé : à charge réelle, il n'y a rien à gagner.
- **Les motifs SONT l'interface humaine de ce module** — c'est là que porte le polish. Format
  unique **« CODE : texte »** (espace avant le deux-points, §5) et **vocabulaire FERMÉ**
  (`MOTIF_CODES` : B1, B2, B3, B4, VP, ATR, TAPE, FENÊTRE, HORLOGE), énumérable pour qu'un log ou
  un futur panneau puisse filtrer sans deviner. Avant, six formats cohabitaient (`B1:`, `VP/B1:`,
  `ATR(5):`, `tape:`, `fenêtre d'analyse invalide:`). Un test vérifie que le vocabulaire reste
  fermé — sans quoi il dériverait au premier ajout.
- **Les périodes d'ATR voyagent avec la mesure.** `atr_5`/`atr_14` sont des alias ergonomiques
  qui MENTIRAIENT si la config passait la période à 7. Le snapshot porte désormais
  `atr_fast_period`/`atr_slow_period` : le lecteur sait ce que vaut le nombre.
- **API du paquet directement importable** : `from app.orderflow import compute_snapshot,
  OrderFlowSnapshot, MOTIF_CODES` — un consommateur n'a pas à connaître le chemin interne.
- **Vérif /polish** : +2 tests (API du paquet, périodes ATR) et 2 assertions renforcées
  (vocabulaire fermé, format greppable) → **691 passed**, ruff clean. Motifs relus tels qu'un
  humain les verra sur une dégradation complète : sept lignes, un code chacune, aucune ambiguïté.

- **Collision de vocabulaire signalée** : B1-B4 désignent AUSSI des panneaux de l'UI (B1 États
  S1·S2, B2 Bridge, B3 Sync, B4 Signal unifié). Les lettres restent de la documentation ; les
  identifiants du code portent le sens (`wall_refill_ratio`…), et snake_case côté Python là où le
  doc LSR écrit `wallRefillRatio` — la correspondance est dans la docstring du module.

## D-056 · Câblage du calculateur order flow dans `evaluate_lsr`
Le calculateur (D-055) entre dans le **chemin d'émission live** — le changement le plus risqué du
dépôt. Quatre décisions gouvernent la tranche, toutes assumées :

**1. Un interrupteur, dont le défaut est le comportement HISTORIQUE.**
`LSR_ORDERFLOW_SOURCE` = `"source"` (proxys du fournisseur : `absorption` booléenne,
`aggressor_ratio` pré-agrégé) ou `"inhouse"` (mesures maison). Défaut : **`"source"`**. La
propriété testée en PREMIER n'est pas « les mesures maison marchent » (D-055 l'a prouvé) mais
**« rien ne change tant qu'on ne l'a pas demandé »** : avec ou sans snapshot attaché, le mode
défaut produit le même plan. Un câblage qui modifie le chemin d'émission sans qu'on l'ait demandé
est un bug, pas une amélioration.

**2. B3 et B4 ne deviennent PAS des portes.** Les transformer en critères de rejet ajouterait des
refus sur des seuils **non calibrés**. Ils sont mesurés et exposés ; la décision de les faire
gater est séparée et se prendra sur des observations, pas sur une idée.

**3. B1 in-house exigeait un historique que le backend n'avait jamais gardé.** Le schéma ne porte
que le carnet COURANT (la heatmap, elle, accumule côté frontend), or le rechargement d'un mur est
par nature une mesure DANS LE TEMPS. Sans tampon, `wall_refill_ratio` n'aurait jamais été
calculable et le câblage aurait été **fictif**. D'où `_book_history` dans l'Engine, borné
(`BOOK_HISTORY_MAX` = 120 ≈ 30 s à 4 Hz — sans plafond, six heures garderaient 86 400 carnets).

**4. Comparaison OMBRE dans les DEUX modes** (`extras.orderflow_shadow`) : les deux valeurs, les
deux **verdicts de porte** (ce qui compte n'est pas l'écart mais s'il change une décision) et les
motifs du calculateur. C'est la preuve qu'on accumule avant d'oser basculer (§10). Elle ne décide
rien et **ne lève jamais** — un défaut d'observation ne doit pas casser la boucle qu'il observe.

**Le pont** (`app/orderflow/bridge.py`) traite le piège qui inverserait tout : un `BID_SWEEP`
signifie qu'une agression VENDEUSE a balayé le bid, donc le mur attaqué est un mur **ACHETEUR**,
au plus-BAS de la fenêtre. Le chercher à l'ask mesurerait la défense du camp adverse — un
contresens invisible dans un nombre qui aurait l'air correct. Sans sweep orienté, **aucun mur
n'est désigné** : en choisir un au hasard mesurerait une défense que personne n'a attaquée.

- **Bug trouvé par l'ESSAI, invisible en test unitaire.** `orderflow_source: str =
  config.LSR_ORDERFLOW_SOURCE` fige le défaut **à l'import** du module (Pydantic évalue le défaut
  à la définition de la classe). Toute bascule au runtime — variable d'environnement relue,
  réglage event-sourcé, essai — restait donc sans effet, et le moteur jurait « [source] » en mode
  maison. Mes tests unitaires passaient parce qu'ils fournissaient la source explicitement. La
  source se résout désormais **à l'appel**, et deux tests le verrouillent.
- **Le motif d'émission NOMME la source** (« absorption · flip 0,82 [source] » vs « mur rechargé ·
  flip 0,74 [inhouse] »). Sans ça, deux manifestes identiques à l'écran auraient pu être décidés
  par deux moteurs différents, sans moyen de le savoir après coup.
- **Ce que l'essai a démontré** (sweep forcé — on teste le câblage, pas le détecteur) :
  *scène A* mur rechargé à 0,875 et flux acheteur → les deux modes émettent, chacun avec son
  motif ; *scène B* **mur JAMAIS rechargé (0,125) alors que le proxy `absorption` dit toujours
  « défendu »** → le mode source émet, **le mode maison REFUSE**, et l'ombre l'annonçait
  (`verdict_source=True, verdict_inhouse=False, agree=False`). C'est exactement la valeur du
  calcul maison : il voit ce qu'un booléen fournisseur ne peut pas dire.
- **Premier essai non concluant, dit comme tel** : sur 60 ticks de mock, aucun sweep ne s'est
  déclenché — donc ni B1 ni l'émission n'étaient exercés, et les chiffres d'ombre ne prouvaient
  rien. Refait avec un sweep forcé plutôt que présenté comme une réussite.
- **Vérif** : 14 tests de câblage (dont la propriété de sûreté du mode défaut, fail-closed sur
  mesure absente, source inconnue rejetée, B3/B4 non gatants) + 11 tests de pont (côté du mur,
  fraîcheur, historique borné, ombre) → **716 passed**, ruff clean.
### /devil (Loop 4) — conditions de marché dégradées
Deux axes demandés : sweeps chaotiques et coupure de flux. Le premier a révélé un défaut
**structurel** que la livraison initiale aurait laissé passer en silence.

- **`alert.ts` GLISSE — B4 était structurellement incalculable en production.** Le détecteur
  ré-horodate l'alerte à CHAQUE évaluation d'une condition persistante (`ts=state["now"]`,
  D-046 : c'est l'identité `trigger|direction` qui fait l'événement, pas le `ts`). Passé tel quel
  au calculateur, `span_after = now − sweep_ts ≈ 0` en permanence → B4 sous le plancher de durée
  **à tous les ticks**, et la fenêtre B1 bornée à un instant qui recule sans cesse. Une porte qui
  répond toujours « non mesurable » ressemble à un marché calme. **L'essai de la livraison le
  montrait déjà** (« B4 non mesuré 52/52 ») et je l'avais attribué à l'absence de sweep : le
  chiffre était là, le diagnostic non. L'Engine garde désormais le PREMIER passage de l'événement
  (`_sweep_event_ts`), et un changement de direction le réinitialise. Mesuré après correctif :
  B4 = **14,0** à t+2 s d'un sweep persistant, là où il valait `None` pour toujours.
- **La fenêtre de mesure démarre AU SWEEP.** Sans borne basse, `consommé` se calculait depuis un
  carnet vieux de 30 s — donc AVANT l'événement : la mesure décrivait une déplétion sans rapport,
  et un changement de direction la laissait tourner sur le mur PRÉCÉDENT. Corollaire assumé et
  testé : juste après un flip, B1 n'est **pas encore calculable** — on n'a pas vu le nouveau mur
  se faire attaquer, et le dire vaut mieux que le deviner.
- **Un trou d'observation n'est pas une observation.** Coupure de flux : deux snapshots adjacents
  dans le tampon peuvent être séparés de trente secondes de cécité, et le « rechargement »
  constaté de part et d'autre n'a jamais été vu — il est INFÉRÉ. Même faute que « hors profondeur
  ≠ taille nulle » (D-055). Garde `ORDERFLOW_MAX_BOOK_GAP_S` (2 s = 8 échantillons à 4 Hz).
  Essai : cécité de 9 s après le sweep → `B1 : trou d'observation de 9s dans le carnet (> 2s) —
  déplétion non observée`, et le tampon ne bouge pas pendant la coupure (rien de non-FRESH n'entre).
- **Interaction découverte en route** : la borne au sweep retire souvent le trou de la fenêtre —
  le seul cas où la cécité compte vraiment est celle qui survient **après** le début de
  l'événement. C'est aussi le cas réel (sweep, puis le feed meurt pendant le rechargement). Ma
  première scène d'essai ne testait donc pas ce que je croyais ; refaite.
- **Données de test rendues réalistes** : sept tests de D-055 espaçaient leurs carnets de 5 à
  10 s, ce qui EST une coupure pour un feed à 4 Hz — le nouveau garde les refusait à juste titre.
  Espacement ramené à 0,25–0,5 s ; les ratios testés n'en dépendaient pas. Deux tests de pont
  plaçaient leur déplétion AVANT le sweep : replacée après, sinon ils testaient une fenêtre que
  le correctif exclut désormais par construction.
- **Vérif /devil** : +9 tests dégradés (fenêtre bornée au sweep, flip de direction, côté du mur
  suivant la direction, trou d'observation ×2, cadence normale non pénalisée, tampon pendant la
  coupure, carnet du futur, horodatage d'événement stable en intégration) → **725 passed**, ruff
  clean. Essai sur l'Engine réel : les trois scènes se comportent comme décrit, motifs à l'appui.
- **Limite honnête de l'essai** : au-delà de t+2 s, B4 retombe à `None` avec le motif « aucun
  volume avant le sweep » — c'est mon tape SYNTHÉTIQUE qui glisse avec `now`, pas un défaut : un
  vrai tape est une fenêtre glissante qui contient encore les prints d'avant l'événement.

### /polish (Loop 5) — une ombre qui clignote ne prouve rien
- **L'ombre n'était visible que 25 % du temps (mesuré).** `_assemble_fast` RECONSTRUIT `extras`
  à 4 Hz ; la boucle sweep y écrivait à 1 Hz. Trois ticks sur quatre, la comparaison disparaissait
  — et un champ qui va et vient se lit exactement comme « non mesurée », le mensonge que tout ce
  terminal refuse. Or l'ombre est précisément ce qui doit ACCUMULER de la preuve avant la
  bascule : intermittente, elle n'en accumule aucune. Elle vit désormais dans son propre attribut,
  recomposée à l'endroit UNIQUE où `extras` se construit. Re-mesuré : **40/40 ticks, 100 %**.
- **Une ligne LISIBLE en tête.** Un dict de valeurs brutes n'est pas un message. `resume` dit le
  verdict d'abord — « accord : les deux sources concluent pareil » / « **DÉSACCORD B1** — proxy et
  mesure maison ne concluent pas pareil » / « mesure maison non mesurable (B1, B2) » — les nombres
  restent en dessous pour qui veut vérifier.
- **Coût du câblage mesuré** : **0,21 ms** par tick sweep (snapshot + ombre), 0,46 ms au pire, sur
  la cadence 1 Hz et hors hot path (§2.8/§7). Le tampon de carnets se stabilise à ~13 entrées sur
  ce banc. Rien à optimiser.
- **Vérif /polish** : +2 tests (persistance de l'ombre à travers six ticks rapides ; ligne lisible
  dans les trois cas) → **727 passed**, ruff clean.

- **Reste ouvert** : la bascule elle-même. Elle se fera quand l'ombre aura montré assez d'accords
  — et le désaccord de la scène B est précisément le genre de cas à examiner avant, pas après.

## D-015 · Un opérateur par instance (AUTORITÉ `CLAUDE §9`)
`VITE_OPERATOR` (ou `?operator=YOUSSEF`) fixe l'instance ; défaut `SONY`. Tous les events
portent `operator`.
