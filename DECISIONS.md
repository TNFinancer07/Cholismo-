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

## D-057 · Accès aux données macro de Youssef — registre, connecteurs, cascade, client FRED
**Sources** : les deux artefacts fournis par le propriétaire de la spec — `API × Arbitrage`
(juillet 2026, 6 arbitrages) et `API × Dimension` (31.07.2026, D1–D5, « catalogues vérifiés »).
**Livré** : `backend/app/providers/` — `catalog.py` (registre), `connectors.py` (7 connecteurs),
`cascade.py` (z-score/divergence/tanh), `fred.py` (client d'interrogation).

### Périmètre assumé
Les specs décrivent ~50 variables, 7 familles de sources, 5 dimensions, 6 arbitrages. Cette
tranche livre **la couche d'accès et sa structure**, pas le câblage au `ContextSchema` : aucun
panneau nouveau, aucun bloc de schéma touché (§1 — un panneau lit UN champ, et il n'y a encore
rien à lire de vivant). Les artefacts disent eux-mêmes que la collecte doit démarrer pendant
que les catalogues se relèvent, « puisque la profondeur d'historique se construit avec le temps
et ne se rattrape pas ». Le câblage viendra quand une série aura de la profondeur.

### La doctrine C1/C2/C3 est devenue exécutable
La note pour Sony est explicite : « un C2 veut dire *ne pas coder l'identifiant en dur sans être
passé par le catalogue du fournisseur d'abord*, un C3 veut dire *ne pas commencer* ». Tenu comme
une règle de code, pas comme un commentaire :
- toute ligne non-C1 a `identifier is None` — **il n'existe aucune clé « probable » dans le
  dépôt**. Une clé inventée aurait exactement l'apparence d'une clé vérifiée (§3) ;
- `fetch_block_reason` est le seul portillon, et `build_url` refuse (`SeriesBlocked`) tout ce
  qu'il bloque. Une clé inconnue est bloquée **par défaut**, jamais autorisée par défaut ;
- **70 lignes, 48 collectables aujourd'hui** ; 7 en C2 (relevé de catalogue), 5 en C3.

### Trois natures de ligne — les confondre était le piège principal
`OBSERVED` (collectable) · `DERIVED` (calcul) · `PARAMETER` (aucune requête ne le fournira).
Conséquence non évidente et testée : **une ligne dérivée dont la dépendance est bloquée est
bloquée aussi, et le motif nomme le maillon** — `ilsw_ez` renvoie vers `bundei_real`, pas vers
un défaut de son propre étage. Sans ça, on cherche le problème au mauvais niveau.
Autre distinction qui manquait : **collectable ≠ interrogeable en HTTP**. Le SPF de Philadelphie
est C1 vérifié et n'a aucun REST — l'absence est structurelle, `has_rest_endpoint` le dit.

### Le registre est verrouillé au moteur qui tourne
La matrice de poids du quadrant existait déjà dans `strategies/youssef.py`. Elle existe
maintenant à deux endroits, donc un test exige leur égalité — de même que les six arbitrages
doivent porter les mêmes dimension/horizon/seuil que ceux que `compute_arbitrages` émet. Une
spec transcrite qui dérive silencieusement du code qu'elle décrit ne vaut rien.

### Pièges de source armés (ceux qui cassent en silence)
- **Dataflow ICP mort** depuis le 04.02.2026, remplacé par HICP à structure identique : un test
  interdit à tout identifiant du registre de commencer par `ICP.`.
- **Code de zone AMECO** en constante visible (`EA20` → `EA21` aux élargissements).
- **Bascule d'ISIN du Bund€i écrite maintenant**, comme la spec le demande — « pas le jour où la
  série cassera ». Et elle MESURE au lieu de supposer : au 01.08.2026, jambe EUR à **6,7 ans**
  contre 10 ans constants côté US, soit **3,3 ans d'écart de ténor déjà**. La spec parlait d'une
  dérive à venir ; elle est là. `bundei_roll_state` rend `BASCULE_REQUISE`.
- **Marqueurs de trou, un par fournisseur, tous mortels s'ils sont lus comme des nombres** :
  `.` (FRED, Bundesbank), `:` (Eurostat), `null` (Yahoo, DBnomics). Aucun ne vaut zéro.

### Incohérences : déclarées, pas patchées en douce (protocole des artefacts)
`KNOWN_CONFLICTS` porte les trois, avec les deux valeurs en présence et ce que le code fait
aujourd'hui — coefficient RED **0.4 (registre N3) vs 0.0 (référentiel)**, TTL 4 h contre NFCI
hebdomadaire, échelle k/seuils qui empêche mécaniquement tout GO.
**Un seul point tranché, et il va plus loin que la spec** : le TTL est séparé en deux axes —
âge de NOTRE COPIE (piloté par la dimension) et âge de la PUBLICATION (piloté par la fréquence).
La spec dit qu'une lecture littérale tuerait le NFCI ; c'est incomplet. **VIXCLS et
BAMLH0A0HYM2 sont des séries de clôture quotidienne** — un seuil de 4 h sur l'âge d'observation
les tuerait aussi. Ce n'est donc pas le seul cas hebdomadaire qui condamne la lecture littérale.

### Cascade — trois gardes qui viennent des trois conséquences de la spec
Profondeur (sous la fenêtre : rien, pas d'approximation), plancher de σ (une série plate n'a pas
de z-score, elle a une division par zéro), et signalement `outlier` **sans écrêtage** — parce que
`tanh` noie l'aberration plus loin : si elle n'est pas vue ici, personne ne la verra, et écrêter
déciderait à la place de l'opérateur (§2.1). Une composante manquante n'est **jamais
renormalisée** sur les présentes : un D1 amputé du PMI (0.30) se lirait comme un D1 complet.

### Client FRED — deux natures d'échec, jamais confondues
Refus de POLITIQUE → exception (clé absente, identifiant mal formé, ligne C2/C3, mauvais
fournisseur) : c'est une erreur de programme, elle doit s'arrêter, pas se dégrader en série vide
qu'on lirait comme un marché calme. Condition de DONNÉES → motif dans le résultat, sans
exception : l'appelant garde ce qu'il avait (doctrine D-050).
Deux gardes non demandés mais nécessaires : **l'identifiant est validé avant la construction de
l'URL** (sans ça, `series_id` écrit dans la query string — un `&` suffit à ajouter un paramètre
à l'appel), et **la clé ne fuit nulle part** (un message de socket contient volontiers l'URL
entière ; tous les motifs passent par `redact`).

### Vérification
**826 passed** (+99 : 25 registre, 31 connecteurs, 18 cascade, 25 FRED), ruff clean, `tsc`
clean. **Essai réel** sur le chemin `urllib` par défaut (serveur local rejouant une réponse
FRED, pas le fetcher injecté) : UNRATE/DFF/SP500/T10YIE lues, trou « . » compté, `vixcls` par la
clé métier, quatre refus de politique sans qu'aucune requête ne parte, réseau mort rendu en
motif sans fuite de clé.

### /polish (Loop 5) — un registre qu'on ne peut pas lire n'est pas un registre
- **Latence : MESURÉE, rien à faire.** Passe complète sur les 70 lignes (motifs + endpoints
  rédigés) = **0,36 ms** (0,32 min / 0,62 max), `fetchable()` 0,05 ms, import 98 ms. Aucun
  travail d'optimisation n'était justifié, et le dire vaut mieux que le supposer.
- **Les motifs disaient « non » sans dire quoi faire.** Le pire était `calcul dérivé, pas une
  collecte — voir depends_on` : renvoyer à un NOM DE CHAMP quand la question est « depuis quoi
  se calcule cette ligne ». Les motifs nomment désormais leurs intrants
  (`dérivé — calculé depuis gdpc1, gdppot`), et **tous** portent la même forme
  `catégorie — constat : quoi faire` (`C2 —`, `C3 —`, `paramètre —`, `dérivé —`, `inconnu —`) :
  vingt-deux motifs défilent d'un coup, sans étiquette de tête commune l'œil ne trie plus.
  Au passage : notes recollées proprement (majuscule initiale, point final, parenthèses
  imbriquées) et **redondances supprimées** — `d4_coeff` disait deux fois « pas une donnée ».
- **Dépendance circulaire : dite, pas une pile qui déborde.** Personne n'en a écrit, rien ne
  l'empêchait — une `RecursionError` au premier import aurait été un blocage sans message. Le
  garde remonte le cycle **tel quel** jusqu'en haut : dire « ouvrir `b` » puis « ouvrir `a` »
  enverrait l'opérateur en rond, ce qui est pire que ne rien dire.
- **Sortie propre : un thread ne s'annule pas.** `timeout_s=None` se traduisait en
  `urlopen(timeout=None)` — un thread qui ne meurt jamais. Timeout borné [1 s, 60 s], défaut
  pour toute valeur absurde. **Mesuré** : à l'annulation, la boucle d'événements se libère en
  < 0,5 ms, mais le thread continue jusqu'au bout de sa socket et `asyncio.run` attend son pool
  à la fermeture — **la durée d'un arrêt propre EST le timeout du fetch**. C'est ce constat, pas
  le confort, qui justifie la borne haute.
