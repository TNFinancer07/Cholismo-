"""Feature — pipeline Tape / Time & Sales (`s1_state.tape`, D-026).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- le mock maintient une FENÊTRE GLISSANTE de prints (transactions observées) et émet les
  N plus récents ; chaque print = {ts, price, size, side ∈ BUY|SELL, seq} ;
- le moteur l'expose en MetaField du canal rapide (FRESH → STALE → ABSENT — no signal
  without data) ; fenêtre bornée à TAPE_WINDOW, prints les plus récents en tête ;
- un print malformé (prix/taille non fini ou ≤ 0, side invalide) est ÉCARTÉ ; si plus
  aucun print exploitable → tape RETIRÉ (ABSENT + flag MALFORMED, fail-closed §3) ;
- AUCUN chemin d'exécution : ce sont les prints OBSERVÉS du marché, pas les ordres de
  l'opérateur (§2.1) — rien à tester côté ordre car rien n'existe.
"""
import asyncio
import time

import pytest

from app.datasource.mock import MockDataSource
from app.engine import TAPE_WINDOW, Engine
from app.meta import Freshness
from app.redis_state import RedisState


def _redis_available() -> bool:
    async def probe() -> bool:
        state = RedisState()
        try:
            return await state.ping()
        finally:
            await state.close()
    return asyncio.run(probe())


pytestmark = pytest.mark.skipif(not _redis_available(),
                                reason="Redis indisponible — intégration sautée")


def _run(coro):
    return asyncio.run(coro)


def test_mock_emits_rolling_well_formed_prints():
    async def scenario():
        state = RedisState()
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up("sierra_chart", True)
            mock = MockDataSource()
            raw = None
            for _ in range(30):
                await mock.tick_fast(state)
                raw = await state.read_raw("tape")
                if raw is not None and len(raw["value"]) >= 5:
                    break
            assert raw is not None, "aucun tape émis"
            prints = raw["value"]
            assert 1 <= len(prints) <= TAPE_WINDOW
            for p in prints:
                assert set(p) >= {"ts", "price", "size", "side", "seq"}
                assert p["side"] in ("BUY", "SELL")
                assert p["price"] > 0 and p["size"] > 0
            # seq strictement croissant dans le temps → plus récent en TÊTE après moteur.
            seqs = [p["seq"] for p in prints]
            assert seqs == sorted(seqs), "l'ordre brut du mock est chronologique"
        finally:
            await state.close()
    _run(scenario())


def test_engine_exposes_tape_most_recent_first_and_ages_it():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up("sierra_chart", True)
            t0 = time.time()
            for _ in range(30):
                await engine.ds.tick_fast(state)
                await engine._assemble_fast(t0)
                tape = engine.schema.s1_state.tape
                if tape.value and len(tape.value) >= 5:
                    break
            tape = engine.schema.s1_state.tape
            assert tape.freshness == Freshness.FRESH
            assert len(tape.value) <= TAPE_WINDOW
            seqs = [p["seq"] for p in tape.value]
            assert seqs == sorted(seqs, reverse=True), "affichage : plus récent en tête"

            await state.set_source_up("sierra_chart", False)
            await engine._assemble_fast(t0 + 20)     # > FAST_ABSENT_SECONDS
            tape = engine.schema.s1_state.tape
            assert tape.freshness == Freshness.ABSENT and tape.value is None
        finally:
            await state.set_source_up("sierra_chart", True)
            await state.close()
    _run(scenario())


