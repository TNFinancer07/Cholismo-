"""LangGraph — détecteur de Liquidity Sweep (D-028).

Architecture graph-state (CLAUDE §4) au service d'une détection **strictement déterministe** :
aucun LLM, aucun hasard, aucune valeur inventée (« sans hallucination », §2.8/§7). Le graphe
*orchestre* (nœuds + arêtes conditionnelles, checkpoint-ready) ; la *décision* est du code à
seuils booléens, reproductible bit-à-bit.

Un « liquidity sweep » = anomalie microstructure (RAFALE de tape OU spread > 2 ticks) COUPLÉE
à une fenêtre de news Tier-1 imminente — la liquidité s'évapore autour des publications, les
carnets se creusent et se font balayer. Le couplage (ET) est le cœur du signal : une anomalie
seule n'est pas un sweep, une news seule non plus.

Fail-closed (§3) : données absentes/périmées → JAMAIS d'alerte inventée. L'état distingue
explicitement « pas de sweep » (`data_ok=True, triggered=False`) de « impossible à évaluer »
(`data_ok=False`) — un détecteur honnête ne confond pas « tout va bien » et « je ne sais pas ».

Le graphe n'émet qu'une **ALERTE** (événement observé, à afficher/scorer en async), jamais un
ordre (§2.1). Il n'est PAS câblé dans le hot path live par cette tranche (une feature par
commit) ; comme il est déterministe, il *pourra* l'être (< 200 ms, §7) — le câblage moteur
périodique est l'incrément suivant.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..meta import Freshness
from ..schema import ContextSchema

# --- Seuils v1 provisional — calibration owner: Sony. Isolés ici (CLAUDE §8/§12). ---
TICK_SIZE = 0.25              # ES : 1 tick = 0.25 pt
SPREAD_TICKS_THRESHOLD = 2.0  # spread STRICTEMENT > 2 ticks = carnet anormalement large
BURST_WINDOW_S = 2.0          # fenêtre de mesure de la rafale de prints
BURST_COUNT_THRESHOLD = 8     # ≥ N prints dans la fenêtre = rafale de tape
NEWS_T1_IMMINENT_S = 30 * 60  # news Tier-1 à ±30 min (fenêtre blackout Sony, D-027)


class LiquiditySweepAlert(BaseModel):
    """Sortie du graphe — un événement OBSERVÉ, jamais un ordre (§2.1). Tous les champs
    dérivent déterministiquement des entrées : aucune probabilité inventée."""
    ts: float
    kind: str = "LIQUIDITY_SWEEP"
    direction: Optional[str] = None      # BID_SWEEP | ASK_SWEEP | None (delta_volume nul/absent)
    spread_width: Optional[float] = None  # en ticks
    delta_volume: Optional[float] = None
    trigger: str = ""                     # TAPE_BURST | WIDE_SPREAD | TAPE_BURST+WIDE_SPREAD
    news_context: str = ""                # libellé de la news T1 déclenchante
    reason: str = ""                      # explication déterministe, lisible


class SweepGraphState(TypedDict, total=False):
    """État du graphe. Les mesures sont extraites du ContextSchema (fail-closed sur la
    fraîcheur) ; `None` = donnée non exploitable, jamais une valeur inventée."""
    now: float
    # mesures microstructure
    delta_volume: Optional[float]              # imbalance agresseur nette sur la fenêtre tape
    spread_width: Optional[float]              # (best_ask − best_bid) / TICK_SIZE, en ticks
    best_bid_ask_depth: Optional[tuple]        # (taille@meilleur bid, taille@meilleur ask)
    # contexte de déclenchement (déterministe)
    tape_burst: bool
    news_t1_imminent: bool
    news_label: str
    data_ok: bool                              # verrou fail-closed : entrées suffisantes ?
    # sorties
    triggered: bool
    alert: Optional[dict]
    reason: str


def _wide_spread(state: SweepGraphState) -> bool:
    spread = state.get("spread_width")
    return spread is not None and spread > SPREAD_TICKS_THRESHOLD


def _detect(state: SweepGraphState) -> dict:
    """Nœud de décision — 100 % déterministe. Ordre des gardes = ordre des raisons.
    Fail-closed d'abord : sans données suffisantes, on ne prononce jamais de sweep."""
    if not state.get("data_ok"):
        return {"triggered": False,
                "reason": "données microstructure/news insuffisantes — fail-closed, aucune alerte"}
    burst = bool(state.get("tape_burst"))
    wide = _wide_spread(state)
    if not (burst or wide):
        return {"triggered": False,
                "reason": "pas d'anomalie microstructure (ni rafale de tape ni spread large)"}
    if not state.get("news_t1_imminent"):
        return {"triggered": False,
                "reason": "anomalie microstructure hors fenêtre news T1 — non couplée, pas de sweep"}
    parts = [p for p, cond in (("TAPE_BURST", burst), ("WIDE_SPREAD", wide)) if cond]
    return {"triggered": True,
            "reason": "sweep : " + "+".join(parts) + " couplé à une news T1 imminente"}