- **Découvrabilité — `python -m app.providers`.** Le registre transcrit deux specs de ~50
  lignes ; tant qu'il ne se lit qu'en important des modules, la question qu'on se pose devant
  ces artefacts (« qu'est-ce que je collecte aujourd'hui, qu'est-ce qui est bloqué, par quoi ? »)
  n'a pas de réponse à portée de main. Vue dense, monospace, **sans aucune couleur** : le statut
  passe par un glyphe **et** le texte du motif — un test interdit qu'une ligne non collectable
  s'affiche sans son motif (§3 transposé au terminal). Troncature toujours VISIBLE (`…`), rien
  ne dépasse la largeur, la clé API n'est jamais imprimée, et l'en-tête dit « lecture seule ·
  aucun appel réseau · aucun ordre ». Seconde vue `arbitrages` (groupée par Arb 1–6, formule à
  l'appui). Aucun appel réseau, aucun panneau nouveau (§10 — on ne construit pas N+1 avant N).
- **Trois familles cessent d'être confondues dans le compte** : « 6 identifiants à relever ·
  3 sources bloquées · 2 paramètres à calibrer », au lieu d'un « 5 bloquées » qui mélangeait un
  relevé de catalogue avec un paramètre — or « C3 » ne veut pas dire « donnée manquante », et
  un paramètre ne manque jamais.
- **Nettoyage** : `ParsedSeries.note` était mort-né (jamais renseigné, jamais lu) — supprimé.
- **Vérif /polish** : +18 tests (5 sur la forme des motifs et le cycle, 8 sur la borne de
  timeout et l'annulation, 12 sur la vue) → **851 passed**, ruff clean, `tsc` clean,
  112 Vitest verts. Vue rendue à l'écran, les deux modes.

### Connecteur SDMX BCE — et l'extraction du harnais qui l'a précédé
- **Refactor d'abord, feature ensuite** (Loop 3 puis Loop 1, deux commits — jamais mélangés).
  Le client BCE partageait tout le harnais d'interrogation avec FRED : timeout borné, fetcher
  injecté, lecture bornée, les deux natures d'échec, rédaction des secrets, portillon du
  registre. Extrait dans `providers/client.py` **avant** d'écrire le second connecteur —
  dupliquer ce harnais une deuxième fois l'aurait figé, et les cinq suivants l'auraient recopié.
  Zéro changement de comportement, et c'est vérifiable : les **34 tests FRED passent sans être
  touchés**, motifs au mot près.
- **Aucune clé API, et c'est prouvable.** Le service BCE est public. `EcbClient` n'a même pas de
  paramètre de clé (test par introspection de signature), et un test vérifie qu'une
  `FRED_API_KEY` définie n'apparaît ni dans l'URL ni dans le résultat. Un client qui exigerait
  une clé refuserait des séries accessibles ; un client qui en enverrait une la ferait fuiter
  chez un tiers qui ne l'a pas demandée.
- **Générique par construction** : une seule fonction `fetch(dataflow, key)` couvre YC, AME,
  SPF, EST, ILM, HICP — « même connecteur générique, seuls le dataflow et la clé changent ».
  `DATAFLOWS` documente ce que chacun sert **sans restreindre** : le connecteur accepte tout
  dataflow bien formé.
- **ICP refusé AVANT la requête, avec son remplaçant nommé.** Le dataflow est mort depuis le
  04.02.2026 ; laisser partir l'appel ramènerait une erreur de service qu'on lirait comme une
  panne réseau. Le refus vaut aussi par la clé pointée (`ICP.M.U2…`).
- **Défaut que j'ai introduit puis corrigé avant de committer** : j'avais deux constructions
  d'URL BCE — celle du registre (`connectors._ecb_url`) et celle du client. Exactement ce que
  j'avais reproché à FRED et corrigé là-bas. Le registre délègue désormais au client (import
  local, la dépendance ne peut aller que dans ce sens), un test verrouille l'égalité des deux
  chemins sur cinq lignes — et les gardes du client (dataflow retiré, clé mal formée)
  s'appliquent du coup aussi au chemin registre.
- **L'avertissement le plus lourd de la spec rendu actionnable** : « ne jamais coder une clé en
  dur sans l'avoir confirmée au catalogue » suppose de savoir où le chercher.
  `series_keys_url(dataflow)` le donne. Réserve assumée dans l'esprit C2 :
  `detail=serieskeysonly` est le paramètre SDMX REST standard mais **n'a pas été vérifié contre
  le service de la BCE** cette session — c'est dit dans la docstring, pas maquillé.
- **Vérif** : +38 tests → **889 passed**, ruff clean. Essai réel sur le chemin `urllib`
  (serveur local rejouant du SDMX-CSV) : YC / AME / SPF lues avec le trou « . » compté, clé
  pointée et clé métier du registre, quatre refus de politique sans qu'aucune requête ne parte,
  zéro `api_key` dans les URL produites.

### Connecteur Eurostat — et le défaut silencieux qu'il a fait sortir
- **/bugfix (Loop 2) AVANT la feature.** En écrivant les tests, j'ai vérifié ce que faisait mon
  parser JSON-stat déjà committé sur une réponse NON filtrée. Repro : cube 3 pays × 3 mois avec
  `id = [time, geo]` → il rendait `6.1 / 3.1 / 7.1`, soit **trois PAYS lus comme trois DATES**.
  Un chômage zone euro affiché à 3,1 % puis 7,1 %, avec l'air d'une mesure. Cause racine :
  indexer `value` par la position temporelle n'est correct que si toutes les autres dimensions
  valent 1 — le parser avait été écrit sur la forme d'une réponse filtrée et supposait cette
  réduction sans jamais la vérifier.
- **Le cas symétrique est refusé aussi, et c'est le point important** : avec `id = [geo, time]`
  le parser rendait par HASARD la bonne série — celle de EA20, que personne n'avait demandée.
  Choisir un pays par défaut serait décider à la place de l'opérateur (§2.1). Les deux ordres
  sont couverts par des tests de régression.
- **`eurostat_open_dimensions` dit QUOI épingler**, pas seulement « non ». Et le client
  distingue les deux causes : « réponse Eurostat NON FILTRÉE : geo, unit portent encore
  plusieurs valeurs » ≠ « réponse illisible ». Chercher un défaut de parsing quand il manque
  juste un filtre fait perdre l'après-midi. La requalification passe par un point d'extension
  du harnais (`_on_unreadable`), qui reçoit le texte déjà en main — **aucun second appel réseau**
  (ma première version en refaisait un, corrigée avant commit).
- **Aucune valeur de filtre inventée.** `unrate_ez` porte `geo=EA20` parce que la spec l'écrit ;
  pour les deux autres datasets, rien n'est deviné — c'est la RÉPONSE du service qui nomme les
  dimensions restées ouvertes, et c'est une information plus fiable qu'une constante supposée
  (doctrine C2 appliquée aux filtres, pas seulement aux identifiants). Le registre gagne un
  champ `filters`, et `fetch_catalog("unrate_ez")` applique le filtre d'office.
- **Leçon BCE appliquée d'emblée** : une seule construction d'URL Eurostat, le chemin registre
  délègue au client (import local), test d'égalité sur les trois lignes.
- **Réserve de fond redite dans le module** : l'ESI n'est pas un PMI. Le biais n'est présent
  que d'un côté de la divergence, donc il ne s'annule pas — il se lit comme du signal. C'est le
  risque n°1 de D1, dont le PMI porte le plus gros poids (0.30).
- **Vérif** : +33 tests → **922 passed**, ruff clean. Essai réel sur le chemin `urllib` : les
  trois datasets lus filtrés, `unrate_ez` par la clé métier, **le même appel sans filtre rend
  le motif au lieu d'une série**, quatre refus de politique sans qu'aucune requête ne parte.

### /polish (Loop 5) après les trois connecteurs — dire ce qu'on sait VRAIMENT aller chercher
- **La vue mentait par omission.** Elle affichait `✓ bund_nominal` comme « collectable » alors
  qu'aucun client Bundesbank n'existe : la ligne est C1, l'endpoint REST existe, et pourtant on
  ne sait pas l'interroger. Trois niveaux à ne pas confondre, désormais distincts partout :
  1. **collectable** (registre : C1, observée) — `fetch_block_reason` ;
  2. **endpoint HTTP** (le SPF est C1 et n'en a aucun) — `has_rest_endpoint` ;
  3. **connecteur écrit** — `has_client`. Nouveau, et c'est le niveau qui manquait.
  En-tête honnête : « 48 collectables · **41 INTERROGEABLES aujourd'hui** ». Glyphe `○` distinct,
  et le motif suit toujours (§3) : `connecteur BUNDESBANK à écrire`, `pas de REST` — deux causes
  différentes, deux messages, parce que l'une est structurelle et l'autre est du code à produire.
- **Le marqueur passe DEVANT l'identifiant**, sinon la troncature mange précisément la partie
  actionnable — le test de largeur l'a attrapé, et c'est la même faute que j'avais corrigée sur
  les indices de catalogue. Deux fois le même piège : la partie utile doit survivre à la coupe.
- **Une porte d'entrée unique** : `client_for(key)` rend le client capable d'aller chercher CETTE
  ligne, sans que l'appelant sache quel connecteur s'en occupe — et lève un motif utile sinon, y
  compris le cas « connecteur pas encore écrit », **qu'aucun autre garde ne couvrait**.
- **Uniformité des motifs vérifiée entre les trois clients** (FRED, BCE, Eurostat) : « X
  injoignable — … » et « réponse X illisible ou hors bornes — cache précédent conservé ». Le
  harnais partagé tient sa promesse ; rien à harmoniser à la main.
- **Latence re-mesurée** après l'ajout des imports locaux : passe complète sur les 70 lignes
  **0,49 ms** en médiane, avec un premier passage à ~47 ms — c'est le coût d'import unique des
  modules connecteurs, pas un coût par appel, et ce chemin est un diagnostic, pas le hot path.
- **Vérif /polish** : +8 tests → **930 passed**, ruff clean. Vue rendue à l'écran, les deux modes.

### Six séries de diagnostic + assemblage tabulaire (demande opérateur, script `fredapi`)
Un script personnel de Youssef proposait une cartographie FRED par dimension. Recoupée au
registre : **22 séries communes sur 28**, 6 ajouts, 10 absences, 0 vrai désaccord de dimension.
- **Le recoupement a servi à trancher, pas à choisir un camp.** Les 10 absences comprennent
  `pmi_us` (0.30), `lei` (0.20) et `sahm` (0.15) — **0,65 du poids de D1**. Basculer sur la
  cartographie du script rendrait D1 non pas dégradé mais **incalculable** (la cascade refuse de
  renormaliser sur les composantes présentes, D-057). D'où : on ajoute, on ne remplace pas.
- **Les 6 ajouts entrent comme DIAGNOSTICS**, jamais comme intrants : `payems`,
  `fed_target_upper`, `sofr`, `walcl`, `cpi`, `core_cpi`. Aucune n'apparaît dans les deux
  artefacts, donc aucune n'alimente une formule.
- **Nouveau champ `role` (FORMULE / DIAGNOSTIC), et un test qui le rend contraignant** : une
  ligne de diagnostic ne peut apparaître dans aucun poids. Sans ça, rien n'empêchait une ligne
  « de contexte » de se retrouver pondérée — comptant une information que la spec ne prévoit
  pas, ou la comptant deux fois. L'occasion a servi à **rendre explicites 9 lignes déjà
  diagnostiques en prose** (`igoas`, `stlfsi`, `move`, `gdpnow`, `dtwexbgs`, `bopgstb`, `reer`,
  `t5yie`, `credit_impulse`) : les artefacts disaient « second rang », « ligne supprimable »,
  « contrôle de cohérence » — c'est désormais lisible par le code. **15 diagnostics au total.**
- **Le piège CPI est armé** : « core PCE — c'est la cible OFFICIELLE de la Fed, **pas le CPI** ».
  `cpi`/`core_cpi` entrent, et un test vérifie qu'ils ne servent aucun arbitrage — le π de
  `taylor_now` reste `pcepilfe`.
- **`to_columns` (pur) sous `to_dataframe` (pandas)**. Toute la logique est en Python pur et
  testée sans pandas ; `to_dataframe` n'est qu'un habillage. Trois règles, chacune corrigeant
  une manière de mentir observée dans le script d'origine :
  1. **une série en échec n'est jamais une colonne vide** — elle sort du tableau avec son motif,
     sinon réseau mort et donnée pas encore publiée deviennent indistinguables (§3) ;
  2. **aucun remplissage** — pas de `ffill`, pas d'interpolation : une valeur reportée est une
     valeur inventée, et un z-score calculé dessus n'est pas un z-score. Vérifié par un test qui
     inspecte l'**AST** (la docstring, elle, a le droit de nommer ce qu'elle interdit) ;
  3. **la couverture est rendue** — mêler quotidien/mensuel/trimestriel donne un tableau très
     creux ; ce n'est pas un défaut, mais le lire sans le savoir en est un.
- **L'index garde la période telle que publiée.** `datetime_index=True` est **opt-in** parce
  qu'il invente de la précision (« 2026 » deviendrait le 1ᵉʳ janvier) : c'est l'appelant qui
  l'accepte, jamais le défaut.
- **pandas reste hors du terminal** : `requirements-dev.txt` seulement. Le chemin d'exécution
  n'a pas à porter une pile numérique de plusieurs dizaines de Mo pour une commodité
  d'exploration ; l'absence produit un message actionnable, pas un `ImportError` nu.
- **Vérif** : +21 tests → **950 passed**, ruff clean. Essai réel sur le chemin `urllib` avec un
  faux FRED : 12 colonnes / 3 périodes pour D1, `nrou` en 503 sorti du tableau avec son motif,
  et le creux structurel visible colonne par colonne.

### Script BCE d'un opérateur — ce qu'il apportait, ce qu'il coûtait
Second script personnel (`requests` + pandas, connecteur SDMX BCE). Le connecteur maison existait
déjà et était plus strict, mais **le script avait deux choses que je n'avais pas** — reprises :
- **`startPeriod` / `endPeriod`.** Le client BCE ramenait l'historique COMPLET à chaque appel.
  C'est un paramètre SDMX REST standard, et il change l'ordre de grandeur du transfert pour rien.
  Étendu à `endPeriod`, et la validation accepte **toutes les granularités SDMX** — année, mois,
  jour, mais aussi trimestre, semestre, semaine : n'accepter que des jours rendrait `AME`
  (annuel) et `SPF` (trimestriel) inbornables. Une borne mal formée est refusée avant l'URL,
  puisqu'elle finirait dans la query string.
- **Un `User-Agent`.** Le fetcher par défaut envoyait un `Python-urllib/3.x` anonyme, que
  certains services publics bloquent — et le refus se lit alors comme une panne de source.
  Ajouté au harnais, donc valable pour les trois connecteurs.

**Quatre défauts du script, démontrés par exécution plutôt qu'affirmés** (pandas 3.0.5) :
1. `pd.to_datetime` fait **collapser des granularités différentes sur le même horodatage** :
   `"2023"` (AMECO annuel) et `"2023-Q1"` (SPF trimestriel) deviennent tous deux
   `2023-01-01`, sans trace. C'est précisément la précision inventée que `to_dataframe` refuse
   par défaut ici — l'index horodaté y est opt-in.
2. `"2023-S1"` et `"2023-W05"`, périodes SDMX **légales**, font LEVER `pd.to_datetime` — et la
   levée est **hors** du `except requests.exceptions.RequestException`.
3. `pd.to_numeric` lève sur un marqueur non numérique, également hors du `except` capturé : un
   échec réseau rend un DataFrame vide, une valeur mal formée fait planter l'appelant.
4. `return pd.DataFrame()` sur erreur : `.empty` est **vrai** aussi bien pour un 503 que pour une
   fenêtre légitimement vide — la confusion échec/absence que §3 interdit. Et si les colonnes
   attendues manquent (page d'erreur, autre format), le script **retourne le DataFrame brut**
   avec des colonnes arbitraires.

**Réserve sur la clé d'exemple** : `B.U2.EUR.4F.G_N_A.SV_C_UC.A100` ne correspond pas à la clé
vérifiée de la spec (`…SV_C_YM.SR_1Y`). C'est exactement le cas C2 — une clé plausible non
confirmée. Le client ne peut pas l'attraper (elle est bien formée) : seul le relevé au catalogue
le peut, d'où `series_keys_url()`.

**Refactor préalable** (Loop 3, commit séparé) : `SeriesTable` / `to_columns` / `to_dataframe`
sont remontés de `fred.py` dans le harnais — ils ne doivent rien à FRED. Les trois connecteurs
en héritent ; le seul point propre à chacun (« un nom désigne quelle série ? ») devient
`_fetch_one`. 47 tests FRED inchangés.

**Vérif** : +18 tests → **968 passed**, ruff clean. Essai réel : appel borné, trois granularités
bornées simultanément, période gardée telle quelle, et trois refus de politique sans requête.

### Audit adversarial du script FRED — et les deux défauts qu'il a trouvés DANS MON code
39 agents, 3 lentilles (données / API-sécurité / cohérence au registre), chaque constat soumis à
un réfutateur. **36 constats, 12 confirmés, 24 réfutés** — la passe adversariale en a tué les
deux tiers, ce qui est le point de l'exercice. Deux résultats méritent d'être consignés.

**Le verify a corrigé son propre auditeur.** L'auditeur affirmait que « réseau KO » et « donnée
absente » étaient indiscernables dans le script. Faux, démontré : `fredapi` ne lève rien sur une
série vide, il rend une `Series` vide — la colonne est donc PRÉSENTE en tout-NaN, alors qu'une
panne réseau la fait disparaître. Le réfutateur a même relevé que la démonstration de l'auditeur
IMPRIMAIT deux shapes différentes tout en concluant « strictement indiscernable ». Il a ensuite
ré-énoncé le constat sur le bon couple, **plus grave** : dans le script, une panne réseau et un
**refus de politique** (clé révoquée, série inexistante, quota 429) produisent des DataFrames
`equals()`. Une clé morte se lit comme une panne de FRED.

**Deux défauts confirmés dans `providers/`, vérifiés par moi avant correction :**
1. **`to_dataframe` reproduisait le défaut que je venais de reprocher aux scripts.** La série en
   échec disparaissait du tableau, `df.attrs` était vide, et le motif n'était récupérable qu'en
   rappelant `to_columns` — donc en **refaisant tous les appels**. Un tableau amputé sans trace
   se lit comme un tableau complet. `failed` / `coverage` / `requested` voyagent désormais AVEC
   le tableau. Seul `SeriesTable` tenait la doctrine ; l'étage pandas ne la tenait pas.
2. **« Injoignable » couvrait aussi les refus.** Un HTTP 400/401/404/429 signifie que le service
   a RÉPONDU et refusé : la demande est en cause. Le motif disait « FRED injoignable », ce qui
   envoie chercher une coupure réseau inexistante et peut masquer une clé morte des heures.
   Motifs distincts désormais (accès refusé / série inconnue / quota / requête en cause /
   panne 5xx), pour les trois connecteurs puisque c'est dans le harnais. On ne LÈVE pas pour
   autant : c'est une condition d'exécution, pas une erreur détectable avant l'appel.

**Ce que je retiens de l'exercice** : le seul reproche fondé contre le dépôt portait sur du code
écrit dans cette même session, et je ne l'avais pas vu — les autres mentions du dépôt dans
l'audit le citaient comme contre-exemple. Le coût (2,6 M jetons) est disproportionné au regard
des deux corrections ; ce qui l'a rentabilisé, c'est la couche de réfutation, pas la recherche.

### /polish après l'audit — vérifier ce que j'avais affirmé, puis rendre l'état LISIBLE
- **Une affirmation vérifiée après coup.** J'avais écrit que la trace « voyage avec le tableau ».
  Mesuré : `attrs` survit à la sélection de colonnes, `copy()`, `head()`, `dropna()` et `concat`
  (pandas 3.0.5). L'affirmation tient — mais elle ne tenait que parce que je l'ai vérifiée, pas
  parce que je l'avais conçue ainsi.
- **`attrs` brut n'est pas un message** (même leçon que l'ombre order flow, D-056). Un opérateur
  voyait `shape = (2, 2)` après avoir demandé 3 séries, et un dict à déchiffrer. `SeriesTable`
  porte maintenant `resume` — « 3 demandées · 2 lues · 1 EN ÉCHEC : BOOM » — placé **en tête**
  d'`attrs`, et rendu par `str(table)`. La liste des noms est bornée à trois, le compte jamais.
- **Latence re-mesurée** après toutes les évolutions : **0,49 ms** en médiane sur les 76 lignes
  du registre, inchangé. Rien à optimiser.
- **Vérif** : +4 tests → **977 passed**, ruff clean, `tsc` + `vite build` OK, 112 Vitest verts.

### Les sept connecteurs sont complets — et la validation réelle reste hors de portée d'ici
**Bundesbank (BBSIS)** : les 20 tests écrits avant une interruption sont repris tels quels et
passent (38 avec paramétrage). Un point de doctrine y est encodé : la spec donne `R10XX` (10 ans)
et `R05XX` (5 ans) et dit que le code encode la maturité résiduelle. Le motif saute aux yeux —
et c'est le piège. `svensson_key(2)` est REFUSÉ : `R02XX` serait une inférence, pas une clé
vérifiée. **Un motif évident est un indice, pas une preuve.** Le parser reconnaît désormais le
séparateur en essayant plusieurs et en gardant celui qui produit des PÉRIODES ; auparavant un
export `;` tombait en « illisible » — fail-closed correct, mais cul-de-sac.

**Socrata CFTC** : `value_field` est un argument OBLIGATOIRE et sans défaut. La ressource porte
des dizaines de colonnes ; en deviner une produirait une série fausse ET plausible, le pire cas.
`$limit` est toujours posé — sans lui Socrata plafonne à 1 000 lignes **en silence**.

**SDMX international** : deux formats (SDMX-CSV du BIS, JSON à listes parallèles de DBnomics)
servis par le MÊME client. Le parser est choisi par la méthode appelée, passé en argument à
`_run` — un attribut d'instance aurait rendu le résultat sensible à l'ordre des appels, et un
test le vérifie en alternant les deux.

**Yahoo** : la réserve des specs est écrite dans le module plutôt que découverte un matin — ce
n'est pas une API officielle, les CGU couvrent l'usage personnel, ça cassera un jour et le
remplacement sera manuel. `ZQ` reste une racine de contrat, jamais un ticker.

**Deux tests devenus obsolètes ont été CONSERVÉS**, pas supprimés : « une ligne collectable sans
client s'affiche honnêtement » ne mord plus, puisque les sept connecteurs ont un client. Ils
testent désormais l'invariant sur un registre de clients amputé. Le supprimer parce qu'il ne
mord plus aujourd'hui, ce serait perdre le garde au moment où le prochain fournisseur arrive.

**53 lignes sur 54 sont interrogeables** ; la 54ᵉ est `spf_us`, dont l'absence de REST est
structurelle.

### Validation end-to-end : BLOQUÉE PAR L'ENVIRONNEMENT, pas par le code
Mesuré : `pypi.org` répond 200, et **les cinq fournisseurs sont refusés au CONNECT (403)** par la
politique d'egress. Le README du proxy est explicite : « do not retry organization policy denials
(403/407) — report them instead. » Aucune requête réelle n'a donc jamais atteint un fournisseur,
et les formats de réponse viennent des SPECS, pas d'une réponse observée. C'est la seule chose
que ce dépôt ne peut pas prouver depuis l'intérieur, et elle est dite plutôt que maquillée.

`scripts/validation_reelle.py` est livré pour être lancé LÀ où l'accès existe : il exerce les
clients maison contre les vrais services, une ligne C1 par fournisseur, et classe chaque échec
**par cause** — RÉSEAU / SERVICE / PARSING / CRASH. La distinction n'est pas cosmétique :
`PARSING` est le verdict qui vaut le déplacement, puisqu'il dit que la spec se trompait sur le
format — précisément ce qu'un mock ne peut pas révéler.

*Défaut trouvé sur moi-même en l'écrivant* : la première version étiquetait « ✗ PARSING » toute
absence de série, y compris les pannes réseau — la confusion même que ce paquet passe son temps
à défaire. Corrigée avant commit.

## D-058 · ReplayDataSource — le replay branché sur la couture du terminal
**Trois décisions de conception, chacune tranchée contre une facilité tentante.**

### 1. Le sens du flux : le terminal reste le seul à cadencer
`MarketDataSource` est TIRÉ (le moteur appelle `tick_fast`), `ReplayEngine.start()` POUSSE avec
ses propres `sleep`. Les brancher tels quels mettrait **deux horloges en concurrence** et
gèlerait la boucle d'événements (§7). L'itérateur PUR (`iter_ticks`) a donc été extrait du
moteur — même parsing, zéro cadence — et la source avance une **horloge virtuelle** du temps
réel écoulé × vitesse. Un test le verrouille en inspectant l'AST : ni `sleep` ni `start` dans le
module. Le refactor d'extraction a changé un comportement observable au premier essai (le
générateur avançait le compteur avant le test d'arrêt, `emitted` valait 6 au lieu de 5) — le
test `stop` l'a attrapé, le test d'arrêt est passé APRÈS la livraison.

### 2. Un replay ne publie que ce qu'un tape contient
Un tape porte des prints et, quand le fichier les donne, une profondeur au meilleur limite. Il
ne contient **ni VIX, ni GEX, ni score SVS, ni matrice Bridgewater**. Ces champs ne sont donc
pas écrits : ils vieillissent visiblement vers STALE puis ABSENT, exactement comme une source
coupée. Fabriquer un SVS depuis un tape rejoué aurait été le chiffre inventé qui a l'air d'une
mesure (§3). **Un replay dit ce qu'il sait et se tait sur le reste** — et le canal LENT n'écrit
rien du tout.

### 3. Trois choix qui protègent l'opérateur
- **La source s'ANNONCE** : nom `replay` (et non `sierra_chart`), drapeau `REPLAY` sur chaque
  écriture, avertissement au démarrage. Un replay qui se fait passer pour du direct est le pire
  état possible de ce terminal. Vérifié bout à bout jusqu'au SSE : `freshness FRESH · source
  replay · flags ['REPLAY']`.
- **Horodatages REBASÉS sur maintenant**, écarts du fichier préservés. Publier les horodatages
  bruts d'une séance ancienne ferait tout juger périmé — le terminal afficherait ABSENT partout.
  Le décalage appliqué est exposé dans l'état, jamais tu.
- **Profondeur inconnue ≠ carnet vide** (D-055) : si `bid_vol`/`ask_vol` manquent, **aucun**
  `order_book` n'est publié. Un carnet à zéro annoncerait une absence de liquidité jamais
  observée. Le `TypedDict Tick` rend ces deux champs `Optional` **par le type**, donc le
  vérificateur l'impose à tous les consommateurs, pas seulement aux tests.

### Contrôle — et ce qu'il refuse
`GET/POST /replay` : play · pause · restart · speed · seek (position / ts / fraction).
- `speed=0` est **borné à 0.01**, pas accepté : ce serait une pause qui ne dit pas son nom, et
  l'UI afficherait « LECTURE » sur un flux arrêté.
- Le temps passé **en pause n'est pas rattrapé** : reprendre après dix minutes déverserait dix
  minutes de tape d'un coup.
- `seek` **remet le tape et le carnet à zéro** : les garder ferait cohabiter des prints des deux
  côtés du saut, et toute mesure de fenêtre (B1/B4) porterait sur un temps qui n'a jamais existé.
- Hors mode replay, les routes rendent **409 avec le motif**, pas 404 : un 404 ferait croire à
  une route absente alors que c'est le terminal qui n'est pas en replay.

### Typage strict — outillé, pas affirmé
`mypy --strict` introduit et **câblé dans `pyproject.toml` sur les modules concernés seulement**.
L'activer partout d'un coup produirait un bruit qu'on apprendrait à ignorer, ce qui est pire que
pas de vérificateur du tout. Il a trouvé **3 défauts réels dans le code neuf** (`dict` nus) que
la relecture n'avait pas vus. Résultat : `Success: no issues found in 5 source files`. Cinq
erreurs pré-existantes subsistent dans `config.py`/`redis_state.py` — hors périmètre, neutralisées
par un override explicite plutôt que masquées.

### Incident d'environnement (sans perte)
Le conteneur a été recyclé en cours de tâche : l'arbre local est revenu à `ebe5b9c` et le `.venv`
avait disparu. **Le distant portait `e62c26d`** — les dix commits de D-057 et l'Étape 1 étaient
intacts. Réaligné par `fetch` + `reset --hard` sur le distant, venv reconstruit ; rien n'a été
reconstruit à la main. C'est l'argument du « pousser tôt » qui a payé.

### Vérif
**44 tests** (18 moteur + 26 source) → **1073 passed**, ruff clean, mypy strict clean.
Essai réel : terminal démarré en `REPLAY_FILE=…` ×5, contrôle complet exercé par HTTP
(restart/pause/speed/seek/play), refus explicites sur les trois commandes incomplètes, et les
prints rejoués vérifiés jusqu'au canal SSE.

## D-069 · Une table de calibration PAR INSTRUMENT — la fin des seuils écrits deux fois

Les seuils microstructure du moteur LSR vivaient en scalaires `config.LSR_*`, alors que le
moteur de référence (`lsr-engine/src/config.ts`) les tient **par instrument**. Deux conséquences,
toutes deux mesurées :

1. **MNQ n'était pas représentable.** Un seuil unique force à choisir la valeur fausse pour l'un
   des deux : exiger 150 de profondeur top-3 sur MNQ (carnet plus fin) n'émettrait jamais rien ;
   tolérer 2 ticks de spread sur MES (carnet dense, 1 tick la quasi-totalité de la séance)
   laisserait passer des marchés disloqués.
2. **Deux valeurs divergeaient vraiment du moteur de référence** : `f4MaxSpreadTicks` (1 côté TS,
   2 côté Python) et `b1MinWallRefillRatio` (0.40 contre 0.50). Le Python refusait donc des murs
   que la référence valide, et acceptait des spreads qu'elle refuse.

`app/lsr_tuning.py` porte la table (MES + MNQ) et les `INSTRUMENT_SPECS` CME. Les neuf constantes
correspondantes ont **disparu** de `config.py` — un test le vérifie nommément, parce que le motif
qu'on corrige n'est pas « une mauvaise valeur » mais « la même valeur à deux endroits », qui finit
toujours par n'être corrigée qu'à un seul.

### Pas de variable d'environnement sur la table — délibéré
Un override d'environnement contournerait en silence le verrou de parité (D-072) : le Python
jurerait 0.40 pendant que la prod tournerait à 0.55, test vert. Recalibrer = éditer les DEUX
fichiers.

### Le mock était la vraie cause du seuil relâché
`LSR_F4_MAX_SPREAD_TICKS = 2` portait ce commentaire : « le mock émet un spread de 2 ticks ».
Autrement dit une frontière de risque avait été desserrée pour qu'une source d'essai mal calibrée
produise quelque chose. Le mock cote désormais **1 tick en régime normal** (bid et ask tous deux
sur la grille, le mid vivant sur un demi-tick), le spread élargi redevenant la pathologie
occasionnelle qu'il aurait toujours dû être. Mesuré sur 600 carnets : **497 à 1 tick**, 46 à 2,
41 à 4, 16 croisés/verrouillés ; F4 MES passe **39 %** du temps — c'est la profondeur qui est
désormais contraignante, pas le spread.

### /devil — le fail-closed silencieux
`LSR_INSTRUMENT` hors table rend `evaluate_lsr` définitivement muet. Correct, mais une faute de
frappe dans l'environnement ressemblerait exactement à « aucun setup aujourd'hui ». Le démarrage
du moteur le dit maintenant en ERROR, en nommant le coupable **et** les instruments admis.

### Vérif
11 tests neufs → **1302 passed**, ruff clean. Le stop reste pris à la borne HAUTE du buffer de
bruit (`sl_noise_buffer_max_ticks`) tant que D-070 n'a pas câblé sa version dynamique : c'est le
choix prudent (stop plus loin = moins de contrats, jamais plus).

## D-070 · Le modificateur VIX manquait tout court — et le stop A3 était figé

Deux des cinq divergences numériques annoncées se sont révélées différentes de leur étiquette.

### 1. Ce n'était pas « une borne à 20 », c'était un modificateur ABSENT
Le moteur de référence fait `contrats = floor(bruts × mult_VIX)`. Le `size_position` Python ne
l'appliquait **pas du tout** : taille pleine à VIX 28, là où la référence coupe de moitié. La
divergence de borne (0.75 contre 0.50 à VIX exactement 20.00) n'était que la partie visible.

`lsr_tuning.vix_multiplier` porte les paliers exacts. La borne de 20.00 est **exclusive** en haut
du palier 0.75 : le doc écrit « 15-20 » puis « 20-30 », 20 appartient aux deux — l'ambiguïté est
dans la SOURCE, pas dans le code. On tranche pour la lecture la plus serrée (§2.4), qui est aussi
celle du moteur TS. `sony.py` est aligné sur la même borne : deux paliers différents pour le même
VIX dans le même terminal seraient indéfendables devant l'opérateur.

**Fail-closed, et dans le bon sens** : un VIX absent, périmé ou non fini rend un multiplicateur de
**0**, pas 1.0. Un VIX qu'on ne voit pas n'est pas un VIX calme ; le repli inverse donnerait la
taille MAXIMALE exactement quand on est le plus aveugle.

Conséquence assumée : `size_plan` (le seul chemin d'émission) rend `None` sans VIX observable, et
le HUD affiche `VIX_BLIND` — motif **distinct** de `VIX_SUSPENDED`, parce que « je ne vois pas la
volatilité » et « elle est trop haute » appellent deux gestes différents (rebrancher un flux /
attendre). Le buffer, lui, reste affiché : il est toujours vrai.

Un test AST interdit à tout module de `app/` d'appeler `size_position` sans `vix=`. Sans lui,
l'oubli ne casserait AUCUN test — il rendrait juste des positions deux fois trop grosses, en
silence.

### 2. Le buffer de bruit A3 était une constante
`min(max, max(min, ceil(spread)) + (atr_rapide > atr_lent ? 1 : 0))`. Un stop qui ignore le spread
se fait sortir par le bruit qu'il est censé absorber. `_f4_liquidity` rend désormais le spread
qu'il a mesuré plutôt qu'un booléen : deux lectures du carnet, ce serait deux occasions de ne pas
parler du même carnet. Absence de spread ou d'ATR → **borne haute** : un stop plus loin, c'est
moins de contrats, jamais plus.

### 3. Le blackout news n'était PAS une divergence — refus argumenté
`f5DefaultBlackout*Ms` = ±2 min contre `MACRO_PAUSE_WINDOW_S` = 900 s. Ce sont deux portes :
- **±2 min** = F5 du moteur LSR. Côté Python : `NEWS_LOCK_BEFORE/AFTER_MIN` → `HARD_LOCK` →
  `evaluate_lsr` rejette. **Déjà aligné à la minute près.**
- **±15 min** = règle Phase 0 `MACRO_BLACKOUT` (D-040), qui gèle le Go/No-Go HUMAIN, et qui est
  strictement plus large donc plus prudente.

La ramener à 2 min « pour aligner » rouvrirait 13 minutes de part et d'autre de chaque NFP : un
DESSERRAGE de discipline déguisé en correction de parité. Les deux restent, et un test interdit
qu'on les confonde plus tard.

### Reporté à D-071, sciemment
`f7ResubmitLockoutMs` (900 s) n'est pas un nombre à changer : c'est une machine à états
(`rejectedSetupIds`, `lockoutUntil`) que le Python n'a pas. L'ajouter en constante seule aurait
produit un nombre mort. Il part avec F6.

### Vérif
19 tests neufs → **1332 passed**, ruff clean, mypy strict clean. Essai réel sur le stack de démo :
VIX 13.13 lu de bout en bout, ticket 53 contrats, `APPROVED`.

## D-071 · F2, les frontières de compte — et pourquoi F3-ATR ne peut PAS être câblée

Port de `lsr-engine/src/frontiers.ts` et des gates F2 / F3-ATR. Deux livrés, un refusé avec ses
chiffres.

### La divergence trouvée en portant — elle n'était dans aucune liste
`compute_buffer` calcule `equity − (day_start − DLL)`. Sur une matinée **gagnante**, ce terme vaut
`DLL + profit` : il dépasse le DLL. La référence, elle, plafonne l'allocation quotidienne au DLL
quoi qu'il arrive (`max(0, DLL − perte_du_jour)`).

À +500 $ sur un Apex 50K, le Python allouait `1500/5 = 300 $` de risque là où la référence alloue
`1000/5 = 200 $` — **50 % de plus, précisément après une bonne matinée**, c'est-à-dire au moment
où on se croit bon. `frontiere_jour_restante` fait foi pour le sizing depuis D-071.

`compute_buffer` survit et ce n'est pas un doublon : il est **signé**, donc il sait afficher
« tu es passé SOUS la ligne » (−500) là où la frontière bornée dirait « tu es dessus » (0). L'un
affiche, l'autre dimensionne, et un test balaye 14 combinaisons pour vérifier qu'ils ne peuvent
pas se contredire sur la seule question qui compte : reste-t-il de quoi trader ?

### F2 — le refus que le Python ne savait pas prononcer
Au-delà de 80 % de la frontière du jour consommée, la séance est finie. Avant, le sizer continuait
à sortir 2 contrats avec 100 $ de marge sur 1 000 : il a raison arithmétiquement, et tort
complètement. Quatre tests existants ont changé de verdict — c'est le signe que la règle mord.

Le motif est **distinct** d'`INSUFFICIENT_BUFFER` : « il ne reste pas de quoi faire un lot » et
« arrête-toi pour aujourd'hui » n'appellent pas le même geste, et le HUD doit les séparer.

### F3-ATR — écrite, testée, PAS câblée. Voici les chiffres.
La règle est portée (`f3_atr_blocked`, fail-closed sur ATR manquant — le piège est que
`None > None` est faux, donc une comparaison naïve laisserait passer une volatilité **jamais
mesurée** comme si elle avait été jugée calme).

Elle n'est pas branchée dans `evaluate_lsr`, et la raison est mesurée, pas supposée :

| observation | valeur |
|---|---|
| tampon de prints du footprint (`FOOTPRINT_MAX_PRINTS`) | 800 ≈ **80 s** de tape |
| bougies produites sur 400 ticks de démo | **1** |
| bougies requises pour un ATR-14 sur 60 s | **15** (~14 min d'historique) |
| snapshots bloqués si on branche la gate | **100 %** |

Cholismo **n'a pas d'ATR à donner à F3**. La brancher rendrait le moteur définitivement muet : un
fail-closed qui ne protège de rien puisqu'il refuse tout. Ce qui manque n'est pas la règle, c'est
une SOURCE (historique OHLC borné, indépendant du tampon d'affichage). Tranche séparée.

Un test verrouille ce raisonnement **et échouera** le jour où le tampon suffira — il rappellera
alors de câbler la gate. Un refus qui s'auto-annule quand sa cause disparaît.

### Restent à porter (item 2 du chantier de parité)
F6 (cooldown après 2 pertes), F7-resubmit (900 s), F8 (campagne : 0.6/0.8/24 h/3/10 trades), A5b
(confluence renforcée au 1er trade), scale-out (clip 50 %), prix d'annulation. Les quatre premiers
exigent un `LsrRuntimeState` que le Python n'a pas — il doit être une **projection** du Decision
Log (§2.5), pas un champ mutable. Les deux derniers sont purs et courts.

### Vérif
21 tests neufs, 4 tests existants mis à jour (F2 les fait changer de verdict) → **1353 passed**,
ruff clean.

## D-094 · F6 / F7 / A5b — et l'état d'exécution en PROJECTION, pas en champ

Priorité 1 de la feuille de route. Les règles qui empêchent de *mal* trader : verrou après deux
pertes (F6), fenêtre anti-FOMO (F7), confluence renforcée au premier trade (A5b).

### La décision structurante : projection, jamais un champ

`lsr-engine/src/types.ts` définit `LsrRuntimeState` et le fait **circuler** — chaque évaluation
rend un `nextState` que l'appelant reporte. Légitime en TS, où le moteur est une fonction pure
appelée en boucle.

Ici c'eût été une faute. `CLAUDE §2.5` : l'état courant est une **projection**. Un
`consecutive_losses` stocké serait une seconde vérité, qui dérive de la première au premier
redémarrage, au premier import de réconciliation, au premier event rejoué. `project_runtime_state()`
le **recalcule** depuis le journal à chaque appel. Coût assumé : ces règles s'évaluent à
l'armement, pas dans le hot path sous-seconde.

Deux tests verrouillent la propriété plutôt que le résultat : deux projections du même journal
sont égales, et **le nombre d'events ne bouge pas** — une projection qui écrit n'en est pas une.

### Quatre arbitrages, chacun contre une lecture fausse

1. **Série de pertes scopée à la SÉANCE.** Les pertes d'hier ne verrouillent pas ce matin. F6
   protège d'un enchaînement à chaud ; l'horizon long est F8, qui n'est pas porté. Les confondre
   donnerait un verrou qu'on ne saurait plus lever.
2. **Issue orpheline ignorée, pas comptée.** Une issue dont la décision est inconnue (import
   partiel, réconciliation bancale) ne doit ni verrouiller ni déverrouiller.
3. **`campaign_stop_until` ABSENT de la structure.** F8 dépend des `AccountFrontiers`, hors du
   journal. Un champ toujours à `None` se lirait « campagne saine » alors qu'il signifie « non
   mesuré » — la confusion exacte que §3 interdit. Il apparaîtra avec F8.
4. **F7 sans horodatage de sweep → REFUS.** Ne pas savoir depuis quand le setup existe n'est pas
   savoir qu'il est frais. Un `None` traité comme « âge zéro » ouvrirait la porte la plus large.

### F7-resubmit est porté à MOITIÉ, et le dit

La moitié FOMO est sans état : portée. La moitié *resubmit* a besoin de la liste des setups déjà
refusés — et **aucun event ne l'enregistre** : `DecisionEvent` porte un `window_id`, pas un
`setup_id`, et le journal des setups ne connaît que `setup_armed` / `setup_outcome`.

Rendre un tuple vide en le présentant comme « rien n'a été refusé » aurait donné une gate qui
passe toujours, indiscernable d'une règle qui marche. L'état porte donc
`resubmit_tracking_available: False` — le drapeau distingue « aucun refus » de « refus non
suivis » — et un test verrouille l'inertie *et* prouve que la logique mord dès que la donnée
existera.

### Verrou de parité (D-072) étendu au moteur LSR

`ts_engine_source()` lit `lsr-engine/src/` — **distinct** de `options_gates.ts_reference_source()`,
qui lit le Fast Engine v1.7 dans `/reference/v2/fast-engine/`. Deux paquets, deux autorités ; les
confondre ferait vérifier la parité contre le mauvais fichier, soit un verrou qui ne mord pas.

Vérifié que le verrou mord : `LSR_F6_COOLDOWN_MS = 999` → le test échoue. Les quatre seuils sont
lus dans le TS (900000 / 2 / 90000 / 900000), et les chaînes de `RejectReason` comparées à
`types.ts` — deux journaux qui nomment différemment le même refus ne se recoupent plus.

### Ce qui n'est PAS fait, et doit être dit

**Les trois règles ne sont appelées par aucun chemin d'armement.** Elles sont portées, testées,
verrouillées — pas branchées. Les poser dans `gates_journal.evaluate_at_arming()` aurait été une
erreur de catégorie : cette fonction est le chemin **consultatif** (G2, n'a aucun pouvoir de
blocage), alors que F6/F7/A5b sont des règles **bloquantes** du scanner déterministe.

Le point de couture est `LsrDriver`, qui reçoit un `evaluator` injecté et threade un `next_state`
— précisément la forme que §2.5 refuse. Réconcilier ce threading avec une projection est la
tranche suivante, et elle touche le chemin de décision : elle mérite son propre travail, pas une
fin de commit.

### Vérif
17 tests neufs → **1770 passed**, ruff clean, mypy 15 fichiers.

## D-093 · Le mock ne peut plus se faire passer pour un fournisseur réel

Défaut que j'avais introduit en D-091 : `.env.production.example` portait `MICROSTRUCTURE_SOURCE=rithmic`,
et cette variable **ne branche aucun connecteur**. Un opérateur suivant le template obtenait un
terminal entièrement simulé qui affichait « source : rithmic ».

### La cause racine était une ligne, pas une intention

`Engine._meta` affiche `raw["source"]` — l'étiquette apposée par le **writer**, pas celle du
registre. `FIELD_SPEC` ne sert que de repli quand le champ est ABSENT.

`ReplayDataSource` s'estampille honnêtement depuis toujours (`SOURCE_NAME = "replay"`), et
`options_worker.py` aussi (`source_vendor_name="mock"`). Seul `MockDataSource` **empruntait** le
nom configuré : `write_raw(field, value, config.MICROSTRUCTURE_SOURCE, …)`.

Reproduction avant correction — le défaut n'était pas cantonné à la microstructure :

```
étiquettes apposées : ['cboe', 'cme', 'econ_feed', 'fx_feed', 'greeks_engine',
                       'macro_feed', 'rates_feed', 'rithmic', 'rms_engine', 'sentiment_feed']
```

**Dix noms de fournisseurs, tous usurpables.** Ne corriger que `MICROSTRUCTURE_SOURCE` aurait
laissé neuf portes ouvertes — c'est pourquoi la correction porte sur `_emit`, pas sur un cas.

### Séparer l'IDENTITÉ de l'ÉTIQUETTE

Le piège de la correction évidente : renommer la source en `mock` cassait la coupure
(`source:{name}:up` dans Redis, bascules `/sources`, clés de `SOURCES`). Deux notions vivaient
dans une seule chaîne.

- **Identité logique** (`cboe`) — pilote la coupure et les bascules. Inchangée.
- **Étiquette de provenance** (`mock:cboe`) — ce que l'opérateur lit. Nouvelle.

`_emit` garde donc `source` comme **garde** et estampille `mock_label(source)`. Une ligne, plus
un helper idempotent. Aucun test existant cassé : rien dans le dépôt ne compare `raw["source"]`
à un littéral (la détection de contradiction DXY compare des **valeurs**, pas des noms).

### L'asymétrie faisait partie du défaut

Le rejeu criait `MODE REPLAY : les prints sont REJOUÉS, pas du direct`. Le mock, lui, **se
taisait**. Il a maintenant son avertissement symétrique au démarrage, qui dit aussi que
`MICROSTRUCTURE_SOURCE` ne branche rien.

### Essai réel, pas seulement des tests

Démarrage avec `MICROSTRUCTURE_SOURCE=rithmic` :

```
WARNING  MODE SIMULÉ : aucune source live — toute lecture est estampillée « mock:* ».
/state   svs_score  source='mock:rithmic'  FRESH
/sources ['rithmic', 'cboe', …]   toggle rithmic → {"ok":true,"up":false}
```

La provenance est honnête **et** la coupure marche encore. Les deux comptaient.

### Vérif
6 tests neufs (dont la reproduction, qui échoue sur le code d'avant) → **1753 passed**, ruff clean,
mypy 15 fichiers. Le garde anti-littéral de D-059 (`test_aucun_nom_de_plateforme_ne_reste_CODE_EN_DUR`)
reste vert : `mock:` est un préfixe, pas un nom de plateforme.

### Ce que ça ne corrige pas
`MICROSTRUCTURE_SOURCE` reste une étiquette sans connecteur — c'est le chantier P2 de la feuille
de route, pas celui-ci. La correction garantit seulement qu'aucune valeur simulée ne peut plus se
présenter comme une mesure.

## D-092 · Verrouiller les dépendances — et trois affirmations fausses que j'ai committées

Deux ajustements demandés (lock backend, typecheck frontend). En les faisant, j'ai découvert que
**trois affirmations que j'avais écrites la veille dans `ci.yml`, `HANDOFF.md` et le corps de la
PR #2 étaient fausses**. Elles passent en premier : le reste est de la plomberie.

### Les trois erreurs, et leur cause unique

| J'avais écrit | En réalité |
|---|---|
| « `frontend/` n'a pas de lockfile, `npm ci` échouerait » | `package-lock.json` est **suivi depuis `ad8b919`**, et `npm ci` marche |
| « aucun fichier de test frontend, `vitest run` ne trouverait rien » | **9 fichiers, 125 tests** — tous verts |
| « la CI a résolu des dépendances plus récentes que mon venv local » | **versions identiques**, à la patch près |

Une seule cause. J'ai lancé les commandes de constat (`ls package-lock.json`, `find src -name
"*.test.*"`) **en parallèle d'un autre appel qui changeait de répertoire**, sans ancrer le leur.
Elles se sont exécutées depuis `backend/`, ont répondu « rien ici », et j'ai lu cette réponse
comme un fait sur `frontend/`. Pour la troisième, je n'ai même pas lancé de commande : j'ai
comparé le journal de la CI à un souvenir.

C'est la faute de D-077, D-085 et D-090 sous une forme nouvelle : là je supposais une structure
au lieu de l'ouvrir, ici j'ai **ouvert la mauvaise porte et cru la réponse**. Une commande
relative dont le répertoire n'est pas ancré ne mesure pas ce qu'on croit. La règle qui en sort :
un constat qui sert de fondement à une affirmation écrite s'ancre en absolu, et se relit avec son
`pwd`.

Le pire n'est pas de m'être trompé — c'est que les trois erreurs allaient **dans le sens du
confort** : elles justifiaient de ne pas câbler de CI frontend. Une erreur qui vous dispense de
travail mérite une seconde vérification, pas une première.

Corrigé dans les trois artefacts, avec la correction visible plutôt que réécrite en silence.

### Ce que le frontend vaut réellement

`frontend/src/` : **125 tests verts** (9 fichiers) et `tsc --noEmit` en `strict` — vérifié
`--listFiles` : les **81** fichiers de `src/` sont bien traversés. Un typecheck qui compile zéro
fichier passe aussi ; il fallait les compter avant de parler.

Ce que ça **ne** couvre pas, et qui reste l'unique point ouvert de P4 : `frontend/public/v17/`
(maquette + `live.js`) n'est atteinte **ni par `tsc`** (hors de `include: ["src"]`) **ni par
aucun test**. Le navigateur reste le seul juge. Aucun job de CI ne prétend le contraire.

### Le typecheck est BLOQUANT, pas « optionnel »

La demande disait « étape `tsc --noEmit` optionnelle ». L'optionnel se justifiait tant qu'on
ignorait le résultat. Je l'ai lancé : **vert**. Un test vert qu'on rend incapable d'échouer ne
protège plus de rien — c'est le feu vert décoratif que ce dépôt refuse partout ailleurs. Les deux
étapes frontend sont donc bloquantes, comme les trois du backend.

### Le verrou

`backend/requirements.lock` — `pip freeze` de l'environnement exact prouvé vert (63 paquets).
`requirements.txt` reste la **déclaration d'intention** (bornes larges, lisible) ; le lock est la
**résolution figée** que la CI installe. Les deux se lisent ensemble : l'intention et le fait.
Le frontend avait déjà son verrou — la CI passe simplement de rien à `npm ci`.

Un run rouge doit toujours désigner le code, jamais le calendrier des releases amont.

### Vérif
Backend : ruff clean, mypy 15 fichiers, **1747 passed**. Frontend : `tsc` vert sur 81 fichiers,
**125 passed**. Lock : `pip install --dry-run -r requirements.lock` sans erreur.

## D-091 · Briques de production — et les identifiants que je REFUSE de mettre dans le template

Trois livrables demandés : `.env.production`, résilience du mode dégradé, `OPERATING_MANUAL.md`.
Le deuxième était en grande partie déjà tenu ; le premier m'a fait buter sur une demande que je
n'ai pas honorée telle quelle.

### 1. Les identifiants courtier ne sont pas dans le template — c'est délibéré

La demande listait « Rithmic, ThetaData, Unusual Whales, **Brokers** ». Les trois premiers sont
des **sources de données** : ils entrent. Le quatrième est un **chemin d'exécution** : il sort.

`CLAUDE §2.1` : « Aucune exécution automatique d'ordre. » Aucun module de ce dépôt ne parle à un
courtier, et deux tests de garde l'interdisent explicitement (`broker`, `submit_order`,
`requests`, `socket` refusés dans la source d'`execution_sim` et de `replay_harness`).

Poser `BROKER_API_KEY=` dans un template de production ne casse rien aujourd'hui — et c'est
précisément le piège. La prochaine personne qui lit ce fichier en conclut qu'un chemin
d'exécution existe quelque part, et le cherche. Une variable d'environnement est une
**affordance**, pas une donnée inerte : elle annonce une capacité. Le jour où l'exécution
automatique sera décidée, ce sera un ADR (`docs/adr/`), pas une ligne ajoutée en silence.

Le refus est **écrit dans le template lui-même**, en tête, avec sa raison. Le taire aurait laissé
croire à un oubli.

Rithmic / ThetaData / Unusual Whales y sont, mais marqués **inertes** : aucun module ne les lit
aujourd'hui (`options_worker.py` tourne sur `MockVendorClient`, le connecteur Rithmic n'existe
pas — D-083). Une clé renseignée ne branche rien ; il faut implémenter le `Protocol`. Une
variable qui a l'air de suffire alors qu'elle ne suffit pas est exactement le « stub qui feint de
fonctionner » que les règles interdisent.

### 2. Résilience — le superviseur tenait déjà, la PROJECTION mentait

Vérification avant d'écrire : le superviseur survit déjà à une boucle qui meurt (prouvé en
D-075 — `options.sync` à `STALLED`, `fail=35`, les autres `RUNNING`). Chaque tick est isolé
(D-073). Il n'y avait rien à durcir de ce côté, et ajouter un filet par-dessus aurait été du
théâtre.

Le vrai défaut était **au-dessus** : `unhealthy` confondait deux choses opposées.

- `core.tick` en `NOT_IMPLEMENTED` — **attendu**, documenté, aucune action.
- `options.sync` en `STALLED` — **anormal**, il faut agir.

Les deux atterrissaient dans la même liste. Un opérateur qui voit `unhealthy: [...]` à chaque
démarrage apprend à l'ignorer — et le jour où quelque chose casse vraiment, il l'ignore aussi.
Une alerte qui crie toujours est une alerte éteinte.

`health.project()` publie donc un bloc `degraded` : `broken` (STALLED/DEAD), `stopped`,
`expected` (NOT_IMPLEMENTED), `hot_path_broken`, et un `verdict` unique —
`HOT_PATH_DOWN` > `DEGRADED` > `PARTIAL` > `NOMINAL`. `PARTIAL` est l'état **normal** du système
aujourd'hui. `unhealthy` et `all_healthy` restent inchangés : aucun consommateur cassé.

### 3. `OPERATING_MANUAL.md` — et un chapitre qui dit « rien à faire »

La demande incluait « bascule manuelle en mode consultatif ». Il n'y a **rien à basculer** : O1-O5
sont consultatifs **par construction** (`COMMANDS.md` §2) — aucun évaluateur ne retourne de
booléen, aucun ne lève, l'entrée de journal n'a ni `blocked` ni `allowed`. Il n'existe aucun
chemin de blocage à désactiver.

Écrire une procédure factice pour honorer la ligne de la demande aurait fabriqué un geste inutile
qu'un opérateur tenterait sous stress. Le chapitre existe donc, et explique pourquoi il est vide.

Ce qui bloque — les 30 contrôles déterministes LSR et Phase 0 — **ne se désactive pas**. C'est le
point du système (`CLAUDE §6` : la discipline est dans l'infra, pas dans la volonté).

Le reste est court par construction : un manuel lu à 09h35 marché ouvert tient en quelques lignes
par situation. Redémarrage en une ligne, triage par boucle, flush Redis (jamais le journal —
immuable par triggers SQLite), et un rappel en tête : le terminal ne passe aucun ordre, donc
aucune panne de ce manuel ne peut provoquer un trade.

### Vérif
4 tests neufs sur le verdict → **1747 passed**, ruff clean. Un test de cadence
(`pas_de_rafale_de_rattrapage`) s'est révélé fragile sous charge parallèle : vérifié 3/3 isolé,
puis rendu robuste (il refuse une **série** de ≥3 intervalles serrés, pas un intervalle isolé —
c'est la rafale qui est interdite, pas le jitter de l'ordonnanceur).

## D-090 · Les conteneurs dedies — ma cartographie d'IDs etait fausse, pas approximative

`frontend/public/v17/live.js` n'ecrit plus dans AUCUN element de la maquette, sauf `#px` dont
j'ai legitimement remplace le generateur. Syntaxe validee (`node --check`), backend 1743 verts.

### Les deux suspects etaient confirmes — et il y en avait un troisieme

J'avais signale deux risques. La lecture du HTML les a confirmes, et en a revele un de plus que
je n'avais pas vu :

1. **`#g4` est la BARRE de la jauge B4** (`<i style="width:28%">`), pilotee par `ofWidgets()` via
   `g.style.width`. Y ecrire du texte detruisait la jauge.
2. **`#p6` est la SECTION ENTIERE** de l'onglet « Backtest & Monte-Carlo »
   (`<section class="panel" role="tabpanel">`). Mon `innerHTML` l'aurait **rasee** — rejeu,
   Monte-Carlo, grille de resilience compris. Bien pire que « pourrait ne pas marcher ».
3. **`#w1`-`#w4` et `#s1`-`#s3` sont les widgets B1-B4 de l'order flow**, deja vivants :
   « B1 · rechargement du mur », « B2 · bascule du tape », « B3 · CVD normalise », « B4 · vitesse
   d'agression », avec leurs sparklines. Je les ecrasais tous les sept.

### Ce n'etait pas deux erreurs, c'etait une methode fausse

J'avais **deduit** une cartographie d'identifiants au lieu de la **lire**. Corriger `#g4` et
`#p6` un par un aurait laisse la cause intacte — et les cinq autres collisions en place.

La correction porte donc sur la methode : `live.js` **cree ses propres conteneurs** (`#cho-live`,
`#cho-opt`, `#cho-o5`, `#cho-loops`, `#cho-blotter`), inseres a cote de l'existant, jamais a sa
place. Le bandeau s'ajoute apres `header.topbar` ; le blotter s'insere SOUS `#jTable`, qui n'est
plus que **lu** comme ancre. Verifie : les seuls selecteurs ecrits sont `#cho-*` et `#px`.

La palette est empruntee aux variables CSS de la maquette (`--bias-up`, `--gold`, `--rust`) avec
repli — on emprunte sa charte, on ne la redefinit pas.

### Ce que ca dit du reste

Trois fois aujourd'hui l'essai reel a trouve ce que les tests avaient manque ; ici c'est la
simple LECTURE du fichier qui a suffi. Je ne l'avais pas faite avant d'ecrire — c'est la meme
faute que le chemin du tape (D-077) et le parseur de calendrier (D-085) : supposer une structure
au lieu de l'ouvrir.

Le reste reste NON VERIFIE : `node --check` valide la syntaxe, pas le rendu. Le test navigateur
de l'operateur demeure le seul juge.

## D-089 · Les generateurs factices de la maquette, remplaces par du reel

`frontend/public/v17/` — carnet, tape et heatmap consomment desormais le canal `fast`.
**Zero `Math.random()` restant.** Syntaxe des deux fichiers validee par `node --check`.

### Du reel, pas des tirets

Le backend publie deja `order_book`, `tape` et `liquidity_heatmap` sur le canal `fast` : il n'y
avait aucune raison de se rabattre sur des tirets. La maquette lit un magasin partage
(`window.CHOLISMO_LIVE`) alimente par `live.js` — elle ne connait pas SSE, elle lit un objet.

**Seul le FRESH passe.** Un carnet perime affiche comme courant annoncerait une liquidite qui
n'est plus la ; il devient `null`, et l'ecran montre des tirets.

### `null` n'est pas `0`, jusque dans le DOM

`domSize()` rend `null` — jamais 0 — quand le carnet n'est pas publie ou ne porte pas ce niveau.
Un 0 annoncerait une absence de liquidite OBSERVEE, alors qu'on n'a rien observe du tout. La
barre de volume disparait avec la valeur : pas de barre a largeur nulle qui suggererait une
mesure.

Meme logique pour le tape : sans print neuf, `ofTrade()` rend `null` et **le tape ne bouge pas**.
Une maquette qui continue de defiler sur un flux mort est le pire des affichages — elle a l'air
vivante. L'immobilite est la verite.

### Ce qui reste NON VERIFIE

`node --check` valide la **syntaxe**, pas le comportement. Ni `vitest` ni un `tsc` epingle ne
sont disponibles (npm hors ligne), et la page n'a jamais ete ouverte. Les selecteurs (`#w1`,
`#p6`, `#jTable`…) sont deduits de la lecture du HTML, pas observes a l'ecran : c'est
precisement le genre d'hypothese que trois essais reels ont invalidee aujourd'hui (D-077, D-085,
D-086).

L'operateur teste la page ; les corrections viendront de ce qu'il observe, pas de nouvelles
suppositions empilees.

## D-088 · P4 — le dashboard v17 raccorde au backend

Endpoints `/setups`, `/setups/calibration`, `/loops/health` (9 tests) + maquette v17 versionnee
sous `frontend/public/v17/` avec son generateur de prix remplace. 1743 verts.

### Ce qui est VERIFIE, et ce qui ne l'est pas

**Verifie** : les trois endpoints, par tests et par appel reel sur un backend demarre.
`/loops/health` rend bien les cinq boucles avec leur statut ; `/setups` rend un blotter vide sans
lever.

**NON verifie** : le fichier `live.js` n'a jamais tourne dans un navigateur. `vitest` et un `tsc`
epingle sont absents de l'environnement (npm hors ligne, meme cause que pour `lsr-engine` en
D-076). Il est ecrit avec soin mais reste a corriger au premier lancement reel. C'est ecrit en
tete du fichier, pas seulement ici.

