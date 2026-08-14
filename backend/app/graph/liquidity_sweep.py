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

import math
from typing import Optional, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from ..meta import Freshness
# LiquiditySweepAlert vit dans le schéma (source unique) — le graphe le RÉUTILISE, pas de
# duplication ni d'import circulaire (schema n'importe pas graph).
from ..schema import ContextSchema, LiquiditySweepAlert

# --- Seuils v1 provisional — calibration owner: Sony. Isolés ici (CLAUDE §8/§12). ---
TICK_SIZE = 0.25              # ES : 1 tick = 0.25 pt
SPREAD_TICKS_THRESHOLD = 2.0  # spread STRICTEMENT > 2 ticks = carnet anormalement large
BURST_WINDOW_S = 2.0          # fenêtre de mesure de la rafale de prints
BURST_COUNT_THRESHOLD = 8     # ≥ N prints dans la fenêtre = rafale de tape
NEWS_T1_IMMINENT_S = 30 * 60  # news Tier-1 à ±30 min (fenêtre blackout Sony, D-027)


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


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _spread_anomaly(state: SweepGraphState) -> tuple[bool, Optional[str]]:
    """(anomalie ?, label) — durci /devil. Un spread doit être FINI pour compter (inf/nan =
    donnée corrompue → n'anomalise rien, fail-closed §3). Deux dislocations distinctes :
    spread > 2 ticks = WIDE_SPREAD (liquidité mince) ; spread ≤ 0 = CROSSED_BOOK (bid ≥ ask,
    marché verrouillé/croisé). Le croisé n'est JAMAIS ignoré en silence — c'est la dislocation
    la plus extrême, souvent le cœur d'un sweep — mais il est labellisé à part pour que
    l'humain le vérifie (peut aussi être un glitch de données)."""
    spread = state.get("spread_width")
    if not _finite(spread):
        return (False, None)
    if spread > SPREAD_TICKS_THRESHOLD:
        return (True, "WIDE_SPREAD")
    if spread <= 0:
        return (True, "CROSSED_BOOK")
    return (False, None)


def _trigger_parts(state: SweepGraphState) -> list[str]:
    parts = []
    if bool(state.get("tape_burst")):
        parts.append("TAPE_BURST")
    anom, label = _spread_anomaly(state)
    if anom and label:
        parts.append(label)
    return parts


def _detect(state: SweepGraphState) -> dict:
    """Nœud de décision — 100 % déterministe. Ordre des gardes = ordre des raisons.
    Fail-closed d'abord : sans données suffisantes, on ne prononce jamais de sweep."""
    if not state.get("data_ok"):
        return {"triggered": False,
                "reason": "données microstructure/news insuffisantes — fail-closed, aucune alerte"}
    burst = bool(state.get("tape_burst"))
    anom, _ = _spread_anomaly(state)
    if not (burst or anom):
        return {"triggered": False,
                "reason": "pas d'anomalie microstructure (ni rafale de tape ni spread anormal)"}
    if not state.get("news_t1_imminent"):
        return {"triggered": False,
                "reason": "anomalie microstructure hors fenêtre news T1 — non couplée, pas de sweep"}
    return {"triggered": True,
            "reason": "sweep : " + "+".join(_trigger_parts(state))
            + " couplé à une news T1 imminente"}


def _emit(state: SweepGraphState) -> dict:
    """Nœud d'émission — construit l'alerte à partir des seules entrées (rien d'inventé).
    Durci /devil : toute mesure NON FINIE (inf/nan) est retirée (→ None), jamais propagée
    dans l'alerte (sinon JSON invalide en aval + direction fantôme)."""
    dv = state.get("delta_volume")
    dv = dv if _finite(dv) else None
    direction = None
    if dv is not None and dv != 0:
        direction = "ASK_SWEEP" if dv > 0 else "BID_SWEEP"  # agression acheteuse balaie l'offre
    spread = state.get("spread_width")
    spread = spread if _finite(spread) else None
    alert = LiquiditySweepAlert(
        ts=state["now"],
        direction=direction,
        spread_width=spread,
        delta_volume=dv,
        trigger="+".join(_trigger_parts(state)),
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
            s = (float(asks[0][0]) - float(bids[0][0])) / TICK_SIZE
            spread = s if math.isfinite(s) else None   # spread corrompu → None, pas propagé
            depth = (float(bids[0][1]), float(asks[0][1]))

    # Tape FRESH → rafale (prints dans la fenêtre) + delta_volume (imbalance agresseur).
    burst = False
    delta_volume: Optional[float] = None
    tp_fresh = tp.freshness == Freshness.FRESH and isinstance(tp.value, list) and bool(tp.value)
    if tp_fresh:
        # Durci /devil : fenêtre BORNÉE des deux côtés `]now−W, now]`. Un print daté DANS LE
        # FUTUR (ts > now, désync d'horloge source) est exclu — son heure d'arrivée réelle
        # est inconnue, il ne doit pas FABRIQUER une rafale.
        recent = sum(1 for p in tp.value if _finite(p.get("ts"))
                     and now - BURST_WINDOW_S < p["ts"] <= now)
        burst = recent >= BURST_COUNT_THRESHOLD
        # Durci /devil : taille NON FINIE (inf/nan) écartée par-print — jamais un
        # delta_volume corrompu (la leçon per-print du /devil Tape, portée ici).
        dv = 0.0
        for p in tp.value:
            sz = p.get("size")
            if not _finite(sz):
                continue
            dv += sz if p.get("side") == "BUY" else -sz
        delta_volume = dv

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
