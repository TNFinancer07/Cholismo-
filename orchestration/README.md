# /orchestration — n8n + LangGraph

Câblé à l'Étape 10 (`TASKS.md`) — **post-MVP**. Structure posée au bootstrap (0.1).

- `n8n/workflows/` — workflows JSON importables (streak-audit, routing risque).
- `langgraph/` — graph-state avec checkpointing SQLite. **Phase 0 déterministe est
  appliquée AVANT tout appel Claude** (`CLAUDE §4`) : le nœud d'entrée du graphe lit le
  verdict Phase 0 du backend et court-circuite en fail-closed si `BLOCKED`.

Aucun de ces composants n'est dans le hot path live (< ~200 ms, `CLAUDE §7`).