Trois fois dans cette session, l'essai reel a trouve ce que les tests avaient manque (D-077,
D-085, D-086). Livrer du code navigateur sans pouvoir l'ouvrir contredit cette lecon — la
livraison est donc **explicitement marquee comme non verifiee** plutot que presentee comme finie.

### Pourquoi un instantane REST en plus du canal SSE

Le canal `options` ne pousse `loops_health` que sur **changement d'etat** (dirty flag, D-075), et
ne pousse pas le blotter du tout. Un client qui vient de se connecter resterait donc vide jusqu'au
prochain changement — potentiellement plusieurs minutes sur un systeme sain. `/loops/health` et
`/setups` servent cet instantane initial ; le SSE prend le relais ensuite.

`/loops/health` sans superviseur rend une **503**, pas un « tout va bien » : ne pas savoir n'est
pas etre sain (§3).

### Les trois regles portees jusqu'a l'ecran

Le back-end passe sa journee a distinguer « pas de donnee » de « donnee nulle ». Un ecran qui
affiche `0` sur une mesure absente annule tout ce travail. `live.js` porte donc :

1. **Aucune valeur inventee** — sans backend joignable, les champs affichent `—`, jamais une
   derniere valeur figee ni un zero ;
2. **La peremption se VOIT** — `OK / STALE / VENDOR_DOWN / UNAVAILABLE` sont rendus distinctement ;
   un contexte `STALE` n'affiche pas ses niveaux comme s'ils etaient frais. `NOT_IMPLEMENTED`
   reste **non sain** a l'ecran, comme cote backend : une capacite annoncee et absente n'est pas
   un etat neutre ;
