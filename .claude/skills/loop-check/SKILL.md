---
name: loop-check
description: Auditer une boucle runtime du terminal Cholismo contre les pièges de RUNTIME_LOOPS.md (busy-wait, blocage, race, backpressure, exception avalée, sortie propre, retry aveugle). À utiliser sur engine.py, ai/tasks.py, ou toute boucle async. Audit LECTURE SEULE — ne corrige rien sans accord.
argument-hint: <fichier ou boucle à auditer>
---

# /loop-check — transverse · audit de boucle runtime

Audite une boucle *dans* le terminal contre les pièges connus de `RUNTIME_LOOPS.md` (Loops A–H).

## Étapes
1. **Busy-wait / blocage** — la boucle attend-elle toujours un event/tick/I/O ? (jamais 100 % CPU ; jamais d'appel bloquant dans une coroutine → `await asyncio.sleep`, `run_in_executor`).
2. **Race & backpressure** — écriture d'état partagé protégée ? un tick lent empile-t-il les suivants ? (sauter/annuler si le précédent n'est pas fini).
3. **Exceptions avalées** — tout `except` logge et repart ? pas de worker qui meurt en silence.
4. **Sortie propre & retry** — arrêt gracieux (Loop H) ? retry seulement sur transitoire, avec plafond + jitter (Loop E).

## Pistes connues Cholismo (note INSTALL)
- `engine._fast_loop` ET `engine._slow_loop` compensent la durée du tick
  (`sleep(max(plancher, CADENCE − elapsed))`) — dérive `_slow_loop` **corrigée**
  (régression : `tests/test_engine_loops.py`).
- `ai/tasks.py` : 3 `sleep` fixes (Groq 30 s, Claude période settings, Gemini poll 60 s)
  — périodicités **best-effort assumées**, pas des contrats de cadence (CLAUDE §6 ne
  couvre que les canaux SSE du schéma). Ne pas « corriger » sans contrat.
- Vérifier la **remontée de l'âge de la donnée à l'écran** (STALE/ABSENT) sur coupure de source.

## Sortie
Rapport : boucle → piège (ou OK) → correctif proposé. **Rien modifié sans validation.**

## Garde-fou
Audit **lecture seule**. Ne corrige pas sans accord explicite (un correctif = une Loop 2/3 séparée).