def test_malformed_prints_are_dropped_and_empty_tape_is_withheld():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            # Fenêtre mixte : 1 print sain + 3 pourris → seul le sain survit.
            await state.write_raw("tape", [
                {"ts": now, "price": 5000.25, "size": 4, "side": "BUY", "seq": 1},
                {"ts": now, "price": float("nan"), "size": 4, "side": "SELL", "seq": 2},
                {"ts": now, "price": 5000.0, "size": 0, "side": "BUY", "seq": 3},
                {"ts": now, "price": 5000.0, "size": 3, "side": "XX", "seq": 4},
            ], "sierra_chart", ts=now)
            await engine._assemble_fast(now)
            tape = engine.schema.s1_state.tape
            assert tape.freshness == Freshness.FRESH
            assert [p["seq"] for p in tape.value] == [1]     # seul le print sain

            # Fenêtre entièrement pourrie → RETIRÉE (jamais un tape inventé).
            await state.write_raw("tape", [
                {"ts": now, "price": -1, "size": 4, "side": "BUY", "seq": 5},
                {"ts": now, "price": 5000.0, "size": float("inf"), "side": "SELL", "seq": 6},
            ], "sierra_chart", ts=now)
            await engine._assemble_fast(now)
            tape = engine.schema.s1_state.tape
            assert tape.freshness == Freshness.ABSENT and tape.value is None
            assert "MALFORMED" in tape.flags
        finally:
            await state.close()
    _run(scenario())


# ---------- /devil — rafales, désordre, robustesse par-print (Loop 4) ----------

def test_burst_is_bounded_to_window_and_ordered(monkeypatch):
    """Rafale hostile 5000 prints, seq mélangés → sortie = 40 plus récents, triés."""
    import random as _r
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            burst = [{"ts": now, "price": 5000.0 + (s % 8) * 0.25, "size": 1 + s % 5,
                      "side": "BUY" if s % 2 else "SELL", "seq": s} for s in range(1, 5001)]
            _r.Random(1).shuffle(burst)
            await state.write_raw("tape", burst, "sierra_chart", ts=now)
            await engine._assemble_fast(now)
            tape = engine.schema.s1_state.tape
            assert tape.freshness == Freshness.FRESH
            assert len(tape.value) == TAPE_WINDOW                 # DOM borné
            seqs = [p["seq"] for p in tape.value]
            assert seqs == sorted(seqs, reverse=True)             # plus récent en tête
            assert seqs[0] == 5000                                # les plus récents gardés
        finally:
            await state.close()
    _run(scenario())


def test_duplicate_seq_is_deduped_stable_react_keys():
    """seq dupliqué (feed multi-thread) → une seule occurrence (clés React uniques)."""
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            await state.write_raw("tape", [
                {"ts": now, "price": 5000.0, "size": 3, "side": "BUY", "seq": 5},
                {"ts": now, "price": 5000.5, "size": 7, "side": "SELL", "seq": 5},  # doublon
                {"ts": now, "price": 5001.0, "size": 2, "side": "BUY", "seq": 6},
            ], "sierra_chart", ts=now)
            await engine._assemble_fast(now)
            tape = engine.schema.s1_state.tape
            seqs = [p["seq"] for p in tape.value]
            assert len(seqs) == len(set(seqs)), f"seq dupliqués dans la sortie : {seqs}"
        finally:
            await state.close()
    _run(scenario())


def test_one_structurally_broken_print_does_not_discard_the_window():
    """Un print sans clé / prix non numérique est écarté SEUL — les valides survivent."""
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            await state.write_raw("tape", [
                {"ts": now, "price": 5000.0, "size": 3, "side": "BUY", "seq": 1},
                {"ts": now, "price": "oops", "size": 3, "side": "SELL", "seq": 2},  # ValueError
                {"size": 3, "side": "BUY", "seq": 3},                                # KeyError price
                {"ts": now, "price": 5001.0, "size": 2, "side": "SELL", "seq": 4},
            ], "sierra_chart", ts=now)
            await engine._assemble_fast(now)
            tape = engine.schema.s1_state.tape
            assert tape.freshness == Freshness.FRESH
            assert sorted(p["seq"] for p in tape.value) == [1, 4]  # les 2 valides survivent
        finally:
            await state.close()
    _run(scenario())
