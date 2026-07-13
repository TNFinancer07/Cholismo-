"""Feature — architecture LangGraph de détection de Liquidity Sweep (D-028).

Comportement figé AVANT implémentation (Loop 1 étape 3). Contrainte cardinale : la
détection est STRICTEMENT DÉTERMINISTE — aucun LLM, aucun hasard, aucune valeur inventée
(« sans hallucination », §2.8/§7). Le graphe orchestre ; le déclencheur est du code à seuils.

- GraphState porte `delta_volume`, `spread_width` (en TICKS), `best_bid_ask_depth`, plus le
  contexte de déclenchement (`tape_burst`, `news_t1_imminent`, `data_ok`) et les sorties ;
- déclencheur = (rafale de tape OU spread > 2 ticks) COUPLÉ à une news Tier-1 imminente ;
- fail-closed (§3) : données absentes/périmées → JAMAIS d'alerte inventée ; l'état distingue
  « pas de sweep » (data_ok) de « impossible à évaluer » (not data_ok) ;
- n'émet qu'une ALERTE (événement observé), jamais un ordre (§2.1) ;
- reproductible : même entrée → même sortie (preuve d'absence de LLM/hasard).
"""
import time

from app.graph.liquidity_sweep import (
    BURST_COUNT_THRESHOLD,
    SPREAD_TICKS_THRESHOLD,
    LiquiditySweepAlert,
    build_graph,
    build_sweep_inputs,
    run_sweep_detection,
    SWEEP_GRAPH,
)
from app.meta import Freshness, MetaField
from app.schema import ContextSchema


def _state(**over):
    base = dict(now=1000.0, data_ok=True, tape_burst=False, spread_width=1.0,
                best_bid_ask_depth=(50.0, 50.0), delta_volume=0.0,
                news_t1_imminent=False, news_label="", triggered=False, alert=None, reason="")
    base.update(over)
    return base


def test_graph_fires_alert_on_coupled_anomaly_and_news():
    out = SWEEP_GRAPH.invoke(_state(tape_burst=True, spread_width=3.0,
                                    news_t1_imminent=True, news_label="NFP — emplois US",
                                    delta_volume=120.0))
    assert out["triggered"] is True
    alert = out["alert"]
    assert alert is not None
    assert alert["kind"] == "LIQUIDITY_SWEEP"
    assert alert["direction"] == "ASK_SWEEP"          # delta_volume > 0 → agression acheteuse
    assert "TAPE_BURST" in alert["trigger"] and "WIDE_SPREAD" in alert["trigger"]
    assert alert["news_context"] == "NFP — emplois US"
    assert alert["spread_width"] == 3.0
    # « sans hallucination » : chaque champ dérive des entrées, la raison les cite.
    assert "news" in alert["reason"].lower()


def test_no_alert_without_news_coupling():
    out = SWEEP_GRAPH.invoke(_state(tape_burst=True, spread_width=3.0, news_t1_imminent=False))
    assert out["triggered"] is False
    assert out["alert"] is None
    assert "coupl" in out["reason"].lower()            # anomalie non couplée à une news


def test_no_alert_without_micro_anomaly():
    out = SWEEP_GRAPH.invoke(_state(tape_burst=False, spread_width=1.0, news_t1_imminent=True))
    assert out["triggered"] is False
    assert out["alert"] is None
    assert "anomalie" in out["reason"].lower()


def test_fail_closed_on_missing_data_never_hallucinates():
    # Données incomplètes MAIS conditions partielles alléchantes (burst + news vrais) :
    # le verrou fail-closed doit gagner — aucune alerte inventée sur données absentes.
    out = SWEEP_GRAPH.invoke(_state(data_ok=False, tape_burst=True, spread_width=5.0,
                                    news_t1_imminent=True, delta_volume=200.0))
    assert out["triggered"] is False
    assert out["alert"] is None
    assert "insuffisant" in out["reason"].lower() or "fail" in out["reason"].lower()