3. **Le rendu est CADENCE, pas evenementiel** — les messages SSE marquent « sale », le DOM se
   redessine a 250 ms (RUNTIME_LOOPS Loop B). Redessiner a chaque message ferait battre l'ecran
   au rythme du reseau.

Une trame malformee est ignoree SEULE : l'ecran garde son etat, il ne se vide pas et ne crashe
pas. Une coupure SSE declenche une reconnexion differee (2 s) plutot qu'un martelage.

### La maquette : design conserve, source remplacee

`COMMANDS.md` §4 exige de conserver l'IHM v17 a 100 %, en precisant que « conserver » signifie
garder le **design** en remplacant les generateurs `Math.random()` par des flux reels. Seul le
bloc `PRIX SIMULE` a ete neutralise ; aucun style, aucun layout, aucune structure DOM n'a bouge.

**Six occurrences de `Math.random()` subsistent** (carnet, tape, heatmap de la maquette) : elles
alimentent des panneaux dont le backend ne publie pas encore l'equivalent sur le canal `options`.
Les remplacer par du vide serait pire que les laisser — mais elles restent **de la simulation
affichee comme reelle**, et c'est le prochain chantier de P4, pas un detail cosmetique.

## D-087 · Le declencheur LSR devient MICROSTRUCTUREL PUR — et l'order flow est mesure

`backend/app/mbo/micro_sweep.py` + order flow cable dans l'adaptateur. 17 tests. 1734 verts.

### L'erreur de categorie, tranchee

J'utilisais `SWEEP_GRAPH` comme declencheur d'armement LSR. Ce graphe definit un sweep comme
« anomalie microstructure **COUPLEE a une news Tier-1 imminente** » (±30 min), et sa propre
docstring precise qu'il n'emet **qu'une alerte** a afficher, jamais un ordre.

| | `SWEEP_GRAPH` (D-028) | LSR — Liquidity Sweep **Reversion** |
|---|---|---|
| News | **prerequis de declenchement** (ET) | **filtre de blocage** en aval (F0/F5) |
| Sortie | affichage / scoring async | armement d'un setup |

Consequence : le rejeu n'aurait mesure que les balayages survenus a ±30 min d'une publication —
pas la population de setups LSR. Arbitre par l'operateur : **declencheur microstructurel pur, la
news redevient un filtre**.

`micro_sweep.detect()` declenche sur rafale de tape OU spread anormal, sans aucune notion de
calendrier — verifie par introspection de sa signature. Les **seuils sont IMPORTES** de
`liquidity_sweep`, jamais recopies : deux detecteurs regardant la meme microstructure avec des
constantes dupliquees divergeraient au premier ajustement.

**La direction se lit sur le cote CONSOMME.** Vendeurs dominants → les bids sont manges →
`BID_SWEEP` → reversion **acheteuse** (`is_long = direction == "BID_SWEEP"`). Se tromper de sens
inverserait tous les trades du rejeu sans qu'aucun test d'usage ne tombe. Une anomalie **sans
cote dominant** ne produit aucune direction plutot qu'un tirage au sort.

### L'order flow est desormais MESURE, pas absent

`snapshot_for_lsr` — le MEME calcul que le moteur live — alimente `absorption` et
`aggressor_ratio`, et le snapshot complet est passe a `build_lsr_inputs`. Chacun ne s'ecrit que
s'il a ete reellement mesure : `None` reste ABSENT, jamais un zero qui se lirait « aucune
absorption » alors qu'on n'a rien mesure.

### Deux contraintes STRUCTURELLES decouvertes, pas des bugs

Le calculateur les nomme lui-meme dans `snapshot.missing` :

1. **B1 exige au moins deux observations du niveau.** Je ne poussais l'historique de carnets qu'a
   l'armement — B1 etait donc structurellement non mesurable. L'historique s'alimente desormais a
   **chaque evenement**.
2. **B4 mesure l'agression APRES le balayage.** A l'instant du sweep, 0 s se sont ecoulees : la
   mesure est impossible par construction. Le moteur live y remedie par sa cadence de tick ; en
   rejeu, le balayage est garde **EN ATTENTE** et reevalue sur les evenements suivants, puis
   **EXPIRE** au-dela de `LSR_SWEEP_MAX_PENDING_S` — un setup arme sur un balayage d'il y a une
   minute n'est plus celui qu'on avait detecte.

### Etat verifie sur flux synthetique

Balayage detecte (`BID_SWEEP`, sens correct), 38 balayages sur une seance simulee de 25 min,
120 carnets historises, 25 barres ATR closes, B2 et B3 calcules. La chaine tourne de bout en bout.

**Aucun setup ne s'arme encore, et la cause est mon GENERATEUR** : ses barres sont degenerees
(amplitude nulle → `atr_fast = 0.0`) et 25 minutes ne suffisent pas a l'ATR lent, qui en exige
50. Aucune donnee synthetique ne fermera ce point — et c'est tant mieux : un generateur capable
d'armer des setups mesurerait le generateur.

## D-086 · La passe relancee — deux bugs qui rendaient tout sweep IMPOSSIBLE

Correctifs dans `mbo/book.py` et `mbo/lsr_adapter.py`. 7 tests de regression. 1717 verts.

### Ce que la passe a revele

Relancee avec le VPOC cable, la passe rendait toujours 0 setup — et surtout
`refuses (post-sweep) = 0` : le detecteur de sweep ne s'etait **jamais** declenche. Le pipeline
n'atteignait donc meme pas `evaluate_lsr`. Un flux MBO synthetique concu pour declencher un
balayage a permis d'isoler deux causes, toutes deux dans MON code.

### Bug 1 — le cote passif resolu APRES la mutation du carnet

L'adaptateur re-resolvait le cote passif de chaque transaction en interrogeant le carnet… qui
venait deja d'appliquer cette transaction. Pendant un **balayage** — l'evenement qu'on cherche
precisement a detecter — les niveaux consommes disparaissent, et les transactions suivantes
tombent « dans le spread » du carnet post-trade : rejetees comme inresolvables.

Mesure : **14 transactions ne produisaient que 2 prints**. Donc aucune rafale de tape, donc
aucun sweep, donc aucun setup. Le detecteur etait structurellement aveugle a l'evenement qu'il
existe pour voir.

Le carnet resout deja le cote correctement, AVANT de muter (D-079). Il memorise desormais ce
resultat (`last_trade_passive_side`) et l'adaptateur le lit au lieu de re-deviner. Apres
correction : **14/14 prints, 0 transaction non resolue, `tape_burst = True`.**

Corollaire : le detecteur depend maintenant de l'ordre « carnet d'abord, detecteur ensuite » —
l'ordre que le harnais applique deja. Quatre tests l'ignoraient et passaient a cote ; ils
nourrissent desormais le carnet, comme la realite.

### Bug 2 — le calendrier « charge mais vide » n'etait pas publie

`build_sweep_inputs` exige `data_ok = (spread ou tape frais) ET calendrier frais`. Ma jointure
(D-084) ne publiait `econ_calendar` **que s'il contenait des evenements**. Une fenetre sans
publication laissait donc le champ ABSENT, `data_ok` restait faux, et **aucun sweep ne pouvait
jamais se declencher** — meme avec un contexte parfaitement charge.

C'est exactement la lecon deja payee dans l'artefact (`CLAUDE` v1.7 §5) : « un tableau vide est
ambigu (« rien aujourd'hui » ou « chargement echoue »)… sans ce champ, M1 est fail-OPEN, c'etait
un vrai bug ». Ici l'effet etait inverse — fail-CLOSED permanent — mais la cause identique :
confondre « charge et vide » avec « pas de source ».

Un contexte fourni signifie que le calendrier a ete charge : le champ est desormais publie FRESH
**meme vide**. Sans contexte, il reste ABSENT — la distinction est conservee, et testee.

**Bug 2 bis** : la jointure ecrivait `tier1` (booleen) la ou le graphe lit `tier` (entier). Un
nom de champ qui diverge ne casse aucun test unitaire — il rend la news invisible en silence.

### Etat apres correctifs

Sur flux synthetique realiste : `SWEEP declenche : True — TAPE_BURST+WIDE_SPREAD couple a une
news T1 imminente`, puis **13 refus post-sweep**. La chaine atteint donc `evaluate_lsr`, qui
refuse pour une autre raison.

**Ce n'est PAS F0** : avec la news placee a +15 min (hors blackout −5/+2), l'etat vaut `SAFE` et
les refus persistent. Les entrees restantes non alimentees par l'adaptateur sont `absorption` et
`aggressor_ratio` (bloc `s1_state.order_flow`), plus le parametre `orderflow` de
`build_lsr_inputs` — que l'adaptateur ne passe pas. Toutes trois sont derivables du flux via
`compute_snapshot` (prints + carnets + barres), deja present au depot. C'est le prochain
increment, et le dernier avant qu'un setup puisse s'armer en rejeu.

### Tension structurelle a trancher (pas un bug)

Le graphe `SWEEP_GRAPH` definit un sweep comme « anomalie microstructure **COUPLEE a une news
Tier-1 imminente** » (±30 min), et sa propre docstring precise qu'il n'emet **qu'une ALERTE**,
jamais un ordre. Or LSR (Liquidity Sweep **Reversion**) traite un balayage de liquidite comme un
evenement de microstructure, sans exigence de news.

Utiliser ce graphe comme declencheur d'armement LSR est peut-etre une erreur de categorie de ma
part : les deux notions portent le meme nom et ne designent pas la meme chose. A trancher avant
la passe reelle — sinon le rejeu ne mesurera que les balayages survenus a ±30 min d'une news
Tier-1, ce qui n'est pas la population de setups LSR.

## D-085 · Extracteur historique — et deux erreurs de ma part corrigees

`backend/app/mbo/build_context.py` (26 tests) + VPOC derive du flux + reclassement de
`svs_score`. Suite complete : 1713 verts.

### `svs_score` n'etait PAS une dependance du LSR — erreur de ma part (D-083)

En lisant `build_lsr_inputs`, la chaine LSR consomme : le sweep, les prints, `absorption`,
`aggressor_ratio`, le carnet, **`vpoc`** et l'order flow. **`svs_score` n'y figure pas** — c'est
une entree de la strategie SVS de Sony, un autre systeme.

Je l'avais inscrit en D-083 dans `MISSING_FROM_MBO`, ce qui envoyait l'operateur chercher une
donnee dont le moteur LSR ne veut pas. Retire.

En revanche `vpoc`, lui, **est** lu par le moteur et n'etait **pas** alimente par l'adaptateur :
le refus venait de la, pas de `svs_score`. Il se derive du flux (volume par niveau accumule sur
les transactions rejouees, puis `build_volume_profile` — le MEME calcul que le moteur live ; en
reecrire un ici ferait deux POC pour un seul marche). La grille est bornee par
`VP_MAX_LEVELS`, comme celle du moteur.

`MISSING_FROM_MBO` est desormais **vide** : plus rien ne manque structurellement au rejeu.

### L'horodatage du VIX — le point qui decide si la jointure est honnete

`VIXCLS` est une serie de **clotures quotidiennes**. Une cloture du 3 mars n'est connue qu'apres
la cloture du 3 mars : la dater a 00:00 la rendrait disponible toute la seance qu'on rejoue, soit
un lookahead d'une journee entiere, invisible dans le fichier produit. Chaque observation est donc
horodatee a la **cloture du cash US (16:00 ET)**, l'instant ou elle devient reellement connue.

Verifie bout en bout : a l'ouverture du 14, `vix_at()` rend la cloture du **13**.

Les jours feries (« . » chez FRED) sont **ecartes**, jamais combles par la veille — combler
fabriquerait une observation qui n'a jamais eu lieu. `--pad-days` remonte quelques jours en amont,
sans quoi la jointure n'aurait rien a rendre sur les premieres minutes de seance (elle ne regarde
jamais devant).

