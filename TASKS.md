# TASKS.md — Plan d'exécution (ordonné, MVP-first)

Réfs : `CLAUDE.md` (contraintes dures + priorité §10) · `PRD.md` (spec panneau par panneau).
Exécute **dans l'ordre**. Ne construis pas la phase N+1 avant que N tourne. Commit atomique
par tâche. Avant toute UI, ouvre `/reference/MANIFEST.md` et n'extrais que les blocs `AUTORITÉ`.

---

## Étape 0 — Bootstrap
- [x] 0.1 Monorepo : `/frontend` (Vite+React+TS+Tailwind+shadcn/ui), `/backend` (FastAPI),
      `/orchestration` (n8n+LangGraph), `docker-compose.yml`, `DECISIONS.md`.
- [x] 0.2 `/reference/` + `MANIFEST.md` classant chaque bloc `AUTORITÉ` vs `PLACEHOLDER` (`CLAUDE §11`).
- [x] 0.3 Tokens couleur : Sony cyan · Youssef violet · Router **or** ; risque VERT/JAUNE/ROUGE
      **+ forme/icône** (accessibilité daltonien). Dark, monospace.
- [x] 0.4 `docker-compose up` : FastAPI + Redis + SQLite + n8n démarrent ensemble.
      *(config compose validée ; daemon indisponible dans l'env de dev → services validés lancés directement)*

## Étape 1 — ContextSchema (fondation)
- [x] 1.1 Pydantic `ContextSchema` — 6 blocs, **chaque champ avec `meta{value,last_update_ts,
      source,freshness}`** (`PRD §0`).
- [x] 1.2 Type TS miroir + store frontend unique (vues = projections).
- [x] 1.3 **SSE segmenté par cadence** : canal rapide (`s1`,`bridge`,`sync`,`signal`) / lent
      (`s2`,`cascade`,`matrix`). Events partiels par bloc (`CLAUDE §6`).
- [x] 1.4 Helper de rendu `FRESH/STALE/ABSENT` réutilisable par tous les panneaux.

## Étape 2 — Adaptateur de données mocké (+ pathologies)
- [x] 2.1 Interface `MarketDataSource` swappable ; `MockDataSource`.
- [x] 2.2 **Injecter les pathologies** : ticks manquants, données en retard, valeurs
      contradictoires entre sources, NaN, désync d'horloge (`CLAUDE §4`). Un mock propre est un piège.
- [x] 2.3 Scénarios : Calme · News EUR Tier 1 · Streak loss · VIX spike · Custom. Sliders
      VIX/CHOP/CVD/GEX/RMS. Seuils `CHOP≥61.8` crit · `VIX>30` crit · `RMS≥3` warn/crit.
- [x] 2.4 Mock → Redis → schéma → SSE. Vérifier que STALE/ABSENT s'affiche vraiment quand on
      coupe une source.

# ── MVP (bloquant) : harnais de discipline pour prendre & prouver 50 trades ──

## Étape 3 — Phase 0 déterministe + Zone 0 + nav clavier
- [x] 3.1 **Moteur de règles Phase 0 déterministe** (booléens checklist), fail-closed si
      dépendance down/lente. Groq **advisory** seulement, jamais le verrou (`CLAUDE §2.2`).
- [x] 3.2 Layout 5 zones + barre statut : horloge Montréal+CET, marqueur session (teinte fond),
      3 modes, **Phase 0 géant OUVERT/BLOQUÉ**, glyphe état maître, badge opérateur.
- [x] 3.3 Nav clavier : focus A/B/C, Go/No-Go, modes, vues ; indicateur de focus.

## Étape 4 — B4 signal + Go/No-Go + Decision Log event-sourced
- [x] 4.1 Event store SQLite **append-only** (aucun UPDATE/DELETE) : `DecisionEvent`,
      `OutcomeEvent`, `ReconEvent` (`PRD §Zone D`). État courant = projection.
- [x] 4.2 B4 Unified Signal : barre segmentée 35/25/20/15/5. Si macro non calibré →
      **poids Macro=0, renormaliser /80, bandeau `degraded`** (`PRD §A3`/§0).
- [x] 4.3 Boutons Go/No-Go → écrivent un `DecisionEvent`. **Aucune exécution d'ordre.**
- [x] 4.4 C5 self-check cognitif **obligatoire** (bloque le Go). C3 countdown 90 s →
      **expiration = auto `NO_GO` reason=timeout**, jamais d'entrée forcée.

## Étape 5 — Calibration + Réconciliation (preuve comportementale)
- [x] 5.1 C4 : deux jauges distinctes (quanti + comportemental), N/60, sizing 50 % verrouillé,
      Sharpe courant, trades → 50+. Validation séquentielle impossible par design.
- [x] 5.2 C2 streak → audit forcé à 8.
- [x] 5.3 **Import CSV NinjaTrader** → match aux `DecisionEvent` (ts+instrument) → `ReconEvent` ;
      flag `matched=false` sur GO sans fill / fill sans GO (`PRD §Réconciliation`).
- [x] 5.4 Calcul Sharpe depuis les `OutcomeEvent` réconciliés. **Result score après 20+ trades seulement.**

> **Gate MVP** : à ce stade tu peux prendre un trade, être bloqué par Phase 0, voir le score,
> décider, logger immuablement, réconcilier avec l'exécution réelle, suivre calibration+Sharpe.
> Ne pas continuer avant que ça tourne end-to-end.

# ── Post-MVP ──

## Étape 6 — Zone A (macro) + B1/B2/B3
- [x] 6.1 A1 cascade (`real_rates` en exergue), rendu STALE par nœud.
- [x] 6.2 A3 `compute_s2_macro_score()` isolée, `NON CALIBRÉ` par défaut, intrants visibles,
      **ne pilote rien avant validation Youssef**.
- [x] 6.3 B1 états S1(cyan)/S2(violet). B2 GEX + **âge de donnée** (pas countdown), STALE au
      seuil. B3 sync verdict.
- [x] 6.4 A2 heatmap Bridgewater (encodage non-couleur en plus).

## Étape 7 — Console orchestrateur
- [x] 7.1 Arbitrage **déterministe** 6 sources, VERT/JAUNE/ROUGE(+forme), actions, fail-closed,
      payload JSON temps réel. Extraire blocs `AUTORITÉ` uniquement.

## Étape 8 — Vues par mode (3)
- [x] 8.1 Pré-session (briefing + JSON). 
- [x] 8.2 Live : Mode Live (RMS 5 couches, chat refusant si VIX>30/CHOP≥61.8, glossaire) —
      arbres conditionnels `PLACEHOLDER` sauf `AUTORITÉ`.
- [x] 8.3 Post-session (rapport JSON strict + audit Gemini async 20 trades).

## Étape 9 — Onglet Prompts & Contextes
- [x] 9.1 6 blocs copiables, extraits de `/reference/`, rien d'inventé.

## Étape 10 — Câblage IA (async, hors hot path)
- [x] 10.1 Groq advisory Phase 0 (<100 ms, fail-closed). 
- [x] 10.2 Claude scoring **async/périodique** (jamais synchrone live) ; borner + logger coût/latence.
- [x] 10.3 Gemini audit 20 trades async.
- [x] 10.4 n8n (streak, routing) + LangGraph (graph-state, checkpointing SQLite) ; Phase 0
      appliquée **avant** appel Claude.

## Étape 11 — Finitions
- [x] 11.1 Chaque panneau trace à un champ du schéma (sinon supprimer).
- [x] 11.2 Repasser les 8 contraintes dures `CLAUDE §2` (ordre auto interdit · Phase 0
      déterministe/inviolable · event store append-only · fail-closed · Claude hors hot path).
- [x] 11.3 README (lancer, changer de scénario, brancher un vrai feed) + `DECISIONS.md` à jour.

---

### Definition of done (allégé — pas de suite de tests imposée)
Stack up via docker-compose, end-to-end sur données mockées **avec pathologies**, STALE/ABSENT
rendus, Phase 0 déterministe bloque réellement, Go/No-Go écrit des events immuables, réconciliation
NinjaTrader + Sharpe fonctionnent, aucun chemin ne passe d'ordre automatiquement.