def test_detection_is_deterministic_reproducible():
    s = _state(tape_burst=True, spread_width=4.0, news_t1_imminent=True, delta_volume=-80.0)
    a = SWEEP_GRAPH.invoke(dict(s))
    b = SWEEP_GRAPH.invoke(dict(s))
    assert a["triggered"] == b["triggered"] is True
    assert a["alert"] == b["alert"]                    # bit-à-bit identique → ni LLM ni hasard
    assert a["alert"]["direction"] == "BID_SWEEP"      # delta_volume < 0 → agression vendeuse


def test_spread_exactly_at_threshold_does_not_trigger():
    # Strictement « > 2 ticks » : exactement 2 ne déclenche pas (pas de rafale non plus).
    out = SWEEP_GRAPH.invoke(_state(spread_width=float(SPREAD_TICKS_THRESHOLD),
                                    news_t1_imminent=True))
    assert out["triggered"] is False


# ---------- câblage au ContextSchema réel (fail-closed sur la fraîcheur) ----------

def _fresh(value, now):
    return MetaField(value=value, last_update_ts=now, source="test", freshness=Freshness.FRESH)


def test_build_sweep_inputs_wires_schema_and_fires():
    now = time.time()
    schema = ContextSchema()
    # order book FRESH : spread large (best_ask 5001.00 − best_bid 5000.00 = 4 ticks).
    schema.s1_state.order_book = _fresh(
        {"bids": [[5000.00, 40.0]], "asks": [[5001.00, 30.0]]}, now)
    # tape FRESH : rafale (>= seuil de prints récents), agression acheteuse nette.
    prints = [{"ts": now, "price": 5000.0, "size": 2, "side": "BUY", "seq": i}
              for i in range(BURST_COUNT_THRESHOLD + 2)]
    schema.s1_state.tape = _fresh(prints, now)
    # calendrier FRESH : NFP Tier-1 dans 5 min (imminent).
    schema.econ_calendar.events = _fresh(
        [{"ts": now + 300, "name": "NFP — emplois US", "tier": 1, "region": "US"}], now)

    st = build_sweep_inputs(schema, now)
    assert st["data_ok"] is True
    assert st["spread_width"] == 4.0
    assert st["tape_burst"] is True
    assert st["news_t1_imminent"] is True and st["news_label"] == "NFP — emplois US"

    out = run_sweep_detection(schema, now)
    assert out["triggered"] is True
    assert out["alert"]["direction"] == "ASK_SWEEP"


def test_build_sweep_inputs_fail_closed_when_order_book_stale():
    now = time.time()
    schema = ContextSchema()
    # order book ABSENT (défaut) + tape ABSENT → micro non évaluable → data_ok False,
    # même si le calendrier annonce une news T1 : on ne peut pas confirmer → pas d'alerte.
    schema.econ_calendar.events = _fresh(
        [{"ts": now + 100, "name": "FOMC", "tier": 1, "region": "US"}], now)
    st = build_sweep_inputs(schema, now)
    assert st["data_ok"] is False
    out = run_sweep_detection(schema, now)
    assert out["triggered"] is False and out["alert"] is None


def test_graph_compiles_with_checkpointer_architecture():
    # Architecture LangGraph « checkpoint-ready » (§4) : le graphe se compile avec un
    # checkpointer et s'invoque avec un thread_id sans casser le déterminisme.
    from langgraph.checkpoint.memory import MemorySaver
    graph = build_graph(checkpointer=MemorySaver())
    out = graph.invoke(_state(tape_burst=True, spread_width=3.0, news_t1_imminent=True),
                       config={"configurable": {"thread_id": "test-sweep"}})
    assert out["triggered"] is True
    assert isinstance(LiquiditySweepAlert(**out["alert"]), LiquiditySweepAlert)


# ---------- /devil — contradictions, croisé, désync, corruption (Loop 4) ----------

def test_crossed_book_is_flagged_anomaly_not_silently_ignored():
    # bid > ask → spread NÉGATIF. Dislocation réelle près d'une news : DOIT déclencher,
    # labellisé CROSSED_BOOK — jamais confondu avec un spread propre, jamais ignoré.
    out = SWEEP_GRAPH.invoke(_state(spread_width=-2.0, news_t1_imminent=True))
    assert out["triggered"] is True
    assert "CROSSED_BOOK" in out["alert"]["trigger"]