### Trois bugs dans MON extracteur, trouves a l'essai reel

Les 22 tests initiaux passaient tous. Ils ne couvraient que le calendrier **vide**.

1. **`CalendarEvent` est un DICT, pas un objet.** `getattr(ev, "ts", None)` rendait `None` pour
   chaque entree — **tous** les evenements d'un flux Finnhub parfaitement valide etaient jetes.
2. **`tier1` n'existe pas** sur `CalendarEvent` : la severite se lit sur `impact`, que le parseur
   a deja promue pour les publications sensibles a impact absent.
3. **`None` et `[]` etaient confondus.** Le parseur les DISTINGUE : `None` = flux illisible ou
   empoisonne, `[]` = flux lisible et vide. Les confondre ecrivait un calendrier vide sur une
   reponse corrompue — un fichier de contexte d'allure normale sur des donnees jamais lues. Et
   iterer `None` aurait leve.

Quatre tests de regression ajoutes, dont celui qui manquait : **un calendrier NON vide**.

### Ce que l'extracteur refuse de faire

Une fenetre incomplete est **rapportee**, pas completee. Un calendrier vide est signale avec ses
**deux causes possibles** — « aucun evenement ce jour-la » et « l'historique n'est pas servi par
ce plan Finnhub » se ressemblent dans la reponse, pas dans les consequences. Et dans tous les
cas la jointure reste fail-closed : sans calendrier, `news_state` vaut `None` et F0 refuse. **Un
calendrier vide ne fabrique jamais un `SAFE`.**

La provenance accompagne le fichier (serie interrogee, convention d'horodatage, avertissements) :
un contexte silencieusement incomplet produirait une passe de calibration d'allure normale sur
des donnees trouees.

## D-084 · Joindre VIX, calendrier et ATR au rejeu — sans ouvrir la porte au lookahead

`backend/app/mbo/session_context.py`, jointure branchee dans `MboLsrDetector`, option
`--context` de la passe de calibration. 24 tests.

### Le risque de cette feature n'est pas qu'elle echoue

C'est qu'elle **reussisse trop bien**. Une jointure negligente injecte des donnees du futur, les
gates s'ouvrent, les setups s'arment, les chiffres deviennent excellents — et faux. L'ordre des
tests suit donc cet ordre de risque : d'abord l'absence de lookahead, ensuite la peremption,
ensuite seulement le fonctionnement nominal.

### Pourquoi `app/external/` ne peut PAS etre appele tel quel

`FredVix.fetch(now=…)` et `FinnhubCalendar.fetch(now=…)` interrogent une API **au present**.
Rejouer une seance du mois dernier en appelant `fetch()` injecterait le VIX **d'aujourd'hui**
dans une seance d'alors. C'est la forme la plus couteuse du lookahead parce qu'elle est
invisible : les chiffres sont reels, ils sont simplement de la mauvaise date.

La jointure lit donc une **serie historique fournie** (`--context`), point-in-time : a l'instant
`t`, on ne voit que ce qui etait **deja publie** a `t`. Comparaison sur `ts <= t` — une valeur
publiee exactement a `t` est connue a `t`. Un test verifie qu'une valeur de `t+100` n'est jamais
rendue a `t`, et un autre que « la plus proche » ne l'emporte pas sur « la derniere publiee »
(a `t+900`, entre une valeur a `t` et une a `t+1000`, c'est celle de `t` qui sort).

### Trois provenances, tenues distinctes

| Provenance | Entrees | Pourquoi |
|---|---|---|
| **du FLUX** | ATR | Se derive des barres de la seance rejouee. Une source externe produirait des barres qui ne coincident pas avec celles qu'on mesure — deux verites sur le meme instrument. |
| **du CONTEXTE** | VIX, calendrier, etat F0 | Joints point-in-time depuis une serie fournie. |
| **de nulle part** | `svs_score` | Un score de STRATEGIE calcule en amont, pas une donnee de marche. Le fabriquer reviendrait a reimplementer une strategie pour pouvoir la mesurer. |

Le diagnostic de la passe imprime desormais les trois listes : ce qui est joint, ce qui est
derive, ce qui reste absent.

### Le calendrier a le droit de regarder devant, le VIX non

Distinction qui merite d'etre ecrite parce qu'elle ressemble a une incoherence. Un calendrier est
**annonce a l'avance** : ses entrees futures sont legitimement connues — c'est tout l'interet de
F5, qui protege d'une publication A VENIR. Le lookahead y porterait sur le CONTENU (un resultat
publie apres `t`), pas sur la date. Le VIX, lui, est une observation : une valeur posterieure a
`t` n'etait pas connue a `t`, point.

### La peremption reste la peremption

Un VIX de la veille n'est pas le VIX de la seance. Au-dela de `VIX_MAX_AGE_S` (24 h,
PLACEHOLDER), la valeur devient ABSENT au lieu de se trainer. Et sans serie fournie, rien n'est
ecrit : injecter « VIX = 15 parce que c'est une valeur courante » fabriquerait le contexte qu'on
pretend mesurer.

### Ce que la jointure change pour F0

Sans calendrier, `news_state` restait `None` — fail-closed sur l'inconnu (D-050), donc refus
systematique. Avec un calendrier date, la porte peut enfin repondre `SAFE` **en connaissance de
cause**, et `HARD_LOCK` dans la fenetre de blackout Tier 1. L'etat issu du contexte **prime** sur
la valeur passee a la construction : celle-ci n'est qu'un defaut pour les rejeux sans calendrier,
et la laisser gagner ferait ignorer un blackout reel.

### Ce qui reste

Les gates peuvent desormais etre alimentes, mais **aucun setup ne s'arme encore sur la fixture** —
7 evenements synthetiques ne produisent ni sweep ni ATR (0 barre close). Ce n'est pas un defaut
de la jointure : c'est l'absence de donnees reelles, que la passe rapporte ligne par ligne.

## D-083 · Le detecteur LSR branche sur le flux MBO — un seul moteur, deux sources

`backend/app/mbo/lsr_adapter.py`, detecteur branche dans `app.calibration`. 16 tests.

### Projeter, pas reimplementer

Le point d'armement lisait le `ContextSchema` alimente par le moteur live ; le harnais de rejeu
reconstruit un carnet depuis un flux MBO. L'adaptateur fait le pont **dans le sens qui ne
duplique rien** : il projette l'etat MBO dans un `ContextSchema` minimal, puis appelle
`build_sweep_inputs`, `SWEEP_GRAPH` et `evaluate_lsr` **tels quels**.

Reimplementer la detection pour le MBO aurait cree un second moteur de decision, a faire diverger
du premier. Le depot a deja tranche ce genre de question (D-052 : « les deux ne doivent jamais
tourner ensemble »). Ici il n'y a qu'un moteur, avec deux sources. Un test verifie qu'aucun seuil
de decision n'est recopie dans l'adaptateur.

### Le silence du fichier est CONSERVE

Un export MBO porte le carnet et les transactions. Il ne porte ni VIX, ni calendrier macro, ni
ATR de session, ni score SVS. Ces entrees ne sont **pas fabriquees** : elles restent ABSENT, les
gates qui en dependent refusent, et `diagnostics()` **nomme** lesquelles manquent.

C'est la doctrine de `ReplayDataSource` (« un replay dit ce qu'il sait, et se tait sur le reste »)
appliquee un cran plus bas. Un detecteur qui armerait quand meme produirait des setups dont les
filtres n'ont jamais tourne — la matrice de calibration mesurerait alors l'absence de donnees,
pas la strategie.

Corollaire assume : `news_state` vaut `None` par defaut, pas `SAFE`. La porte F0 est fail-closed
sur l'inconnu ; passer `SAFE` par defaut leverait une protection faute de donnees (lecon D-050).

### L'inversion passif -> agresseur, explicite

Le carnet MBO resout le cote PASSIF consomme (D-079) ; le tape du `ContextSchema` attend
l'AGRESSEUR (`tradeSideMeaning`). La conversion est donc une inversion — passif ASK -> agresseur
BUY. L'omettre retournerait B2 et B3 en silence, exactement ce que D-079 s'employait a empecher.
Un trade au cote inresolvable ne produit **aucun** print plutot qu'un print devine.

### Une matrice vide qui dit POURQUOI

Sans le rapport de diagnostic, une matrice de calibration vide se lirait « la strategie ne se
declenche jamais ». La cause peut etre tout autre : « le fichier ne porte pas les entrees que les
filtres exigent ». La passe imprime donc prints accumules, setups armes, refus post-sweep, et la
liste nommee des entrees absentes.

Exerce sur la fixture : 7 evenements, 2 prints accumules, 0 setup arme, entrees absentes listees.
Aucun chiffre invente pour combler le vide.

### Ce qu'il reste a faire pour la passe reelle

Deux ecarts a couvrir avant que la matrice puisse se remplir, et il vaut mieux les nommer
maintenant que les decouvrir sur le fichier :

1. **Les entrees absentes doivent venir d'ailleurs.** VIX, calendrier et ATR ne sont pas dans le
   MBO — il faudra les joindre depuis les sources externes existantes (`app/external/`) en les
   alignant sur les horodatages de la seance, ou accepter que les gates correspondants refusent.
2. **Une seance ne fera pas 60 setups.** A 0,4-0,8 trade/jour, la calibration demande plusieurs
   mois de seances rejouees. La matrice restera `INSUFFICIENT_DATA` d'ici la — et c'est elle qui
   le dira, plutot qu'un taux calcule sur trois trades.

## D-082 · Infrastructure P2 — le journal des setups et la matrice de calibration

`backend/app/setup_journal.py`, `app/calibration.py`, table `setup_journal` dans l'event store.
21 tests. **Ecrite AVANT les donnees**, pour qu'aucune decision de mesure ne soit prise sous la
pression d'un fichier deja la.

### Une seule question

> Les setups marques `FLAG` par les balises O1-O5 ont-ils un taux de reussite degrade ?

La matrice de calibration croise chaque balise avec chaque statut et rend, par cellule : nombre
de setups, non remplis, taux de non-remplissage, trades denoues, taux de reussite. Elle **compte**
et dit quand elle ne peut pas compter. Elle ne conclut rien — un test verifie qu'aucune
formulation conclusive (`has_edge`, `is_profitable`, `works`…) n'existe dans le module.

### Grammaire event-sourced, reprise telle quelle

