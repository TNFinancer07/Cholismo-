"""Feature — Calendrier économique (`econ_calendar.events`, D-027).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- le mock émet une liste d'événements macro/géo PROGRAMMÉS, chacun
  {ts, name, tier ∈ 1|2|3, region} ; bloc SYSTÉMIQUE, canal LENT ;
- le moteur l'expose en MetaField trié par heure (le plus PROCHE en tête), borné à
  CAL_WINDOW, avec escalade FRESH → STALE → ABSENT (no signal without data, §3) ;
- un événement malformé (ts non fini, tier hors {1,2,3}, name vide, clé manquante) est
  ÉCARTÉ SEUL ; plus aucun exploitable → calendrier RETIRÉ (ABSENT + MALFORMED) ;
- doublons (ts, name, region) dédupliqués (clés React stables) ;
- AUCUNE exécution : événements OBSERVÉS/annoncés, pas des ordres de l'opérateur (§2.1).
  Le compte à rebours est une dérivation CLIENT du `ts` CONNU — honnête, contraste B2 §8.2.
"""
import asyncio
import math
import time

import pytest

from app.datasource.mock import MockDataSource
from app.engine import CAL_WINDOW, Engine
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


def test_mock_emits_scheduled_tiered_events():
    async def scenario():
        state = RedisState()
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up("econ_feed", True)
            mock = MockDataSource()
            raw = None
            for _ in range(5):
                await mock.tick_slow(state)
                raw = await state.read_raw("econ_calendar")
                if raw is not None and raw["value"]:
                    break
            assert raw is not None, "aucun calendrier émis"
            events = raw["value"]
            assert isinstance(events, list) and len(events) >= 1
            # §4 : le flux BRUT peut contenir une pathologie injectée (événement cassé) —
            # le moteur l'écarte (test dédié). Ici on prouve que le PLANNING bien formé est
            # émis : sous-ensemble strictement valide non vide.
            good = [e for e in events
                    if {"ts", "name", "tier", "region"} <= set(e)
                    and isinstance(e["ts"], (int, float)) and math.isfinite(e["ts"])
                    and e["tier"] in (1, 2, 3) and str(e["name"]).strip()]
            assert len(good) >= 5, "le calendrier programmé n'est pas émis"
        finally:
            await state.close()
    _run(scenario())


def test_engine_exposes_calendar_soonest_first_and_ages_it():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            await state.write_raw("econ_calendar", [
                {"ts": now + 300, "name": "NFP — emplois US", "tier": 1, "region": "US"},
                {"ts": now - 90, "name": "IPC zone euro", "tier": 2, "region": "EU"},
                {"ts": now + 1800, "name": "Stocks EIA", "tier": 3, "region": "US"},
            ], "econ_feed", ts=now)
            await engine._assemble_slow(now)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.FRESH
            assert len(cal.value) <= CAL_WINDOW
            tss = [e["ts"] for e in cal.value]
            assert tss == sorted(tss), "le plus proche/passé en tête (tri chronologique)"

            # Feed vieilli très au-delà du seuil ABSENT → retiré, jamais d'événement fantôme.
            await engine._assemble_slow(now + 3600)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.ABSENT and cal.value is None
        finally:
            await state.close()
    _run(scenario())


def test_malformed_events_dropped_and_empty_withheld():
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            # Fenêtre mixte : 1 sain + doublon + 3 pourris → sain + 1 occurrence du doublon.
            await state.write_raw("econ_calendar", [
                {"ts": now + 60, "name": "FOMC", "tier": 1, "region": "US"},
                {"ts": now + 60, "name": "FOMC", "tier": 1, "region": "US"},   # doublon exact
                {"ts": float("nan"), "name": "X", "tier": 1, "region": "US"},  # ts non fini
                {"ts": now + 90, "name": "Y", "tier": 9, "region": "US"},      # tier invalide
                {"name": "Z", "tier": 2, "region": "EU"},                      # clé ts manquante
            ], "econ_feed", ts=now)
            await engine._assemble_slow(now)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.FRESH
            names = [e["name"] for e in cal.value]
            assert names == ["FOMC"], f"seul le sain dédupliqué survit : {names}"

            # Fenêtre entièrement pourrie → RETIRÉE (jamais un calendrier inventé).
            await state.write_raw("econ_calendar", [
                {"ts": float("inf"), "name": "A", "tier": 1, "region": "US"},
                {"ts": now, "name": "", "tier": 2, "region": "EU"},
            ], "econ_feed", ts=now)
            await engine._assemble_slow(now)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.ABSENT and cal.value is None
            assert "MALFORMED" in cal.flags
        finally:
            await state.close()
    _run(scenario())


