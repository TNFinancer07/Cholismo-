---
name: stack
description: Décision de stack (Loop 0, CLAUDE §13). RÉSOLU pour Cholismo (§4). N'invoquer qu'en cas de remise en cause majeure de la base technique, avec un ADR dans docs/adr/.
argument-hint: [remise en cause à trancher]
---

# /stack — Loop 0 · décision de stack

> ✅ **RÉSOLU pour Cholismo** (CLAUDE §4). Stack figé : FastAPI + Pydantic v2 + Redis + SSE + SQLite /
> React + TS + Vite + Tailwind + zustand / LangGraph + n8n. Boucle conservée pour mémoire.

À ne rejouer qu'en cas de **remise en cause majeure**, jamais par défaut.

## Étapes
1. Lister 2-3 candidats réalistes.
2. Comparer (rendu, async, testabilité, poids, maintenabilité).
3. Écrire l'ADR `docs/adr/NNNN-<sujet>.md` (contexte, options, décision, conséquences).
4. Figer runtime, paquets, framework de test, linter.
5. Squelette « démarre puis s'arrête proprement » (cf. `RUNTIME_LOOPS.md` Loop A + H).

## Sortie
ADR écrit, squelette démarre/s'arrête sans erreur, tests & lint tournent.

## Garde-fou
Maintenable par une seule personne. On choisit **pour la durée, pas la mode**. Toute déviation de §4 est un ADR, pas une décision implicite.