`setup_armed` est immuable (ecrit par L4 a l'armement), `setup_outcome` est un event ULTERIEUR
qui le reference par `setup_id`, l'etat courant est une projection. L'append-only est garanti par
des triggers SQLite — `UPDATE` et `DELETE` levent `IntegrityError`, verifie par test. Aucun
chemin ne corrige un armement : le reecrire signifierait reecrire l'histoire de la calibration.

Un second armement pour un meme `setup_id` ne remplace pas le premier — il est conserve au
journal et compte dans `duplicates`. L'ecraser laisserait croire a une correction propre alors
qu'une double emission est une anomalie. Idem pour une seconde issue, et une issue orpheline
reste au journal mais n'entre pas dans la projection : elle ne reference rien, donc ne mesure
rien.

### Quatre regles d'honnetete, toutes testees

1. **`NO_FILL` hors du denominateur du taux de reussite**, mais remonte a cote au meme rang.
   « La strategie gagne-t-elle ? » et « les entrees sont-elles servies ? » sont deux questions ;
   les melanger rend les deux illisibles.
2. **Sous l'echantillon minimal, le taux vaut `None`**, pas un chiffre — un taux sur trois trades
   n'est pas une mesure, c'est du bruit avec une decimale. La cellule porte `INSUFFICIENT_DATA`.
3. **Un setup sans issue reste `PENDING`**, jamais un resultat neutre. Et les `PENDING` sont
   exclus du denominateur du taux de non-remplissage : sinon il baisserait mecaniquement a
   chaque armement, sans qu'aucune entree n'ait ete servie ni refusee.
4. **Process et resultat jamais consolides** (§2.7) : le volet resultat reste masque sous
   `RESULT_SCORE_MIN_TRADES`.

Export CSV a colonnes **fixes et ordonnees** — un export dont les colonnes varient selon les
donnees presentes n'est pas comparable d'une passe a l'autre. Un `None` s'exporte VIDE : la
chaine « None » dans un CSV se relit comme une valeur et fausserait toute reprise en pandas.

### La commande qui tournera le jour ou le fichier arrive

    python -m app.calibration seance.parquet --csv setups.csv

Enchaine Parquet -> carnet -> armement -> simulateur FIFO -> issues -> journal -> matrice, sans
etape manuelle. **Le detecteur d'armement est INJECTE** : sans detecteur fourni, la passe ne
fabrique aucun setup — elle le dit et rend des zeros. Des armements arbitraires produiraient une
matrice d'allure complete mesurant un generateur, pas une strategie.

Exerce sur la fixture : ingestion 7/7, 0 rejet, 0 setup, tous les taux a `—`. Aucun chiffre
invente pour combler le vide.

### Ce que la passe reelle mesurera

Le **taux de non-remplissage** est la mesure laissee non chiffree depuis D-078 : c'est lui qui
donne la magnitude reelle du biais de touche. Un backtest naif l'affiche structurellement a 0 %.
Il manque desormais une seule chose : le fichier.

## D-081 · Harnais de rejeu bout-en-bout — la boucle du PnL est fermee

`backend/app/replay_harness.py`. 15 tests. MBO -> carnet -> armement -> simulateur FIFO ->
`Outcome`. Les modules existaient tous ; il manquait le fil qui les relie.

### `NO_FILL` est une issue de PREMIERE CLASSE

C'est tout l'interet du harnais. Un setup parfaitement valide dont l'entree limite n'est jamais
servie n'est ni un gain ni une perte : **il n'a pas eu lieu**. C'est exactement ce qu'un backtest
« rempli au touche » transforme en gagnant. Le compter comme un trade neutre serait deja un
mensonge — il faut pouvoir dire COMBIEN de setups n'auraient jamais ete pris.

Quatre issues tenues distinctes : `NO_FILL`, `WIN`, `LOSS`, `OPEN_AT_END`. Le taux de reussite
se calcule sur les trades REELLEMENT PRIS ; mettre les `NO_FILL` au denominateur melangerait deux
questions distinctes — « la strategie gagne-t-elle ? » et « les entrees sont-elles servies ? ».
Sans trade pris, `win_rate` vaut `None`, jamais 0 : « 0 % de reussite » et « aucun trade » ne
veulent pas dire la meme chose.

### Le stop sort au MARCHE, le TP reste une LIMITE

Un stop n'est pas une limite : quand le prix le traverse, on sort en payant le carnet, et le
slippage de sortie est la consommation reelle des niveaux — jamais zero. Le TP, lui, repasse par
la file FIFO et **peut ne jamais etre servi**. Sur un evenement ambigu ou stop et TP sont tous
deux atteignables, **le stop prime** : ne pas s'accorder le meilleur des deux est ce qui separe
une mesure d'un voeu.

### Le bug de double decompte, trouve par un test

Un ordre arme sur un evenement de TRADE voyait sa file decrementee **deux fois** : une fois par
le carnet qui venait d'absorber l'echange, une fois par le simulateur a qui on presentait le meme
echange. Il avancait donc dans la file sans que personne n'ait rien achete — un biais d'optimisme
silencieux, dans le module ecrit precisement pour les supprimer.

Corrige par une comparaison LARGE dans le simulateur : **un ordre place a l'instant T ne peut pas
participer a l'echange survenu a T**, il n'etait pas encore dans le carnet.

Corollaire : `entry_queue_ahead` (instantane immuable a l'armement, covariable utile a la
calibration) est desormais distingue de `entry_queue_remaining` (ce qu'il restait devant nous a
la fin, qui dit a quel point on est passe pres).

### Ce qui reste NON MESURE — et pourquoi

Le harnais ferme la boucle **mecaniquement**. Il ne ferme pas la question laissee ouverte en
D-078 : la magnitude reelle du biais de touche. La seule fixture MBO disponible compte **7
evenements synthetiques** — de quoi verifier la mecanique, pas de quoi mesurer une distribution
volume-au-prix contre profondeur de file.

Aucun chiffre de surestimation ne sera ecrit tant qu'une seance MBO reelle n'aura pas ete
rejouee. Le harnais est l'outil ; il lui manque la donnee.

### Bout-en-bout sur la fixture reelle

Verifie : notre limite a 5000.00 derriere 40 lots, l'ordre 101 se deplace a 4999.75 (modify),
15 lots s'y echangent — un echange SOUS notre bid traverse notre limite, donc tout ce qui etait
devant a necessairement ete servi et nous sommes remplis. Le flux s'arrete la : `OPEN_AT_END`,
`pnl_usd = None`. Distinguer cela d'un `NO_FILL` etait l'un des points a ne pas rater.

## D-080 · L4 `gates.eval` cablee — et la frontiere entre ce qui est mesurable et ce qui ne l'est pas

`backend/app/gates_journal.py`, `build_gates_tick`, hook `on_arm` dans `engine.py`. 13 tests.

### Le PnL n'existe pas a l'armement

L'objectif de P3 item 3 etait de journaliser chaque setup « avec son PnL/slippage simule ». Les
deux moities n'ont pas le meme statut, et les confondre aurait produit un chiffre invente :

- **Le slippage d'ENTREE est mesurable maintenant** : le carnet est connu, la file d'attente a
  notre prix limite se lit dedans, et le simulateur FIFO (D-078) dit ce qu'un ordre y subirait.
- **Le PnL ne l'est PAS** : le trade n'a pas eu lieu, sa sortie depend d'un futur qui n'est pas
  arrive. Fabriquer un PnL a l'armement reviendrait a supposer le resultat qu'on cherche
  precisement a mesurer.

Ce n'est pas une limitation, c'est la doctrine event-sourced deja etablie (`CLAUDE §2.5`,
D-045) : **la decision est un event immuable, l'outcome est un event ULTERIEUR qui la
reference**. L'entree porte `setup_id` et `pnl_source: "PENDING"` — jamais un zero qui se lirait
comme un resultat nul. Le PnL arrivera par reconciliation NinjaTrader en live, ou par rejeu MBO
en backtest.

### Consultatif par CONSTRUCTION, pas par convention

Le hook `on_arm` est appele APRES `broadcaster.publish("fast", "trade_manifest", ...)`. L4 est
donc structurellement incapable de retenir un manifeste : meme si elle levait, l'emission a deja
eu lieu. Elle ne leve pas pour autant, et l'entree de journal n'a ni `blocked` ni `allowed`.

Un contexte options mort n'empeche pas la journalisation : le setup est annote
`O1_DATA_UNAVAILABLE`, pas supprime — sinon la calibration perdrait exactement les setups pris
sans contexte, qui sont ceux qu'il faut pouvoir comparer.

### Le bug que le test a attrape — et qui aurait tout annule

Le manifeste parle en `LONG`/`SHORT`, le simulateur en `BUY`/`SELL`. En passant `LONG` tel quel,
`_resolve_queue` lisait `book.bids if side == "BUY" else book.asks` — donc les ASKS pour un
achat, ou aucun niveau ne correspond au prix d'entree : **file = 0, « premier servi »**.

C'est-a-dire *exactement* le biais optimiste que D-078 et D-079 existent pour supprimer,
reintroduit par une traduction manquante a la frontiere. Deux corrections :

1. la traduction est faite explicitement dans `gates_journal` ;
2. le simulateur **refuse** desormais un cote inconnu au lieu de retomber silencieusement sur
   les asks. Un `else` implicite transformait toute faute de frappe en file nulle. Test de
   regression sur `LONG`, `SHORT`, `buy`, `""`, `None`.

### L4 lit les MEMES barres que L3

Le tampon `EsBarAggregator` est partage : deux tampons distincts divergeraient, et l'O5 inscrit
au journal ne serait plus celui diffuse sur le canal — deux verites pour une meme mesure.

### Essai reel — ce qui est verifie et ce qui ne l'est pas

`gates.eval` passe de `NOT_IMPLEMENTED` a **RUNNING** sur le backend reel, et `unhealthy` se
reduit a `['core.tick']`. En revanche **aucun armement n'a ete observe** pendant l'essai (0
manifeste emis en 20 s) : a 0,4-0,8 trade/jour, c'est attendu. Le chemin complet
armement -> journal -> canal est couvert par test avec un manifeste synthetique, pas par
observation live. Ce sera verifiable en rejeu MBO sur une seance complete.

### Reste ouvert

`core.tick` demeure `NOT_IMPLEMENTED` : la boucle rapide est assuree par `engine.py`, sa
migration sous le contrat est un refactor. Le harnais de rejeu de bout en bout (MBO -> armement
-> simulateur -> PnL realise) reste a assembler : c'est lui qui fermera la boucle du PnL et
rendra enfin mesurable la magnitude du biais de touche laissee non chiffree en D-078.

## D-079 · Rejeu Parquet/MBO — le carnet L2/L3 reconstruit tick-by-tick

`backend/app/mbo/` (`events.py`, `book.py`, `ingest.py`). 38 tests. Fixtures Parquet reelles de
l'artefact v1.7 versionnees sous `backend/tests/fixtures/`.

### L'ambiguite de cote sur un trade — traitee, pas devinee

L'artefact impute le passif d'un trade depuis le drapeau : `side === 'A' ? asks : bids`. Or son
propre `CLAUDE.md` §5 avertit que « `tradeSideMeaning` = **agresseur**, pas le passif consomme —
l'inverser retourne B2 et B3 **en silence** », et Databento documente `side` comme le cote de
l'agresseur. Sous cette convention l'imputation de l'artefact est inversee ; sous celle de sa
propre fixture elle est juste. **Les deux lectures s'opposent et aucune n'est verifiable sans
donnees reelles.**

Deviner aurait inverse deux gates sans qu'aucun test ne tombe. Le cote passif est donc resolu
dans cet ordre : (1) l'`order_id` au repos — seule source autoritaire, l'ordre touche porte son
propre cote ; (2) a defaut le PRIX compare aux meilleures limites, derive du carnet donc
independant de la convention (`order_id = 0` est le cas normal des donnees reelles) ; (3) sinon
**rejet compte** (`unresolved_trades`), jamais une imputation au hasard.

Un test verifie explicitement que le drapeau `side` **ne peut pas** inverser le passif : meme
trade, drapeau oppose, meme resultat. Les deux trades anonymes de la fixture sont tous deux
resolus, `unresolved_trades == 0`.

### Deux ecarts de plus avec l'artefact

- Sa docstring annonce « O(1) par evenement, sans allocation dans le chemin chaud ». C'est
  **inexact** : `recomputeBest` balaie tous les niveaux a chaque retrait, `cumulativeDepth`
  alloue puis trie. La promesse n'est pas reprise — mieux vaut pas de promesse qu'une fausse.
- `levelOf` creait une entree a chaque prix touche, y compris pour l'annulation d'un ordre
  inconnu a un prix arbitraire : sur une seance la table croit sans borne (piege « fuite
  memoire » de RUNTIME_LOOPS Loop D). Le nombre de niveaux par cote est **borne**, les plus
  eloignes du marche evinces en premier, et **jamais** un niveau portant de la liquidite vivante.

### L'invariant nanoseconde change de NATURE en Python

L'artefact impose `bigint` parce qu'un epoch ns (~1,78e18) depasse `Number.MAX_SAFE_INTEGER`
(9,0e15) : en `number`, deux evenements distincts collapsent et l'ordre de rejeu cesse d'etre
reproductible. Les entiers Python sont illimites — l'invariant est acquis **tant qu'on reste en
`int`**. Un `float` porte exactement la meme mantisse de 53 bits que le `number` JS : stocker des
ns en flottant reintroduirait le bug a l'identique. Verrouille par un test qui montre que
`float(1_700_000_000_000_000_001) == float(1_700_000_000_000_000_002)`.

### Rien n'est ecarte en silence

Chaque ligne rejetee l'est **avec son motif compte**, et le `reject_ratio` est calcule plutot que
laisse a l'appelant : un fichier a moitie rejete qui produit un backtest d'allure normale est le
pire resultat possible. Un recul temporel est **signale et conserve** par defaut — trier
discretement ferait disparaitre le symptome d'un probleme de capture ; le jeter est un choix
explicite (`drop_out_of_order=True`) et compte comme les autres. Une colonne requise absente est
fatale au FICHIER, pas a la ligne : on ne devine pas une colonne absente. Un fichier illisible
**leve** au lieu de rendre une liste vide, qui se lirait « seance sans evenements ».

### `pyarrow` reste OPTIONNEL

Le coeur — schema d'evenements et carnet — n'a aucune dependance Parquet : il se teste et tourne
sans. La lecture est importee a l'usage, et `pyarrow` va dans `requirements-dev` : le rejeu est
une preoccupation de backtest, pas du terminal live, et imposer ~100 Mo au demarrage d'un chemin
qui ne s'en sert jamais serait un cout gratuit.

### La jonction de P3

`to_aggregated_book()` projette le carnet MBO vers le carnet du simulateur FIFO (D-078) : la file
d'attente cesse d'etre une deduction et devient la **profondeur reellement observee** dans le
flux. Verifie sur la fixture — un ordre place a 4999.75 apres le `modify` trouve bien les 40 lots
de l'ordre 101 devant lui.

C'est aussi ce qui rendra mesurable la magnitude du biais de touche, laissee explicitement
non chiffree en D-078.

## D-078 · Simulateur d'execution FIFO — le biais le plus couteux du backtest de scalping

`backend/app/execution_sim.py`. 33 tests. Phase P3, intervertie avec P2 sur arbitrage operateur.

### Pourquoi ce module passe AVANT la journalisation des 60 setups

L'artefact v1.7 nomme lui-meme le biais : « un ordre limite n'est pas rempli au simple touche ;
il entre en fin de file FIFO et n'est execute que quand le volume devant lui est consomme. C'est
le biais le plus couteux d'un backtest de scalping ». Sur un TP a 5 ticks, supposer le fill au
touche transforme des trades **jamais remplis** en gagnants. Journaliser 60 setups avant d'avoir
ce module aurait produit des resultats faux, pas seulement absents.

### Quatre defauts de l'artefact, corriges

1. **Drapeau inverse.** `if (vol > 0 && !this.requireTrade === false)` : en JS,
   `(!requireTrade) === false` signifie « requireTrade est vrai ». Mettre le drapeau a `false`
   (« ne pas exiger d'echange ») **empechait** tout remplissage au lieu de l'assouplir. Le
   comportement n'est plus derriere un drapeau ambigu.
2. **Latence non rejouable.** `_lat()` tire `Math.random()`, en contradiction avec l'invariant
   n°1 de l'artefact — fonctions pures a etat injecte, « ce qui rend le backtest rejouable a
   l'identique ». Generateur seme et injecte ; verrouille par un test qui compare deux
   executions a graine egale.
3. **File d'attente optimiste par defaut.** `queueAhead` valait 0 sauf mention : le cas par
   defaut etait « premier de la file », l'hypothese la plus favorable qui soit. La file se
   **deduit du carnet** a l'envoi ; **sans carnet ni file explicite, l'ordre est REFUSE**. Se
   placer premier faute de donnees recreerait exactement le biais combattu.
4. **Carnet epuise maquille.** L'artefact completait au dernier niveau ± 2 ticks sans le dire.
   Ici la part non servie est rapportee (`unfilled_qty`, `book_exhausted`), jamais inventee.

Un cinquieme ecart, moins visible : `marketOrder` ne consommait pas le carnet — deux ordres au
meme instant obtenaient tous deux le meilleur niveau, soit de la liquidite fabriquee.
`market_order_consuming` rend le carnet residuel.

### Ce que l'essai manuel montre — et ce qu'il ne montre PAS

Meme tape, deux hypotheses : le comptage naif retient chaque touche comme un TP gagne, le FIFO
ne retient que ceux dont la file a reellement ete consommee. Le mecanisme fonctionne et se voit.

**Mais la MAGNITUDE mesuree n'est pas une propriete du marche.** Le scenario tire le volume
echange en `uniform(0, 2 x file)`, si bien que le volume depasse la file une fois sur deux **par
construction** — d'ou ~45-50 % de surestimation quelle que soit la taille de file (47 %, 44,5 %,
51,5 % pour 10, 40 et 100 lots : le chiffre ne bouge pas, ce qui trahit l'artefact de scenario).
Ce nombre mesure mon hypothese, pas ES.

La vraie magnitude depend de la distribution volume-au-prix contre profondeur de file, qui est
une propriete empirique des donnees MBO reelles. C'est precisement ce que le rejeu Parquet/MBO
(P3, item 1) doit fournir. **Aucun chiffre de surestimation ne sera inscrit dans la doc avant
d'etre mesure sur des donnees reelles.**

### Aucun ordre reel (§2.1)

Le module simule un appariement ; aucune dependance reseau. Un test de garde interdit
`requests`, `httpx`, `socket`, `broker`, `submit_order`, `aiohttp` dans la source — la frontiere
est facile a franchir sans y penser une fois qu'un simulateur produit des `Fill` credibles.

### Invariant n°4 preserve — on freine les envois, jamais les sorties

Le gouverneur gele les ENVOIS apres N annulations rapides, mais `cancel()` n'est jamais bloquee,
et les motifs protecteurs (`RISK_HALT`, `NEWS_BLACKOUT`, `SESSION_END`, `OPERATOR`) ne sont ni
comptes ni entraves : un arret de risque ne doit pas pouvoir declencher le gel qui l'empecherait
de se repeter.

### Reste de P3

Item 1 (rejeu Parquet/MBO, incrementation du carnet L2/L3 tick-by-tick) et item 3 (cablage L4
`gates.eval` sur le point d'armement du detecteur de sweep) ne sont pas dans ce commit.

## D-077 · L3 `o5.kurtosis` cablee — les barres ES qui n'existaient pas

`backend/app/es_bars.py`, `build_o5_tick` dans `app/loops/wiring.py`. 19 tests.

### Personne ne produisait de barres ES

O5 lit une fenetre de 121 barres — deux heures. Le footprint agrege bien par bougie, mais son
tampon est borne a `FOOTPRINT_MAX_PRINTS` (800 prints), de quoi couvrir quelques minutes. **Une
fenetre de deux heures ne se reconstruit pas depuis un tampon de prints ; elle s'ACCUMULE.**
D'ou un agregateur dedie, qui echantillonne le dernier print du tape et clot une barre a chaque
frontiere de minute.

### Trois choix qui ne sont pas cosmetiques

1. **La largeur de barre est INDEPENDANTE de `FOOTPRINT_CANDLE_SECONDS`.** Ce reglage pilote un
   affichage et peut basculer en mode tick (`FOOTPRINT_TICKS_PER_CANDLE`). Adosser une mesure de
   risque a un reglage d'affichage, c'est accepter qu'un changement de vue modifie le kurtosis
   sans que personne ne fasse le lien. `O5_BAR_PERIOD_SECONDS` lui appartient en propre.
2. **Seules les barres CLOSES entrent dans le tampon.** La bougie en formation a une cloture
   mouvante ; `push_bar` rejetant les doublons d'horodatage, la premiere valeur partielle serait
   **gelee** comme cloture definitive de la minute.
3. **Tape non FRESH -> aucune observation.** Repeter le dernier prix connu fabriquerait des
   rendements nuls : une serie calme *inventee*, donc un kurtosis rassurant sur des donnees qui
   n'existent pas. Un trou reste un trou — c'est `has_temporal_gap` qui doit le voir.

### La cadence declaree de L3 est l'ECHANTILLONNAGE, pas la largeur de barre

Correction de la spec posee en D-073 (60 s). Une boucle cadencee a la largeur de barre verrait
chaque bucket une seule fois : la moindre gigue d'ordonnanceur sauterait une minute et
fabriquerait un `O5_DATA_GAP` qui ne dit rien du marche et tout de notre boucle. On echantillonne
a 5 s, et on ne recalcule **qu'a la cloture** d'une barre — entre deux clotures la fenetre n'a pas
change, recalculer serait douze fois le travail pour la meme reponse.

### Le deport, raison d'etre de cette boucle

`evaluate_o5` est du CPU synchrone. Execute sur le fil de la boucle d'evenements, il la gele
avant tout point d'attente — et gele `core.tick` avec elle (piege Python en tete de
`RUNTIME_LOOPS.md`). Le calcul part donc en `asyncio.to_thread`. Le plafond de duree du contrat
borne l'attente ; il ne rend pas le calcul non bloquant, seul le deport le fait. Un test le
verifie en capturant le NOM DU FIL d'execution, pas en faisant confiance a la lecture du code.

### Regression trouvee a l'essai reel, et le filet qui la cachait

Premiere version : `snapshot()["s1_state"]["tape"]`. Or `Engine.snapshot()` enveloppe le schema
sous la cle `schema`. Le chemin etait faux — et il etait entoure d'un `except Exception` qui a
transforme un `KeyError` en `None`, donc en `tape_not_fresh`. Resultat : **L3 a echoue 58 fois
d'affilee en accusant le feed**, alors que la faute etait dans ce chemin.

Le `except` fourre-tout a ete retire, pas seulement le chemin corrige : **un filet trop large ne
protege pas, il deguise**. Une projection malformee rend toujours `None` (fail-closed), mais une
erreur de programmation remonte au lieu de se maquiller en absence de donnee. Le test de
regression construit la projection depuis le **vrai modele Pydantic** plutot qu'un dict ecrit a
la main — un dict fabrique se serait contente de refleter la meme erreur.

### Essai reel — O5 vivant sur le canal `options`

Worker -> Redis -> backend -> SSE, barres compressees a 2 s pour observer la montee. Sequence :
23 evenements `O5_SAMPLE_TOO_SMALL` avec `excess_kurtosis: null` pendant l'accumulation (aucune
valeur inventee sous le seuil d'echantillon), puis bascule en `PASS` des 30 rendements, avec
kurtosis, skewness, variance et attribution du residu dominant renseignes. 42 evenements au
total, un par cloture de barre.

Les 3 echecs de L3 observes pendant l'essai ne sont pas des defauts : le `MockDataSource` injecte
les pathologies exigees par §4 (ticks manquants, donnees en retard), le tape passe brievement
non-FRESH, et L3 refuse alors d'observer plutot que de fabriquer une barre. Le chemin fail-closed
s'exerce donc en conditions reelles.

### Reste ouvert

`gates.eval` (L4) demeure `NOT_IMPLEMENTED` : elle attend le point d'armement du detecteur de
sweep. `core.tick` reste assuree par `engine.py` — sa migration est un refactor.

## D-076 · Portage Python des balises O1-O5 — et un verrou qui MORD

`backend/app/options_gates.py` (O1-O4 + assemblage + export CSV), `backend/app/o5_tail_risk.py`
(O5). 69 tests. Sources TS sous `reference/v2/fast-engine/`, marquees `AUTORITE` au MANIFEST.

### Le mode G2 est une garantie STRUCTURELLE, pas une configuration

Aucun evaluateur ne retourne de booleen, aucun ne leve, et l'entree de journal n'a ni champ
`blocked` ni `allowed`. Il n'existe nulle part un motif `if not gate: block()` desactive qu'un
refactor pourrait reactiver par accident : il n'y a simplement **aucun chemin de blocage**.

Cette propriete est verifiee **par introspection** (`inspect.getsource`), pas seulement par
usage. Un test qui se contente d'appeler les gates prouve qu'ils ne bloquent pas *aujourd'hui* ;
un test qui lit leur source prouve qu'on ne peut pas les faire bloquer *demain* sans le voir.

### Deux divergences deliberees avec le TypeScript, chacune fail-closed

1. **GEX non fini -> `O1_DATA_UNAVAILABLE`.** Le TS fait `Math.abs(NaN) <= seuil` -> faux, puis
   `NaN > 0` -> faux, et tombe dans la branche du regime negatif : il produirait un
   `FLAG_STRONG` porteur d'un `NaN`. Ce n'est pas du JSON valide, et §3 exige un refus explicite
   plutot qu'une mesure inventee. Un strike **ou** une valeur non finie est ecarte du choix du
   plus proche — designer « le plus proche » puis n'avoir rien a y lire n'avance a rien.
2. **Horodatage du futur**, deja tranche en D-075.

Toute autre divergence est un bug, pas un choix. Les deux sont testees et nommees comme telles.

### Le verrou de parite, verifie en le faisant ECHOUER

Un verrou qui ne tombe jamais est du theatre. Trois mutations deliberees ont ete introduites
dans les sources TS — `O2_EXCLUSION_TICKS` 12 -> 14, un statut `O3_NOUVEAU` ajoute a l'union,
`kurtosisThreshold` 6.0 -> 8.0 — et **chacune a fait tomber son test**, aucun autre. Sources
restaurees a l'identique de l'artefact (verifie par `diff`).

Le verrou couvre les seuils, le tick ES, **les unions de statuts** et **les noms de colonnes
CSV**. Ces deux derniers comptent autant que les seuils : un statut ajoute d'un seul cote ne
casse aucun test d'usage, il produit une colonne de journal que personne ne sait relire ; et le
journal des 60+ setups sera relu par la calibration, donc une colonne renommee casserait la
correlation en silence.

### Ou vivent les sources TS — et pourquoi pas dans `lsr-engine/`

Correction d'une regression que j'ai introduite en D-075 : `optionsContext.ts` avait ete versionne
dans `lsr-engine/src/`, un paquet qui **compile**. Il importe `redis`, absent de ses dependances
-> `tsc --noEmit` passait de 6 erreurs preexistantes (`vitest` non installe dans cet
environnement) a 8. Le gate TypeScript etait rouge de mon fait, et je ne l'avais pas execute.

Ces fichiers appartiennent au Fast Engine v1.7 — un autre paquet, d'autres dependances. Ce depot
ne les execute pas, il les **porte**. Ils vivent donc sous `reference/v2/fast-engine/`, avec une
entree `AUTORITE` explicite au MANIFEST : exception assumee a la regle « `/reference/` =
maquette », puisqu'ils sont la source du portage et la cible du verrou.

Nuance inscrite au MANIFEST : ils font autorite pour l'**equivalence des deux implementations**,
jamais pour affirmer que leurs seuils sont calibres. Aucun ne l'est.

### O4 est inerte par PREREQUIS EXTERNE, pas par bug

`sourceConfirmed` faux court-circuite tout le reste : la source Net Premium Drift n'est confirmee
que sur QQQ, pas SPY/SPX. Avec les donnees disponibles, O4 renvoie donc toujours
`O4_SOURCE_UNCONFIRMED`. La logique d'alignement en dessous est **prete et testee** — un test
force `sourceConfirmed` a vrai et verifie qu'elle fonctionne. Ce n'est pas du code mort a
supprimer : c'est du code qui attend une donnee qui n'existe pas encore, et on le prouve.

### Unites — `now_ms` en millisecondes, explicitement

Le worker horodate `netDriftCrossover.ts` en ms ; le reste du backend est en secondes. Convertir
au milieu du gate serait le meilleur moyen de comparer des secondes a des millisecondes sans que
rien ne le signale. La conversion est la responsabilite de l'appelant, et le nom du parametre le
dit.

### Ce que ce commit ne fait PAS

Le port est une bibliotheque pure : **L3 et L4 ne sont pas cablees**. `o5.kurtosis` et
`gates.eval` restent `NOT_IMPLEMENTED` dans la projection de sante. L3 exige une source de barres
ES 1 min et le deport `asyncio.to_thread` (le calcul est du CPU synchrone : execute dans la
boucle, il gele `core.tick` avant tout point d'attente) ; L4 exige le point d'armement du
detecteur de sweep. Deux tranches d'integration distinctes.

## D-075 · L2 `options.sync` — le contexte options, de Redis au canal SSE

`backend/app/options_context.py` (port Python d'`optionsContext.ts`), `app/loops/wiring.py`,
3e canal SSE `options`, `workers/options_worker.py` versionne. 20 tests + 23 du worker.

### Ce qui est cable, et ce qui ne l'est pas

Deux boucles sur cinq : `options.sync` (L2) et `ui.broadcast` (L5, qui publie la sante). Les
trois autres restent `NOT_IMPLEMENTED` et le disent. `core.tick` est deja assuree par
`engine.py` : l'y migrer est un refactor, pas cette feature (Loop 3).

### Le worker n'est pas pilote, il est consomme

`options_worker.py` pose son propre decouplage : « un redemarrage ou une panne du serveur qui
sert le terminal ne doit jamais affecter ce worker, et inversement ». Il est donc versionne sous
`backend/workers/` — hors du paquet `app`, demarre separement — et L2 ne fait que lire
`options:context:latest`. Sans worker, L2 echoue a chaque tick et finit `STALLED` : c'est la
verite, elle se lit sur le canal, et aucune valeur n'est inventee pour combler le vide.

### La discipline de lecture, reprise telle quelle du TypeScript

`snapshot()` est SYNCHRONE, pure sur `now`, sans aucune I/O. Le fichier TS justifie la regle par
la mesure : ~0,02 us pour une lecture locale, ~130x de plus pour le moindre saut asynchrone. Au
moment de l'armement on lit une variable en memoire ; le rafraichissement vit dans L2, hors du
chemin de decision (§7).

### `refresh()` LEVE au lieu de renvoyer un booleen

Un rafraichissement silencieux ferait battre L2, et le superviseur l'afficherait `RUNNING` alors
qu'aucune donnee n'arrive — exactement le mensonge que D-073 existe pour empecher. L'echec doit
etre compte. Le cache, lui, n'est jamais corrompu par une lecture ratee : la derniere valeur
bonne reste et vieillit vers `STALE`. Trois causes distinguees (`redis_error`, `key_missing`,
`malformed`) parce qu'elles n'appellent pas la meme intervention, et journalisees **une fois par
episode** : a 5 s de cadence, une panne d'une heure produirait 720 lignes identiques (hygiene
D-046, meme parade que la regression d'horloge du `lsr_driver`).

Le tick publie dans un `finally`, donc **meme quand il echoue**. Sans cela, une source morte
laisserait l'UI sur le dernier contexte recu, fige et d'allure fraiche.

### Divergence ASSUMEE avec le TypeScript — l'horloge du futur

`optionsContext.ts` calcule `age = now - computedAt`, obtient un negatif sur un horodatage date
du futur, le compare a un seuil positif, et conclut `OK` : **fail-OPEN sur une desync
d'horloge**. Ce depot a deja paye cette lecon (D-050/D-048) et refuse une donnee du futur —
`STALE`, avec l'age negatif conserve dans la projection : on ne maquille pas la desync, on
refuse seulement de la traiter comme de la fraicheur. Le type de retour reste identique aux
quatre valeurs de `SnapshotHealth`, donc le contrat de fil ne bouge pas.

### Verrou de parite (doctrine D-072), sur les DEUX bouts

Trois tests LISENT les sources et echouent en cas de divergence : le seuil de peremption
(`STALE_THRESHOLD_MS` du TS vs `OPTIONS_CONTEXT_TTL_SECONDS`), et la cle Redis + le canal
pub/sub, compares a la fois au TypeScript et au worker Python. Une cle qui diverge ne casse
aucun test unitaire : elle produit juste un terminal eternellement `UNAVAILABLE` face a un
worker qui publie correctement.

### Essai reel — la source coupee se VOIT

Worker reel -> Redis reel -> backend reel -> canal SSE. Sequence observee de bout en bout :
contexte `OK` a 13 strikes ; worker tue ; la cle survit sous son TTL de 90 s et L2 continue de
lire **avec succes** un payload de plus en plus vieux (`fail=0`, age qui monte — comportement
correct, la degradation etant portee par `age_s`) ; a 90 s le contexte bascule `STALE` ; le TTL
expire, la cle disparait, `key_missing` s'accumule en `failures`. La valeur figee n'a jamais ete
presentee comme fraiche.

### `loops_health` publie sur changement d'etat

A 0,25 s, publier la sante a chaque tick ferait 4 messages/s au contenu quasi constant. On
publie sur changement d'empreinte (statut/echecs/plafonds — volontairement sans les ages ni les
compteurs de ticks, qui bougent a chaque tour et supprimeraient tout dirty flag), plus un rappel
toutes les 2 s pour que l'age affiche ne se fige pas. `replay=False` : une mesure datee ne se
rejoue pas pour hydrater un abonne neuf.

**Limite connue** : c'est `ui.broadcast` qui publie la sante. Si elle meurt, la sante cesse
d'etre poussee et le client ne le voit qu'au silence du canal. Un watchdog externe (Loop G) est
le vrai remede ; hors de cette tranche.

### Reste ouvert

Le frontend ne consomme pas encore le canal `options` (3e `EventSource` + panneau) : c'est une
tranche UI, qui passe d'abord par `/design` (Loop 6). O4 restera `O4_SOURCE_UNCONFIRMED` tant
que la source Net Premium Drift n'est confirmee que sur QQQ — prerequis externe, rendu lisible
dans la projection (`net_drift.source_confirmed`) plutot que masque.

## D-073 · Un contrat unique de boucle — parce qu'une boucle morte ressemble à une boucle calme

`backend/app/loops/` : `contract.py` (LoopSpec + runners), `supervisor.py`, `health.py`,
`registry.py`. 27 tests.

### Pourquoi maintenant, et pas une sixième boucle à la main

Le dépôt comptait déjà **quatre** boucles Loop-D écrites une par une (`engine.py` 0,25 s/15 s,
`account_provider` 1 s, `macro_news` 1 h, `lsr_driver` 0,25 s). Le Pont Options v2 en ajoute
**trois** (sync options, kurtosis O5, gates O1-O5). Refaire sept fois les mêmes parades, c'est
sept occasions de rouvrir la faille que D-052 a fermée au prix d'une passe `/devil` complète —
et cette faille a un nom : **un driver mort ressemble à un driver calme**.

Les parades de D-052 sont donc factorisées ici en un seul endroit : cadence à l'échéance sur
horloge monotone sans rattrapage, créneaux manqués comptés puis abandonnés, drop-if-busy,
plafond de durée par tick, filet d'exception, relance signalée d'une boucle tuée de l'extérieur,
arrêt non propageant.

### Le vrai apport n'est pas la factorisation, c'est la santé observable

`CLAUDE §3` — « no signal without data » — s'applique aussi aux boucles. La projection
`health()` permet à l'UI d'afficher « o5.kurtosis STALLED » au lieu de laisser un kurtosis figé
passer pour frais. **Le battement ne compte que les ticks RÉUSSIS** : une boucle qui cycle sans
rien produire est vivante et inutile ; l'afficher `RUNNING` serait précisément le mensonge que
ce module existe pour empêcher.

Corollaire trouvé à l'**essai manuel** (§13 Loop 1, étape 6) et corrigé avant commit : la grâce
accordée avant le premier battement n'était pas bornée, si bien qu'une boucle échouant à *chaque*
tour restait `RUNNING` pour toujours. Elle est désormais bornée par le seuil de péremption,
mesurée depuis le démarrage. Test de régression dédié.

### Trois choix qui ne sont pas cosmétiques

1. **`gates.eval` est ÉVÉNEMENTIELLE**, déclenchée par `evaluateLsr()`, jamais par une horloge :
   une L4 périodique réévaluerait le PASSÉ (piège de cadence D-052 / doctrine D-045 T3).
   Conséquence assumée : son silence n'est pas une panne (un matin sans setup est un matin
   normal), donc elle n'a **pas** de seuil de péremption et ne peut pas passer `STALLED`. Une
   spec événementielle portant un seuil est refusée à la construction.
2. **`o5.kurtosis` est COLD.** Les moments d'ordre 4 sur 120 rendements sont du CPU synchrone :
   exécutés dans la boucle, ils gèlent `core.tick` avant tout point d'attente (piège Python en
   tête de `RUNTIME_LOOPS.md`). Le budget borne l'attente ; il ne rend pas le calcul non
   bloquant — c'est au tick de déporter (`asyncio.to_thread`).
3. **`options.sync` DÉGRADE, elle ne bloque pas.** Le Pont Options est consultatif (mode G2) :
   un fournisseur muet ramène le poids options à zéro et marque le signal dégradé, il n'empêche
   jamais un trade que les contrôles déterministes ont autorisé. Même doctrine que le poids
   Macro non calibré (`CLAUDE §8`).

Le seuil de watchdog doit dépasser la période (RUNTIME_LOOPS Loop G) : un watchdog en alerte
permanente est un watchdog qu'on apprend à ignorer. Refusé à la construction, pas découvert en
production.

### Ce que ce commit ne fait PAS

Il **déclare** les cinq boucles ; il n'en câble aucune. Un superviseur monté sur le registre seul
rapporte `NOT_IMPLEMENTED` sur les cinq lignes et `all_healthy: false` — c'est la vérité à ce
stade, et elle est visible. Le critère retenu (COMMANDS.md §3) est « un lecteur peut-il confondre
ceci avec du code de production validé ? » : ici le statut le dit en toutes lettres.
`NOT_IMPLEMENTED` est délibérément classé **non sain** — une capacité annoncée et absente n'est
pas un état neutre.

L1/L5 existent déjà sous une autre forme (`engine.py`, `api.py`) : les y migrer est un refactor,
pas cette feature (§13 Loop 3 — jamais refactor + feature dans le même commit).

## D-074 · Transport : le 3ᵉ canal SSE, pas une passerelle WebSocket

`COMMANDS.md` (P4) et `/sync-ui` désignent une « passerelle WebSocket ». Écart signalé, arbitré
par l'opérateur : **on conserve SSE**, et les métriques GEX/Kurtosis/O1-O5 partent sur un
**3ᵉ canal SSE `options`**, aux côtés des canaux rapide et lent (`CLAUDE §6`).

Raison : `frontend/src/lib/sse.ts` porte deux `EventSource` auto-résurrectés, durcis par une
passe `/devil` (deux pannes distinctes fermées). Migrer vers WebSocket jetterait un transport
éprouvé pour du bidirectionnel dont aucun besoin n'est établi — le flux options est
unidirectionnel serveur → client, exactement ce que SSE fait. La cadence UI reste à 250 ms :
`options_worker.py` publie toutes les 5 s, un rafraîchissement à 50 ms rendrait 100 fois la même
valeur.

## D-072 · Le verrou de parité — le test qui LIT le TypeScript

`tests/test_parite_lsr_config.py` parse `lsr-engine/src/config.ts` et échoue si le Python ne dit
pas la même chose.

### Pourquoi un test et pas une relecture
Les huit passes de parité précédentes ont toutes trouvé la même chose : non pas une mauvaise
valeur, mais **la même valeur écrite à deux endroits**, puis corrigée d'un seul côté. Une
relecture attrape ça le jour où on la fait. Et une divergence de seuil **ne casse aucun test
métier** — elle produit des trades légèrement différents, en silence, pendant des semaines.

### Trois propriétés, dans l'ordre d'importance
1. **Aucune constante du TS ne peut être IGNORÉE.** Chaque clé de `DEFAULT_CONFIG` est soit
   comparée (table `PORTE`, avec la conversion d'unités écrite explicitement — c'est le seul
   endroit où ms et secondes se rencontrent, et le cacher ferait disparaître un facteur 1000),
   soit inscrite au registre `NON_PORTE` **avec son motif et sa dépendance**. Une clé neuve côté
   TypeScript fait tomber le test tant que personne n'a tranché son sort.
2. **Ce qui est comparé doit être égal.**
3. **Le registre ne peut pas pourrir** : une entrée qui a fini par être portée fait tomber le
   test, pour qu'on la retire au lieu de la laisser mentir.

Le registre `NON_PORTE` compte aujourd'hui **9 entrées** : F6 (×2), F7-resubmit, F8 (×5),
scale-out. Chacune nomme ce qui la débloquera — pour les huit premières, un `LsrRuntimeState` qui
doit être une **projection du Decision Log** (§2.5), pas un champ mutable.

### Le parseur dit quand il ne comprend plus
Un parseur muet passerait tous les autres tests au vert **en ne comparant rien**. Un test exige
donc un plancher de clés par bloc, et l'absence du fichier de référence est une ERREUR explicite
(« le RÉPARER, pas le désactiver »), pas un skip.

Pas d'`eval` : l'arithmétique se limite aux sommes de produits (`24 * 60 * 60_000`), ce que
`config.ts` contient réellement. Exécuter du texte lu sur le disque pour lire un nombre serait
disproportionné.

### Le verrou s'est attrapé lui-même à sa première exécution
`INSTRUMENT_SPECS` est IMBRIQUÉ (`MES: { tickSize… }, MNQ: { tickSize… }`). Mon parseur à plat
gardait la DERNIÈRE valeur de chaque clé homonyme : il comparait MNQ en croyant comparer MES, et
aurait déclaré la parité sur un instrument jamais vérifié. Corrigé par une lecture imbriquée.

### Vérif — le verrou mord, prouvé par mutation
Sept mutations, une à la fois, **des deux côtés**, chacune restaurée ensuite :

| mutation | verrou |
|---|---|
| TS · `b1MinWallRefillRatio` 0.4 → 0.45 | ✓ détectée |
| TS · constante globale AJOUTÉE | ✓ détectée |
| TS · `APEX maxDrawdown` 2500 → 3000 | ✓ détectée |
| TS · palier VIX 20 → 22 | ✓ détectée |
| PY · `tp_max_ticks` MNQ 8 → 7 | ✓ détectée |
| PY · `tick_value` MNQ 0.5 → 0.6 | ✓ détectée |
| PY · `RISK_BUFFER_DIVISOR` 5 → 4 | ✓ détectée |
| sources intactes | ✓ vert |

11 tests neufs → **1364 passed**, ruff clean.

## D-065 · Outiller le relevé C2 — et une correction à D-063
`python -m app.providers.releve` prépare la séance de catalogue. Il pose trois questions dans
l'ordre : **est-ce que ça répond** (appel réel, échec classé par cause), **est-ce lisible**
(observations, premières et dernières dates), **qu'est-ce que ça débloque** (simulation contre un
registre hypothétique, rien n'est écrit sur disque). Le passage en C1 reste MANUEL : c'est tout le
sens de C2, un identifiant plausible se code aussi facilement que le bon.

### La correction : j'avais annoncé quatre champs, il y en a deux
J'avais écrit que relever les lignes C2 débloquerait `d5`, `beer_z`, `leading_turn` et
`rr_zscore`. **C'est faux pour `d5` et `rr_zscore`**, et c'est l'outil qui l'a montré :

`rr_zscore` passe par `ilsw_ez` et `d5` par `rdiff` — deux lignes **DÉRIVÉES**. Une ligne dérivée
n'est jamais interrogeable : `fetch_block_reason` rend « dérivé — calculé depuis X : rien à
collecter ici » **même une fois tous ses intrants relevés**. Relever `bundei_real` ne suffit donc
pas ; il faudra en plus écrire l'arithmétique `rdiff = f(dfii10, bundei_real)` et
`ilsw_ez = f(bund_nominal, bundei_real)`, qui n'est écrite nulle part au référentiel.

Bilan réel du relevé complet des six lignes : **`beer_z` et `leading_turn`, rien d'autre.**
- `oecd_cli` → `leading_turn` (seule, suffit)
- `nfa` + `tot` → `beer_z` (**les deux**, indispensables ensemble)
- `bundei_real`, `nairu_ez`, `r_star_us` → rien aujourd'hui, même avec les autres

### Le relevé se raisonne par LOT, pas ligne à ligne
Première version de l'outil : il jugeait chaque ligne isolément et annonçait « `nfa` n'ouvre
RIEN » — vrai isolément, trompeur en pratique, puisque `nfa` + `tot` ouvrent `beer_z`. Un
opérateur en aurait conclu que la séance ne servait à rien. L'outil simule désormais le lot
complet et marque chaque ligne **indispensable** ou non.

### Deux autres défauts trouvés en l'écrivant
- **`uip_implied` figurait dans les lignes à relever** : elle est C2 mais DÉRIVÉE. Aucun
  catalogue ne contient son identifiant, parce qu'elle n'en a pas — on aurait envoyé quelqu'un
  chercher une chose inexistante. Le filtre exige désormais `Kind.OBSERVED` (6 lignes, ce que le
  lecteur de registre annonçait déjà).
- **Un identifiant mal formé était étiqueté « CRASH — défaut CHEZ NOUS »** alors que c'est le
  résultat le plus utile du relevé : le connecteur refuse la forme, et on l'apprend AVANT de la
  figer. Devenu `IDENTIFIANT REFUSÉ`, avec la forme attendue dans le message.

`client_for_provider` (nouveau) donne le client d'un fournisseur **sans portillon de registre** :
la ligne est encore C2, donc `client_for` la refuse — à juste titre en production, à tort quand on
cherche précisément à la vérifier.

### Vérif
**11 tests** → **1283 passed**, ruff clean, mypy strict. `test_le_relevé_complet_debloque_
EXACTEMENT_deux_champs` fige l'enjeu réel : il échouera le jour où un blocage change, plutôt que
de laisser la promesse dériver en silence.

## D-064 · `fetch_catalog` devient un vrai contrat (Loop 3)
Sept connecteurs implémentaient `fetch_catalog(clé_du_registre)`, **aucun ne le déclarait**. Un
contrat de fait que le typage ne pouvait pas vérifier — D-063 le contournait par un `cast`, en
notant la dette. Passe de refactor dédiée, comme prévu (§13, Loop 3 : jamais mêlé à une feature).

- `HttpSeriesClient.fetch_catalog` est désormais **concret et unique** : il résout la spec, fusionne
  les filtres du registre, et délègue à `_by_identifier` — la seule ligne où les connecteurs
  diffèrent (`fetch` pour quatre, `fetch_key` en deux segments pour les trois SDMX).
- Les sept `fetch_catalog` disparaissent, remplacés par un `_by_identifier` d'une ligne.
- **La fusion des filtres du registre remonte dans la base.** Elle ne valait que pour Eurostat ;
  elle vaut pour tous. Neutre aujourd'hui — une seule ligne du catalogue porte des filtres
  (`unrate_ez` : `geo=EA20`) — et c'est vérifié par un test.
- Le `cast` de `macro_series.py` disparaît : mypy vérifie l'appel.

### Le filet de refactor a trouvé un défaut AVANT que je touche au code
Écrit d'abord, vert avant : `tests/test_providers_fetch_catalog.py` fixe le comportement
observable des sept (identifiant pris au REGISTRE, filtres d'office, clé bloquée qui LÈVE, clé
inconnue refusée). Il a immédiatement révélé que **CFTC ne pouvait pas honorer le contrat** :
`value_field` est obligatoire sans défaut (choix D-057 — deviner la colonne porteuse
fabriquerait une donnée), donc `fetch_catalog("cot_fx")` sortait un `TypeError` brut du fond de
la pile. Latent aujourd'hui (aucune recette faisable n'utilise `cot_fx`), fatal demain.

