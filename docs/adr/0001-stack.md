# ADR 0001 — Décision de stack (Loop 0) · RÉSOLU

- **Statut** : ✅ accepté (rétrospectif — décision prise à l'Étape 0, formalisée ici par `/stack`)
- **Décideur** : opérateur (spec `CLAUDE.md §4`) ; l'ADR documente, il ne re-décide pas
- **Portée** : tout le terminal Cholismo (backend, frontend, orchestration, IA, données)

## Contexte

Terminal de trading human-in-the-loop (ES/NQ + EUR/USD), un seul mainteneur, contraintes
dures non négociables (`CLAUDE §2`) : hot path déterministe < ~200 ms sans LLM synchrone,
fail-closed, event store append-only, SSE segmenté par cadence, UI dense clavier-first.
Le choix devait tenir **pour la durée, pas la mode**, et rester maintenable par une
personne.

## Options considérées

| Option | Verdict |
|---|---|
| **Python FastAPI + React/Vite** (retenue) | async natif (`asyncio`) pour les boucles fast/slow, Pydantic v2 = schéma typé miroir TS, SSE simple, écosystème IA ; React/TS/Tailwind = densité + vitesse d'itération UI |
| Node full-stack (Fastify/Next) | event loop native mais Pydantic-équivalent moins net pour le `ContextSchema` ; écosystème IA/analyse moins direct |
| TUI pur (textual/blessed) | densité clavier idéale mais rendu multi-panneaux riches (matrices, jauges, sparklines, deux instances opérateur) trop coûteux à maintenir seul |

## Décision (figée, `CLAUDE §4`)

- **Backend** : Python 3.11 · FastAPI (REST + SSE) · Pydantic v2 · Redis (état intra-session) · SQLite (event store append-only, triggers `RAISE ABORT`)
- **Frontend** : React 18 + TypeScript strict · Vite · Tailwind · zustand (store unique) · SSE 2 canaux
- **Orchestration** : n8n (workflows) · LangGraph (graph-state, checkpointing SQLite) — hors hot path
- **IA** : Claude (scoring async) · Groq (advisory Phase 0, < 100 ms fail-closed) · Gemini (audit 20 trades) — jamais synchrones dans le hot path
- **Données** : interface unique `MarketDataSource` swappable ; `MockDataSource` pathologique en démo

### Test & lint (figés par cet ADR)
- **Backend** : `pytest` (invariants dans `backend/tests/`) · `ruff` (lint, config `backend/pyproject.toml`)
- **Frontend** : `tsc --noEmit` strict = gate de type/lint (`npm run typecheck`) ; ESLint **non retenu**
  (poids/entretien pour un mainteneur unique — le typage strict + revue Loop 4 couvrent le besoin ;
  re-décision possible par ADR ultérieur)
- **E2E** : Playwright piloté ad hoc (captures `docs/`) — l'essai manuel réel reste obligatoire (`/done`)

## Conséquences

- Toute boucle backend suit `RUNTIME_LOOPS.md` (asyncio : jamais d'appel bloquant en coroutine).
- Le squelette « démarre puis s'arrête proprement » est prouvé (lifespan FastAPI : engine/AI/redis fermés en `finally`).
- **Toute déviation de ce stack = nouvel ADR** (`docs/adr/NNNN-*.md`), jamais une décision implicite.