# ---------- /devil — désync, planning passé, rafale simultanée (Loop 4) ----------

def test_far_past_events_never_starve_upcoming_ones():
    """20 événements passés lointains + 3 à venir (dont un T1) → les à-venir SURVIVENT
    au cap CAL_WINDOW. Un cap naïf « 12 plus anciens » cacherait un NFP imminent."""
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            past = [{"ts": now - 7200 - i * 60, "name": f"Ancien {i}", "tier": 3,
                     "region": "US"} for i in range(20)]
            upcoming = [
                {"ts": now + 600, "name": "NFP — emplois US", "tier": 1, "region": "US"},
                {"ts": now + 1200, "name": "Fed", "tier": 1, "region": "US"},
                {"ts": now + 1800, "name": "EIA", "tier": 3, "region": "US"},
            ]
            await state.write_raw("econ_calendar", past + upcoming, "econ_feed", ts=now)
            await engine._assemble_slow(now)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.FRESH
            names = [e["name"] for e in cal.value]
            assert "NFP — emplois US" in names, f"le T1 imminent a été jeté : {names}"
            assert {"Fed", "EIA"} <= set(names), f"les à-venir ont été jetés : {names}"
        finally:
            await state.close()
    _run(scenario())


def test_fully_elapsed_schedule_is_empty_fresh_not_malformed():
    """Planning entièrement passé (au-delà de la grâce ±30 min) → FRESH + liste VIDE
    (« aucun événement dans la fenêtre »), PAS un faux PAS DE DONNÉES : le feed vit,
    il n'a juste rien de pertinent. MALFORMED reste réservé aux données pourries."""
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            await state.write_raw("econ_calendar", [
                {"ts": now - 7200, "name": "Vieux 1", "tier": 2, "region": "EU"},
                {"ts": now - 3600, "name": "Vieux 2", "tier": 1, "region": "US"},
            ], "econ_feed", ts=now)
            await engine._assemble_slow(now)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.FRESH
            assert cal.value == [], f"attendu liste vide, reçu : {cal.value}"
            assert "MALFORMED" not in cal.flags
        finally:
            await state.close()
    _run(scenario())


def test_simultaneous_burst_is_deduped_bounded_with_unique_keys():
    """Rafale : 30 publications DISTINCTES à la même seconde + doublons exacts →
    doublons fusionnés, distinctes conservées jusqu'au cap, clés (ts,name,region) uniques."""
    async def scenario():
        state = RedisState()
        engine = Engine(MockDataSource(), state)
        try:
            now = time.time()
            burst = [{"ts": now + 900, "name": f"Publication {i}", "tier": 1 + i % 3,
                      "region": "US"} for i in range(30)]
            burst += burst[:5]   # doublons exacts (feed qui bégaie)
            await state.write_raw("econ_calendar", burst, "econ_feed", ts=now)
            await engine._assemble_slow(now)
            cal = engine.schema.econ_calendar.events
            assert cal.freshness == Freshness.FRESH
            assert len(cal.value) == CAL_WINDOW                     # borné
            keys = [(e["ts"], e["name"], e["region"]) for e in cal.value]
            assert len(keys) == len(set(keys)), "clés React dupliquées"
        finally:
            await state.close()
    _run(scenario())