**Un seul changement de comportement, assumé et testé** : le refus devient un `SeriesBlocked`
qui NOMME `value_field` et dit quoi faire. Un contrat que six implémentations sur sept honorent
n'est pas un contrat ; le déclarer sans corriger la septième aurait été pire qu'avant.

Mon propre test était faux sur un point : Yahoo encode `^GDAXI` en `%5EGDAXI`, et je comparais la
chaîne brute — l'assertion échouait sur un connecteur parfaitement correct. Corrigée en comparant
l'URL décodée.

### Vérif
**28 tests de filet** → **1272 passed**, ruff clean, mypy strict (15 fichiers). Les 351 tests des
suites `providers` + `macro_series` passent sans modification : le comportement est préservé.

## D-063 · Le registre branché sur le `ContextSchema` — et ce qu'il refuse d'alimenter
53 séries sont interrogeables depuis D-057 et **n'alimentaient rien**. `MacroSeriesProvider`
(`app/external/macro_series.py`) est le pont manquant : il fetche, calcule avec les formules DÉJÀ
écrites (`providers/cascade.py`), et publie sous la source `macro_feed` que le moteur attend —
**zéro ligne modifiée dans `engine.py`**, comme pour D-062.

### La faisabilité est DÉRIVÉE du registre, jamais déclarée
`RECIPES` dit COMMENT un champ se construit, jamais s'il est alimentable : ça se déduit à l'appel
de `fetch_block_reason`, `has_rest_endpoint` et de l'existence des deux jambes. Une table de
faisabilité écrite à la main mentirait le jour où un identifiant C2 est relevé — ou pire,
resterait « OK » après qu'une source soit passée C3. **Les six lignes C2 relevées débloqueront
leurs champs sans toucher ce fichier.**

### Le résultat, sans maquillage : 1 champ sur 17
**`real_rates` seul est alimentable aujourd'hui** (DFII10, ligne C1). Les seize autres sont
bloqués, chacun avec un motif vérifiable et recopié du registre :

| champ | motif |
|---|---|
| `d1` | `lei`, `sahm`, `ip` n'ont **aucune jambe BASE** — pas de divergence, et `cascade.aggregate` refuse de renormaliser sur les présentes (un D1 sur 45 % du poids se lirait comme un D1 complet) |
| `d2`, `d3` | ABSORBÉS par Arb1/Arb2 (poids 0 dans `DIMENSIONS`) — un score propre les compterait deux fois |
| `d4` | `d4_coeff` est un PARAMÈTRE à calibrer ; l'incohérence `d4_red_coeff` reste ouverte |
| `d5`, `beer_z` | `nfa` et `tot` sont C2 |
| `taylor_ois_delta` | `r_star_us` C2, `r_star_ez` C3 |
| `phillips_tips_delta` | `beta_phillips` à calibrer |
| `leading_turn`, `rr_zscore` | bloqués par `oecd_cli` / `bundei_real` (C2) |
| `bridgewater_matrix`, `g_momentum`, `pi_momentum`, `carry_net`, `cycle_div_delta`, `spot_momentum` | **aucune formule figée** au référentiel — le mock les fabrique ; en inventer une ici la ferait passer pour de la mesure (§8/§11) |

Ce n'est pas un échec du câblage : **c'est le câblage qui dit la vérité**. `python -m
app.external.macro_series` affiche les 17 champs avec leur motif, sans ouvrir une seule socket.

### Discipline de quota
Seules les séries d'une recette FAISABLE sont interrogées — **une aujourd'hui**, pas 53. Le
`fetcher` d'essai LÈVE sur toute clé hors périmètre : la discipline est vérifiée, pas espérée.

### Trouvé en câblant
- **`fetch_catalog` est un contrat de fait** : les sept clients l'implémentent, **aucun ne le
  déclare**. Typé localement (`CatalogClient` Protocol) avec un `cast` qui est l'aveu exact du
  trou — mêler un refactor de `providers` à ce câblage aurait violé la Loop 3. À remonter dans
  `HttpSeriesClient` lors d'une passe dédiée.