def test_locked_book_zero_spread_triggers_crossed():
    out = SWEEP_GRAPH.invoke(_state(spread_width=0.0, news_t1_imminent=True))
    assert out["triggered"] is True
    assert "CROSSED_BOOK" in out["alert"]["trigger"]


def test_non_finite_spread_never_triggers_nor_leaks():
    for bad in (float("inf"), float("nan"), float("-inf")):
        out = SWEEP_GRAPH.invoke(_state(spread_width=bad, tape_burst=False,
                                        news_t1_imminent=True))
        assert out["triggered"] is False, f"spread {bad} a déclenché (fail-closed attendu)"
        assert out["alert"] is None


def test_delta_volume_corruption_does_not_leak_into_alert():
    for bad in (float("inf"), float("nan")):
        out = SWEEP_GRAPH.invoke(_state(tape_burst=True, spread_width=3.0,
                                        news_t1_imminent=True, delta_volume=bad))
        assert out["triggered"] is True
        a = out["alert"]
        assert a["delta_volume"] is None, f"delta_volume {bad} a fui dans l'alerte"
        assert a["direction"] is None            # direction indéterminée sur delta corrompu


def test_burst_from_future_dated_prints_is_not_fabricated():
    now = time.time()
    schema = ContextSchema()
    schema.econ_calendar.events = _fresh(
        [{"ts": now + 300, "name": "NFP", "tier": 1, "region": "US"}], now)
    # rafale de prints tous DATÉS DANS LE FUTUR (+50 s) — désync d'horloge source.
    future = [{"ts": now + 50, "price": 5000.0, "size": 2, "side": "BUY", "seq": i}
              for i in range(BURST_COUNT_THRESHOLD + 5)]
    schema.s1_state.tape = _fresh(future, now)
    st = build_sweep_inputs(schema, now)
    assert st["tape_burst"] is False, "rafale FABRIQUÉE par des prints futurs (désync)"


def test_delta_volume_ignores_non_finite_sizes_in_tape():
    import math as _m
    now = time.time()
    schema = ContextSchema()
    schema.econ_calendar.events = _fresh(
        [{"ts": now + 100, "name": "FOMC", "tier": 1, "region": "US"}], now)
    schema.s1_state.tape = _fresh([
        {"ts": now, "price": 5000.0, "size": 10, "side": "BUY", "seq": 1},
        {"ts": now, "price": 5000.0, "size": float("inf"), "side": "BUY", "seq": 2},
        {"ts": now, "price": 5000.0, "size": 4, "side": "SELL", "seq": 3},
    ], now)
    st = build_sweep_inputs(schema, now)
    assert st["delta_volume"] is not None and _m.isfinite(st["delta_volume"])
    assert st["delta_volume"] == 6.0             # 10 (BUY) − 4 (SELL), l'inf écarté


def test_contradiction_orderbook_fresh_tape_absent_no_fabricated_direction():
    # Order book FRESH large + news, mais tape ABSENT → sweep sur spread SANS direction
    # inventée (pas de tape pour confirmer l'agresseur).
    now = time.time()
    schema = ContextSchema()
    schema.s1_state.order_book = _fresh(
        {"bids": [[5000.00, 40.0]], "asks": [[5001.00, 30.0]]}, now)     # 4 ticks
    schema.econ_calendar.events = _fresh(
        [{"ts": now + 200, "name": "NFP", "tier": 1, "region": "US"}], now)
    st = build_sweep_inputs(schema, now)
    assert st["data_ok"] is True and st["spread_width"] == 4.0
    assert st["delta_volume"] is None
    out = run_sweep_detection(schema, now)
    assert out["triggered"] is True
    assert out["alert"]["direction"] is None     # pas de tape → pas de direction inventée
    assert "WIDE_SPREAD" in out["alert"]["trigger"]
