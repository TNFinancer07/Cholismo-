"""Feature — pipeline carnet d'ordres (`s1_state.order_book`, D-025).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- le mock émet un carnet ES 10 niveaux (bids/asks triés, prix alignés au tick 0.25) ;
- le moteur l'expose en MetaField du canal rapide (FRESH → STALE → ABSENT comme tout
  champ — no signal without data) ;
- un carnet CROISÉ (best bid ≥ best ask) est détecté serveur → flag `CROSSED_BOOK` ;
- un carnet malformé est retiré (ABSENT + flag `MALFORMED`), jamais rendu comme réel ;
- AUCUN chemin d'exécution : l'affichage est lecture seule (§2.1) — rien à tester côté
  ordre car rien n'existe.
"""
import asyncio
import time

import pytest

from app import config
from app.datasource.mock import MockDataSource
from app.engine import Engine
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


def test_mock_emits_sorted_tick_aligned_book():
    async def scenario():
        state = RedisState()
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, True)
            mock = MockDataSource()
            raw = None
            for _ in range(10):        # les pathologies peuvent dropper un tick — on insiste
                await mock.tick_fast(state)
                raw = await state.read_raw("order_book")
                if raw is not None:
                    break
            assert raw is not None, "aucun carnet émis en 10 ticks"
            book = raw["value"]
            bids, asks = book["bids"], book["asks"]
            assert 1 <= len(bids) <= 10 and 1 <= len(asks) <= 10
            assert all(len(level) == 2 for level in bids + asks)
            assert bids == sorted(bids, key=lambda level: -level[0])   # bids décroissants
            assert asks == sorted(asks, key=lambda level: level[0])    # asks croissants
            assert all(abs(p / 0.25 - round(p / 0.25)) < 1e-6 for p, _ in bids + asks)
            assert all(s > 0 for _, s in bids + asks)
        finally:
            await state.close()
    _run(scenario())


def test_engine_exposes_order_book_and_ages_it():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, True)
            t0 = time.time()
            for _ in range(10):
                await engine.ds.tick_fast(state)
                if (await state.read_raw("order_book")) is not None:
                    break
            await engine._assemble_fast(t0)
            ob = engine.schema.s1_state.order_book
            assert ob.freshness == Freshness.FRESH
            assert isinstance(ob.value, dict) and ob.value["bids"] and ob.value["asks"]

            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, False)
            await engine._assemble_fast(t0 + 20)     # > FAST_ABSENT_SECONDS
            ob = engine.schema.s1_state.order_book
            assert ob.freshness == Freshness.ABSENT and ob.value is None
        finally:
            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, True)
            await state.close()
    _run(scenario())


def test_crossed_book_is_flagged_and_malformed_book_is_withheld():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            now = time.time()
            # Carnet croisé : best bid (5001.0) ≥ best ask (5000.75) — donnée réelle
            # pathologique, montrée MAIS flaggée.
            await state.write_raw("order_book",
                                  {"bids": [[5001.0, 10]], "asks": [[5000.75, 8]]},
                                  config.MICROSTRUCTURE_SOURCE, ts=now)
            await engine._assemble_fast(now)
            ob = engine.schema.s1_state.order_book
            assert ob.freshness == Freshness.FRESH
            assert "CROSSED_BOOK" in ob.flags

            # Carnet malformé : structure inexploitable → RETIRÉ (fail-closed §3),
            # jamais rendu comme un carnet réel.
            await state.write_raw("order_book", {"bids": "garbage"}, config.MICROSTRUCTURE_SOURCE, ts=now)
            await engine._assemble_fast(now)
            ob = engine.schema.s1_state.order_book
            assert ob.freshness == Freshness.ABSENT and ob.value is None
            assert "MALFORMED" in ob.flags
        finally:
            await state.close()
    _run(scenario())


# ---------- /devil — flux extrêmes et normalisation (Loop 4) ----------

def test_extreme_book_is_capped_sorted_and_deduped():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            # Feed hostile : 500 niveaux, NON triés, avec doublons de prix.
            bids = [[5000.0 - 0.25 * k, 10] for k in range(500)]
            bids.reverse()                                   # tri inversé volontaire
            bids.append([4999.75, 5])                        # doublon de prix
            asks = [[5000.25 + 0.25 * k, 10] for k in range(500)]
            asks.reverse()
            await state.write_raw("order_book", {"bids": bids, "asks": asks},
                                  config.MICROSTRUCTURE_SOURCE, ts=now)
            await engine._assemble_fast(now)
            ob = engine.schema.s1_state.order_book
            assert ob.freshness == Freshness.FRESH
            assert len(ob.value["bids"]) == 10 and len(ob.value["asks"]) == 10  # borné
            prices = [p for p, _ in ob.value["bids"]]
            assert prices == sorted(prices, reverse=True)    # canonisé décroissant
            assert prices[0] == 5000.0                       # les MEILLEURS niveaux gardés
            assert ob.value["asks"][0][0] == 5000.25
            # doublon agrégé : 4999.75 apparaît UNE fois, taille sommée 10+5
            dup = [s for p, s in ob.value["bids"] if p == 4999.75]
            assert dup == [15]
        finally:
            await state.close()
    _run(scenario())


def test_non_finite_or_non_positive_levels_withhold_the_book():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            for bad in ({"bids": [[float("nan"), 10]], "asks": [[5000.25, 8]]},
                        {"bids": [[5000.0, 0]], "asks": [[5000.25, 8]]},
                        {"bids": [[5000.0, -4]], "asks": [[5000.25, 8]]},
                        {"bids": [[float("inf"), 10]], "asks": [[5000.25, 8]]}):
                await state.write_raw("order_book", bad, config.MICROSTRUCTURE_SOURCE, ts=now)
                await engine._assemble_fast(now)
                ob = engine.schema.s1_state.order_book
                assert ob.freshness == Freshness.ABSENT and ob.value is None, bad
                assert "MALFORMED" in ob.flags
        finally:
            await state.close()
    _run(scenario())