def _emit(state: SweepGraphState) -> dict:
    """Nœud d'émission — construit l'alerte à partir des seules entrées (rien d'inventé)."""
    dv = state.get("delta_volume")
    direction = None
    if dv is not None and dv != 0:
        direction = "ASK_SWEEP" if dv > 0 else "BID_SWEEP"  # agression acheteuse balaie l'offre
    parts = [p for p, cond in (("TAPE_BURST", bool(state.get("tape_burst"))),
                               ("WIDE_SPREAD", _wide_spread(state))) if cond]
    alert = LiquiditySweepAlert(
        ts=state["now"],
        direction=direction,
        spread_width=state.get("spread_width"),
        delta_volume=dv,
        trigger="+".join(parts),
        news_context=state.get("news_label", ""),
        reason=state.get("reason", ""),
    )
    return {"alert": alert.model_dump()}


def build_graph(checkpointer: Optional[BaseCheckpointSaver] = None):
    """Fabrique + compile le graphe. `checkpointer` optionnel (MemorySaver en test, SqliteSaver
    en prod — §4) : l'architecture est checkpoint-ready sans que la détection en dépende."""
    g = StateGraph(SweepGraphState)
    g.add_node("detect", _detect)
    g.add_node("emit", _emit)
    g.add_edge(START, "detect")
    g.add_conditional_edges("detect", lambda s: "emit" if s.get("triggered") else END,
                            {"emit": "emit", END: END})
    g.add_edge("emit", END)
    return g.compile(checkpointer=checkpointer)


# Détecteur sans état : chaque évaluation est indépendante et reproductible (idéal « sans
# hallucination »). Le checkpointing (§4) sert l'orchestration STATEFUL — incrément suivant.
SWEEP_GRAPH = build_graph()


def build_sweep_inputs(schema: ContextSchema, now: float) -> SweepGraphState:
    """Câblage : extrait l'état du graphe du ContextSchema, fail-closed sur la fraîcheur
    (seules les données FRESH sont exploitées — STALE/ABSENT ⇒ `None`, jamais inventé)."""
    ob = schema.s1_state.order_book
    tp = schema.s1_state.tape
    cal = schema.econ_calendar.events

    # Carnet FRESH → spread (ticks) + profondeur au meilleur niveau.
    spread: Optional[float] = None
    depth: Optional[tuple] = None
    ob_fresh = ob.freshness == Freshness.FRESH and isinstance(ob.value, dict)
    if ob_fresh:
        bids, asks = ob.value.get("bids"), ob.value.get("asks")
        if bids and asks:
            spread = (float(asks[0][0]) - float(bids[0][0])) / TICK_SIZE
            depth = (float(bids[0][1]), float(asks[0][1]))

    # Tape FRESH → rafale (prints dans la fenêtre) + delta_volume (imbalance agresseur).
    burst = False
    delta_volume: Optional[float] = None
    tp_fresh = tp.freshness == Freshness.FRESH and isinstance(tp.value, list) and bool(tp.value)
    if tp_fresh:
        recent = sum(1 for p in tp.value
                     if isinstance(p.get("ts"), (int, float)) and p["ts"] > now - BURST_WINDOW_S)
        burst = recent >= BURST_COUNT_THRESHOLD
        delta_volume = float(sum((p["size"] if p.get("side") == "BUY" else -p["size"])
                                 for p in tp.value))

    # Calendrier FRESH → news Tier-1 imminente (±30 min).
    news = False
    news_label = ""
    cal_fresh = cal.freshness == Freshness.FRESH and isinstance(cal.value, list)
    if cal_fresh:
        for e in cal.value:
            if e.get("tier") == 1 and abs(float(e["ts"]) - now) <= NEWS_T1_IMMINENT_S:
                news, news_label = True, str(e.get("name", ""))
                break

    # data_ok : on ne peut trancher (« pas de sweep » vs « sweep ») que si le micro est
    # évaluable (carnet OU tape frais) ET l'état news connu (calendrier frais). Sinon
    # « impossible à évaluer » → fail-closed, aucune alerte (§3).
    data_ok = (spread is not None or tp_fresh) and cal_fresh

    return SweepGraphState(
        now=now, delta_volume=delta_volume, spread_width=spread, best_bid_ask_depth=depth,
        tape_burst=burst, news_t1_imminent=news, news_label=news_label, data_ok=data_ok,
        triggered=False, alert=None, reason="")


def run_sweep_detection(schema: ContextSchema, now: float,
                        thread_id: str = "sweep") -> SweepGraphState:
    """Détection de bout en bout sur le ContextSchema courant. Déterministe, sans état
    partagé entre appels (SWEEP_GRAPH n'a pas de checkpointer)."""
    state = build_sweep_inputs(schema, now)
    return SWEEP_GRAPH.invoke(state, config={"configurable": {"thread_id": thread_id}})