- **Une recette `DIRECT` mal formée tuait le worker** (`series[0]` sur un tuple vide) — et avec
  lui toute la macro, pour une faute de frappe dans la table.
- **Une clé d'API absente est un refus de POLITIQUE**, pas une panne réseau (D-050). Le worker ne
  meurt pas : le champ reste ABSENT, et le motif dit `renseigner FRED_API_KEY`.
- **Mon propre garde anti-seuils était trop large** : il attrapait un contrôle d'ARITÉ
  (`len(...) != 1`). Affiné plutôt que désactivé.

### Vérif
**21 tests** (dont 2 d'intégration) → **1244 passed**, ruff clean, mypy strict (15 fichiers).
Essai manuel bout à bout en replay : `real_rates = 2.03` arrive **FRESH**, `source=macro_feed`,
`flags=[MACRO_SERIES]`, dans `s2_state.cascade.real_rates`. Contrôle négatif : pont muet → champ
**ABSENT**, jamais un zéro. Démarrage avec `EXTERNAL_DATA=1` : aucun avertissement, le mock cède
`real_rates` en plus de `vix`/`macro_releases`.

### Reste ouvert
Les six lignes C2 à relever (une session, même protocole) débloqueront `d5`, `beer_z`,
`leading_turn`, `rr_zscore`. Les six champs SANS FORMULE attendent une décision du propriétaire de
la spec, pas du code. `d1` restera bloqué tant que `lei`/`sahm`/`ip` n'auront pas de jambe zone
euro — c'est un manque de SÉRIE, pas de câblage.

## D-062 · Sources externes Niveau 3 — alimenter F5 et F3, sans créer un second verrou
**Le cahier des charges demandait de créer `EconomicCalendarProvider`, `VixProvider` et
`getVixRegime()`. Ces trois contrats existaient déjà**, et les redoubler aurait été la pire
option possible sur un terminal qui journalise des décisions :

| demandé | existe déjà, et fait autorité |
|---|---|
| calendrier fort impact + fenêtre d'interdiction | `macro_risk.compute_macro_risk` → règle Phase 0 `MACRO_BLACKOUT` (D-040), verrou UNIQUE §2.2 |
| 2ᵉ couche calendrier (Porte F0 LSR) | `macro_news.MacroNewsProvider` (D-050) |
| régime de volatilité | `strategies.youssef.update_regime` — hystérésis D4 |
| seuil VIX critique | `config.VIX_CRIT = 30.0`, marqué **AUTORITÉ** |
| source VIX | ligne `vixcls` → FRED `VIXCLS`, **C1** au registre (D-057) |

Deux calendriers qui répondent différemment à « sommes-nous en blackout ? », c'est exactement la
panne que ce terminal existe pour empêcher. **Ce qui manquait n'était pas la logique : c'était la
SOURCE.** `macro_releases` et `vix` n'étaient remplis que par le mock ; en mode replay,
`tick_slow` n'écrivant rien, ils vieillissaient vers ABSENT et le garde tournait à vide.

`app/external/` transporte donc la donnée, les couches déterministes tranchent.
`is_high_impact_news_near()` et `get_vix_regime()` existent **avec la signature demandée**, mais
en pure délégation — l'API voulue, une seule source de vérité.

### Publié sous les noms de source que le moteur attend DÉJÀ
`macro_releases` sous `econ_feed`, `vix` sous `cboe` → **zéro ligne modifiée dans `engine.py`**.
Tout le pipeline aval fonctionne sans avoir été prévenu, et la couche de fraîcheur fait son
travail parce que l'horodatage publié est celui de l'**observation**, jamais `now`.

### L'écart entre les deux seuils VIX — ARBITRAGE TRANCHÉ
Le dépôt porte **deux systèmes de seuils VIX qui ne coïncident pas** : `VIX_CRIT = 30`
(AUTORITÉ, veto dur) et l'hystérésis D4 (ORANGE 26 → RED 37). **Un VIX à 32 est un veto Phase 0
mais seulement ORANGE au sens D4.** Personne ne l'avait écrit ; je l'ai soulevé sans le résoudre.

**Décision du propriétaire de la spec : les deux restent SÉPARÉS.** `VIX_CRIT` est un veto
d'**exécution** (« a-t-on le droit d'entrer ? ») ; l'hystérésis D4 module le **sizing** (« de
combien réduit-on la taille ? »). Deux questions distinctes, deux seuils distincts — l'écart
n'est pas une incohérence à corriger, c'est la conception.

Conséquence pratique : **ne jamais aligner ces nombres « pour la cohérence »**, ce qui
rabaisserait un veto de sécurité au rang d'un multiplicateur de taille (ou l'inverse). Trois
verrous plutôt qu'un commentaire :
1. `test_les_DEUX_systemes_de_seuils_VIX_restent_INDEPENDANTS` — échoue si `VIX_CRIT` prend la
   valeur d'un seuil D4, ou si la bande « veto sans RED » disparaît. **Vérifié en mutant
   `VIX_CRIT` à 26 puis à 37 : le test tombe dans les deux cas.**
2. `test_les_deux_faits_restent_DEUX_champs_jamais_un_mot_unique` — interdit qu'un `HIGH_VOL`
   unique réapparaisse et efface l'information que les deux couches ne s'accordent pas.
3. Un test par AST interdit tout littéral numérique de comparaison dans `app/external/vix.py`.

Un commentaire à `config.VIX_CRIT` pointe vers ces verrous — c'est là qu'un futur lecteur
regardera avant d'être tenté d'« harmoniser ».

### La promotion Tier-1 — un fail-OPEN corrigé
`build_macro_calendar` écarte tout événement dont l'`impact` n'est pas lisible. Correct pour du
bruit — mais écarter un NFP parce que le fournisseur a omis son champ **ouvrirait** le verrou au
pire moment. Quand l'impact est absent/illisible ET que le nom correspond à une publication
Tier-1 (NFP, CPI, FOMC, PPI, Jobless Claims…), l'événement est promu `HIGH`. On ne contredit
JAMAIS un impact explicite : le fournisseur qui dit « low » est cru, parce que le corriger serait
inventer.

### Ce que je n'ai pas pu vérifier
Le format Finnhub vient de sa **documentation, jamais d'une réponse réelle** — l'egress est
bloqué ici. Doctrine C2 : `FinnhubCalendar` porte `verified=False`, ce qui devient un drapeau
`SOURCE_NON_VERIFIEE` jusque dans le panneau. `scripts/validation_externe.py` lève le doute
depuis une machine avec du réseau et classe les échecs **par cause** (RÉSEAU / SERVICE / PARSING
/ CRASH) — un `✗ PARSING` est le résultat utile, il dit que la doc ment.
**Piège n° 1 = le fuseau, pas le format** : Finnhub renvoie une heure naïve, l'hypothèse UTC est
donc un paramètre EXPLICITE. Une heure d'écart déplace toute la fenêtre de blackout sans que rien
ne le signale (même classe de faute que ms/s en D-060).

### Défauts trouvés en maltraitant mon propre code (`/devil`)
- **Une fenêtre F5 à `NaN` devenait PERMISSIVE** : `max(0.0, nan)` rend `0.0` en Python, donc
  `near=False` — une autorisation de trader fondée sur une valeur absurde. Une fenêtre non finie
  est une faute d'APPEL, pas une condition de donnée → elle lève (doctrine D-050).
- **Un fournisseur qui LÈVE emportait toute la chaîne**, donc le repli — c'est-à-dire exactement
  ce pour quoi la chaîne existe. Il est désormais écarté, pas suivi.
- **`RecursionError` traversait le parser** sur un JSON profondément imbriqué (elle n'est pas une
  `ValueError`). Un flux qui fait exploser la pile est empoisonné, pas illisible : même issue.
- **`redact` ne couvrait que `api_key=`** alors que Finnhub utilise `token=`. Étendu à six noms
  de paramètre plutôt que dupliqué — un rédacteur qui rate un nom est une fuite en attente.
- **Aveugle ≠ calme** : sans calendrier utilisable, `news_near` rend `blind=True`, jamais
  `near=False`. Un cache fossile n'est plus une donnée mais un souvenir : rien n'est publié, le
  champ vieillit visiblement (le republier avec un horodatage frais le blanchirait).
- Mes deux propres tests étaient faux : le garde anti-seuils grepait la DOCSTRING (refait par
  AST) et j'attendais une distinction « série vide » que `providers._finish` ne fait pas.

### Limite CONNUE, héritée et assumée
`providers._finish` pose « rien de lisible = illisible, pas vide » — choix délibéré D-057. Un
jour de fermeture, VIXCLS ne publie que des « . » et le motif remonte « illisible ». Je n'invente
pas la distinction que je n'ai pas : `FredVix` ajoute l'indice qui évite de chercher une panne là
où il y a un jour férié. Par ailleurs une **clôture quotidienne ne peut pas honnêtement alimenter
un champ de canal rapide** : le drapeau `VIX_CLOTURE_<date>` part avec la valeur, et le repli
`TermStructureVix` (déjà intraday, déjà dans le terminal) passe avant.

### Vérif
**90 tests** (85 unitaires + 5 d'intégration) → **1218 passed**, ruff clean, mypy **strict** étendu
à `app/external` (14 fichiers), 125 vitest, tsc strict vert. **Essai manuel bout à bout, en mode
replay** (où le module est seul à écrire ces champs) : NFP à +60 s → `MACRO_BLACKOUT` avec le motif
« Nonfarm Payrolls dans la fenêtre ±15 min » ; le même à +2 h → bloqueur absent ; VIX externe à 34
→ `VIX_LIMIT : VIX 34.0 > 30`. Zéro ligne modifiée dans `engine.py`.

### Le conflit d'écriture mock ↔ externe — RÉSOLU par la propriété déclarée
Première version : `EXTERNAL_DATA=1` avec la source mock donnait **deux producteurs pour la même
clé** (`vix` à chaque tick rapide, `macro_releases` à chaque tick lent), et je m'étais contenté
d'un WARNING au démarrage. C'était insuffisant : la valeur finale dépendait de l'ordonnancement
des ticks, c'est-à-dire de rien. Un avertissement décrit un défaut, il ne le corrige pas.

**Corrigé en rendant la propriété explicite**, pas en éteignant le log :
`external.OWNED_FIELDS` déclare les champs que le module possède quand il est actif, et
`MockDataSource(skip_fields=…)` les retire de sa production — un seul point de passage (`_emit`).
Le mock **cesse réellement de les produire** ; il n'est pas simplement écrasé. La nuance n'est pas
cosmétique : être écrasé donne le même écran *par accident*, et le jour où l'ordre change, la
valeur change aussi.

**Contrepartie assumée, et c'est la bonne direction** : avec `EXTERNAL_DATA=1`, une source externe
muette rend ces champs **ABSENT** — Phase 0 bloque (fail-closed §3) au lieu d'afficher du mock
déguisé en donnée réelle. Le démarrage le dit en **INFO** (plus aucun avertissement) : quels
champs sont externalisés, et que muet = ABSENT.

Essai manuel, Redis vidé entre les deux :
- `EXTERNAL_DATA=1` + mock → aucun WARNING ; `vix = 28.5 flags=[EXTERNAL, EXTERNAL_FALLBACK]` ;
  `macro_releases` **ABSENT** (aucune source calendrier configurée) ; `econ_calendar` et `chop`
  toujours produits par le mock — on retire deux champs, pas une source.
- sans `EXTERNAL_DATA` → `vix = 13.72 source=cboe`, `macro_releases` mock : aucune régression.

Trois tests le verrouillent, dont le contrôle négatif (`test_sans_source_externe_le_mock_garde_
TOUTE_sa_production`) : sans lui, une bride toujours active priverait le stack démo de son VIX.

### Reste ouvert
Le format Finnhub à confirmer (`scripts/validation_externe.py` sur une machine réseau), puis
`verified=True`. C'est le dernier point ouvert de D-062 : l'écart `VIX_CRIT` / hystérésis D4 a été
**tranché** et le conflit d'écriture **résolu** (voir ci-dessus).

## D-061 · Le tape d'essai fabrique enfin de la microstructure — et dit ce qu'il ne peut pas
**Constat de départ, jamais formulé jusqu'ici.** Le générateur produisait des prints
indépendants : un tape statistiquement plausible, mais sans aucun des phénomènes que le Niveau 2
mesure. **B1, B3 et B4 n'étaient donc exercés que sur des scènes écrites à la main dans leurs
propres tests.** Rejouer mille ticks de bruit ne les faisait pas réagir — donc ne prouvait rien,
ni dans un sens ni dans l'autre. Le mock était propre là où ça comptait le plus (CLAUDE §4).

### Sept scènes scriptées (`app/replay/scenes.py`), intercalées dans le bruit
`sweep` (B4), `wall_refill` / `wall_fail` (B1), `absorption` (B1), `accumulation` (B2),
`rejection` / `double_bottom` (B3). Chacune rend sa **vérité terrain** — bornes, niveau de mur,
instant de sweep — écrite dans un sidecar `<tape>.truth.json`, **jamais dans le CSV** : une
colonne « scène » ferait fuiter la réponse dans la donnée. Aucune pathologie n'est injectée dans
une scène (une ligne écartée au milieu d'un sweep en ferait un demi-sweep).

**Ce que ça prouve, et ce que ça ne prouve pas.** Une scène scriptée peut INFIRMER : un mur qu'on
a fait recharger et qui ne produit aucun B1 est un défaut. Elle ne peut pas VALIDER : elle dit que
le calculateur réagit à ce qu'on a écrit, pas qu'il mesure le marché. Seul un vrai tape le dira.
Les attentes sont donc qualitatives (signe, ordre de grandeur) — réencoder la valeur exacte du
calculateur ferait un test qui se vérifie lui-même.

### Trois scènes n'existent que parce que la première version des tests était fausse
La suite a été éprouvée en **mutant le calculateur** (11 mutations : signes inversés, rapports
retournés, gardes retirées). Trois ont survécu, et chacune a révélé une scène trop complaisante :
- **B1 inversé passait.** Un mur qui se recharge intégralement donne ≈ 1 dans les deux sens.
  → `wall_fail` (rechargement PARTIEL) casse la symétrie.
- **B2 compté par PRINTS au lieu du volume passait.** Toutes mes scènes étaient unilatérales.
  → `accumulation` (30 petites ventes contre 5 gros achats) fait diverger les deux lectures.
- **B3 daté de la PREMIÈRE touche de l'extrême passait.** → `double_bottom`.

Deux mutations survivantes se sont révélées **couvertes ailleurs** (suite du calculateur), et une
troisième a montré un vrai trou : un sweep hors fenêtre rendait `None` par une autre garde, donc
retirer le contrôle de fenêtre ne changeait rien d'**observable**. Le motif est désormais asserté
(`test_B4_sweep_HORS_FENETRE_rend_None_ET_le_DIT`) — la leçon des `providers` : un mauvais motif
envoie chercher au mauvais endroit.

### `python -m app.replay.portes <fichier>` — et le constat inconfortable
Compagnon de `inspect` : celui-ci dit « ton fichier est-il lisible ? », celui-là « ce tape
peut-il faire parler B1-B4 ? ». Sur un export réel (sans vérité terrain), il balaie le fichier à
la fenêtre RÉELLE du terminal et compte combien de fois chaque porte sait répondre.

**Résultat sur notre propre tape : B2/B3/B4 répondent 100 % du temps, B1 seulement 3 %.** Motif :
`trou d'observation de 3.33s dans le carnet (> 2s)`. La cause n'est pas le calculateur — c'est
que **le replay ne publie un carnet que lorsqu'un print tombe**, donc tout creux de séance de plus
de 2 s devient un trou d'observation, et B1 refuse (à raison, §3) de mesurer une déplétion qu'il
n'a pas vue. Conséquence à dire franchement : **B1 n'est pas exploitable depuis un tape seul, il
lui faut un vrai flux L2.** Un tape CSV ne porte pas les mises à jour de carnet entre deux
trades ; prétendre le contraire inventerait de la donnée.

### Défauts trouvés en maltraitant mon propre code (`/devil`)
- **Un nom de scène mal orthographié était silencieusement ignoré** — `scenes=("sweeep", …)`
  produisait un tape sans sweep sans rien dire ; on aurait mesuré B4 dessus et conclu que la
  porte était cassée. Un défaut inventé de toutes pièces par une faute de frappe. → `ValueError`.
- **Un `.truth.json` corrompu emportait tout le diagnostic** par une trace de pile, alors que le
  tape, lui, est intact. → section omise avec le motif, balayage conservé.
- Tape trop court pour ses scènes → dit dans le bilan, plus silencieux.
- `_Book` renommé **`TapeBook`** (public) : l'outil de diagnostic et les tests s'en servent, et
  une deuxième reconstruction du carnet finirait par diverger de celle du terminal.

### Vérif
**26 tests** (dont 11 mutations du calculateur rejouées à la main) → **1128 passed**, ruff clean,
mypy strict clean (9 fichiers), 125 vitest, tsc strict vert. Essai manuel : générateur CLI,
`main_test`, et `portes` exécutés bout à bout sur un tape de 888 ticks.

`app.orderflow.*` et `app.volume_profile` entrent dans le graphe mypy avec `portes.py` ; ils sont
**exemptés explicitement** dans `pyproject.toml` plutôt qu'annotés au passage — mêler un refactor
du module de calcul le plus chargé du dépôt à une feature est précisément ce que la Loop 3
interdit.

## D-060 · Consommer un export tiers — Bookmap, sans connaître son format
**Le point de départ est un aveu** : je ne connais pas le format d'export de Bookmap. Inventer
des noms de colonnes aurait été exactement ce que la doctrine C2 interdit depuis D-057 — un
identifiant qui a l'air vérifié sans l'être. Plutôt que de deviner, on outille la question.

### `python -m app.replay.inspect <export.csv>`
Lit un échantillon d'un export RÉEL et **montre** : séparateur déduit, colonnes présentes,
candidats par rôle, unité d'horodatage, valeurs de côté observées. Il ne décide rien, et il
**refuse de proposer** une correspondance dès qu'un rôle requis est ambigu ou que l'unité de
temps est indéterminée.

### Les deux pièges d'un export tiers, traités explicitement
1. **L'unité de temps, pas le nom des colonnes.** Des millisecondes lues comme des secondes
   placent la séance en l'an 56 000 ; des nanosecondes, bien plus loin. Toutes les fenêtres
   d'order flow (B1/B4) deviennent alors absurdes **en restant crédibles**. L'unité se déduit de
   l'ORDRE DE GRANDEUR, se montre avant tout rejeu, et une unité indéterminée bloque la
   proposition.
2. **Le sens du côté agresseur.** `Bid` comme côté AGRESSÉ veut dire une **VENTE** — l'inverse
   de l'intuition, et l'erreur qui inverserait tout le delta agresseur sans qu'aucun nombre ne
   paraisse suspect. Une valeur de côté non traduite ne reçoit **jamais** de défaut : elle est
   signalée.

### Le fichier de l'opérateur n'est jamais réécrit
`Mapping` adapte le moteur au fichier, pas l'inverse. Un export de trades seuls (sans
profondeur) se rejoue parfaitement — il produit un tape sans carnet, ce qui EST la vérité
(D-055). Sans correspondance explicite, le format canonique reste le défaut : les 44 tests
existants passent sans modification.

### Le dialecte Bookmap est marqué `verified=False`
Ses noms de colonnes viennent de conventions courantes, **pas d'un fichier observé**. Un test
verrouille ce marquage. Il deviendra `verified=True` le jour où un en-tête réel l'aura confirmé,
pas avant.

### Deux défauts trouvés sur mon propre travail
- Le renifleur annonçait `AMBIGU : BidSize, BidSize` — la même colonne comptée deux fois
  (« bidsize » et « bid_size » se normalisent pareil). Une fausse alerte d'ambiguïté sur une
  détection correcte, de quoi faire douter d'un bon résultat.
- Mon garde anti-nom-en-dur (D-059) a refusé `dialects.py`. Il avait tort : « bookmap » y nomme
  un FORMAT DE FICHIER, pas l'identité de la source live — un opérateur peut rejouer un export
  Bookmap sur un terminal branché à Rithmic. Le garde est affiné, pas désactivé.

### Vérif
**24 tests** → **1099 passed**, ruff clean, mypy strict clean (7 fichiers). Démonstration sur un
export fictif « à la Bookmap » (`;`, millisecondes, `Ask`/`Bid`) : reconnu, correspondance
proposée, rejoué avec `Ask→BUY` et `Bid→SELL`.

### Reste ouvert (sans blocage)
Six lignes de catalogue à relever (3 clés SDMX en une session, la clé du Bund€i qui débloque
aussi `rdiff`), quatre connecteurs sur sept n'ont pas encore leur client d'interrogation
(Bundesbank, Socrata CFTC, SDMX international, Yahoo — URL et parsing sont là), et le câblage au
`ContextSchema`/aux panneaux n'est pas commencé.

## D-015 · Un opérateur par instance (AUTORITÉ `CLAUDE §9`)
`VITE_OPERATOR` (ou `?operator=YOUSSEF`) fixe l'instance ; défaut `SONY`. Tous les events
portent `operator`.
