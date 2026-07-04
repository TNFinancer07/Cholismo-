"""LangGraph — graph-state du pipeline d'analyse asynchrone (Étape 10.4).

Invariant non négociable (CLAUDE §4/§7) : **Phase 0 déterministe est appliquée AVANT tout
appel Claude**. Le nœud d'entrée lit le verdict du backend ; si BLOQUÉ, le graphe
court-circuite en fail-closed et n'appelle jamais le LLM. Checkpointing SQLite pour
reprendre un graphe interrompu. Rien ici n'est dans le hot path live.

Dépendances (non installées par défaut — hors MVP) :
    pip install langgraph langgraph-checkpoint-sqlite httpx
"""
from __future__ import annotations

import os
from typing import Any, TypedDict

import httpx

BACKEND = os.getenv("CHOLISMO_BACKEND", "http://localhost:8000")
CHECKPOINT_DB = os.getenv("LANGGRAPH_CHECKPOINT_DB", "orchestration/langgraph/checkpoints.db")


class AnalysisState(TypedDict, total=False):
    phase0: str                 # OPEN | BLOCKED — lu du backend, jamais recalculé ici
    blockers: list[str]
    schema_snapshot: dict[str, Any]
    claude_commentary: str | None
    aborted_reason: str | None


def phase0_gate(state: AnalysisState) -> AnalysisState:
    """Nœud d'entrée : lit le verrou déterministe. BLOQUÉ (ou backend muet) => abort."""
    try:
        snapshot = httpx.get(f"{BACKEND}/state", timeout=5.0).json()
        identity = snapshot["schema"]["session_identity"]
        state["phase0"] = identity["phase0"]
        state["blockers"] = [b["rule"] for b in identity["phase0_blockers"]]
        state["schema_snapshot"] = snapshot["schema"]
    except Exception as exc:  # backend injoignable -> fail-closed
        state["phase0"] = "BLOCKED"
        state["aborted_reason"] = f"backend unreachable ({type(exc).__name__})"
    if state["phase0"] != "OPEN":
        state["aborted_reason"] = state.get("aborted_reason") or "phase0 BLOCKED — fail-closed"
    return state


def claude_scoring(state: AnalysisState) -> AnalysisState:
    """Nœud Claude (async/périodique) — n'est JAMAIS atteint si Phase 0 est bloquée."""
    # L'appel réel vit dans backend/app/ai/tasks.py ; ce nœud illustre le point d'entrée
    # LangGraph et resterait borné en coût/latence, loggé dans ai_calls.
    state["claude_commentary"] = "delegated to backend AITasks (bounded, logged)"
    return state


def build_graph():
    """Assemble le graphe si langgraph est installé. Import paresseux volontaire."""
    from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]
    from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]

    graph = StateGraph(AnalysisState)
    graph.add_node("phase0_gate", phase0_gate)
    graph.add_node("claude_scoring", claude_scoring)
    graph.set_entry_point("phase0_gate")
    graph.add_conditional_edges(
        "phase0_gate",
        lambda s: "claude_scoring" if s.get("phase0") == "OPEN" else END,
        {"claude_scoring": "claude_scoring", END: END},
    )
    graph.add_edge("claude_scoring", END)
    checkpointer = SqliteSaver.from_conn_string(CHECKPOINT_DB)
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    result = phase0_gate({})
    print("phase0:", result.get("phase0"), "| abort:", result.get("aborted_reason"))
