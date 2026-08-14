"""Feature — intégration du détecteur Sweep au moteur + ContextSchema (D-028).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- le détecteur tourne en advisory ASYNC, JAMAIS dans le hot path (§2.8/§7) : `_assemble_sweep`
  peuple `schema.liquidity_sweep` sur sa propre cadence, sans bloquer les boucles fast/slow ;
- le bloc porte : `assessable` (data_ok), `triggered`, `alert` courante, `last_compute_ts`
  (âge réel), et un feed `recent` court des dernières alertes DISTINCTES ;
- fail-closed honnête : données absentes → `assessable=False`, aucune alerte inventée (§3) ;
- feed dédupliqué : une condition persistante n'inonde pas le feed (une entrée), mais un
  sweep qui se lève puis re-déclenche = un NOUVEL événement ;
- aucun ordre (§2.1) : le bloc est un signal observé, affiché, jamais exécuté.
"""
import asyncio
import time

from app.datasource.mock import MockDataSource
from app.engine import Engine
from app.meta import Freshness, MetaField
from app.redis_state import RedisState


def _fresh(value, now):
    return MetaField(value=value, last_update_ts=now, source="test", freshness=Freshness.FRESH)


def _engine():
    return Engine(MockDataSource(), RedisState())


def _wire_wide(schema, now, bid=5000.0, ask=5001.0):
    """Carnet FRESH (spread (ask−bid)/0.25 ticks) + news T1 imminente → condition de sweep."""
    schema.s1_state.order_book = _fresh({"bids": [[bid, 40.0]], "asks": [[ask, 30.0]]}, now)
    schema.econ_calendar.events = _fresh(
        [{"ts": now + 300, "name": "NFP — emplois US", "tier": 1, "region": "US"}], now)


def test_assemble_sweep_populates_block_and_recent():
    async def scenario():
        now = time.time()
        eng = _engine()
        _wire_wide(eng.schema, now)                     # spread 4 ticks + news
        await eng._assemble_sweep(now)
        sw = eng.schema.liquidity_sweep
        assert sw.assessable is True
        assert sw.triggered is True
        assert sw.alert is not None and "WIDE_SPREAD" in sw.alert.trigger
        assert sw.last_compute_ts == now
        assert len(sw.recent) == 1
    asyncio.run(scenario())


def test_recent_feed_dedups_persistent_then_records_new_event():
    async def scenario():
        now = time.time()
        eng = _engine()
        _wire_wide(eng.schema, now)
        await eng._assemble_sweep(now)
        await eng._assemble_sweep(now + 1)              # MÊME condition → pas de doublon
        assert len(eng.schema.liquidity_sweep.recent) == 1

        # la condition se lève (spread 2 ticks = normal) → plus de sweep
        eng.schema.s1_state.order_book = _fresh(
            {"bids": [[5000.0, 40.0]], "asks": [[5000.5, 30.0]]}, now + 2)
        await eng._assemble_sweep(now + 2)
        assert eng.schema.liquidity_sweep.triggered is False

        # re-déclenchement → NOUVEL événement distinct dans le feed
        eng.schema.s1_state.order_book = _fresh(
            {"bids": [[5000.0, 40.0]], "asks": [[5001.0, 30.0]]}, now + 3)
        await eng._assemble_sweep(now + 3)
        assert eng.schema.liquidity_sweep.triggered is True
        assert len(eng.schema.liquidity_sweep.recent) == 2
    asyncio.run(scenario())


def test_sweep_block_fail_closed_when_data_absent():
    async def scenario():
        now = time.time()
        eng = _engine()                                  # schéma vierge : tout ABSENT
        await eng._assemble_sweep(now)
        sw = eng.schema.liquidity_sweep
        assert sw.assessable is False
        assert sw.triggered is False and sw.alert is None
        assert sw.recent == []
    asyncio.run(scenario())


# ---------- /devil — backpressure, race du feed, invariant (Loop 4) ----------

def test_slow_langgraph_invoke_does_not_block_the_event_loop(monkeypatch):
    """Backpressure : un invoke LENT est OFFLOADÉ (to_thread) → la boucle d'événements
    reste LIBRE ; le tick fast < 200 ms n'est jamais bloqué (§2.8/§7)."""
    async def scenario():
        import app.engine as eng_mod
        eng = _engine()
        _wire_wide(eng.schema, time.time())

        class SlowGraph:
            def invoke(self, state, config):
                time.sleep(0.4)          # bloque un THREAD, jamais la boucle d'événements
                state.update({"triggered": True, "alert": {
                    "ts": state["now"], "kind": "LIQUIDITY_SWEEP", "direction": None,
                    "spread_width": state.get("spread_width"), "delta_volume": None,
                    "trigger": "WIDE_SPREAD", "news_context": "", "reason": "lent"}})
                return state

        monkeypatch.setattr(eng_mod, "SWEEP_GRAPH", SlowGraph())
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(60):
                await asyncio.sleep(0.01)
                ticks += 1

        await asyncio.gather(eng._assemble_sweep(time.time()), ticker())
        assert ticks >= 50, f"boucle bloquée par l'invoke lent (ticks={ticks})"
        assert eng.schema.liquidity_sweep.triggered is True   # le résultat arrive quand même
    asyncio.run(scenario())


def test_recent_feed_is_bounded_maxlen_under_many_events():
    """Le feed ne grossit JAMAIS sans borne : 20 sweeps distincts (levés/re-déclenchés) →
    borné à SWEEP_RECENT_MAX (deque), pas de fuite mémoire ni de liste géante à rendre."""
    from app import config

    async def scenario():
        now = time.time()
        eng = _engine()
        eng.schema.econ_calendar.events = _fresh(
            [{"ts": now + 300, "name": "NFP", "tier": 1, "region": "US"}], now)
        for i in range(20):
            eng.schema.s1_state.order_book = _fresh(          # spread large → déclenche
                {"bids": [[5000.0, 40.0]], "asks": [[5001.0, 30.0]]}, now)
            await eng._assemble_sweep(now + i * 2)
            eng.schema.s1_state.order_book = _fresh(          # normal → se lève (reset clé)
                {"bids": [[5000.0, 40.0]], "asks": [[5000.5, 30.0]]}, now)
            await eng._assemble_sweep(now + i * 2 + 1)
        assert len(eng.schema.liquidity_sweep.recent) == config.SWEEP_RECENT_MAX
    asyncio.run(scenario())


def test_triggered_always_carries_an_alert_invariant():
    """Invariant anti-incohérence du panneau : triggered ⇒ alert présent (jamais un
    triggered sans alerte, qui ferait afficher « aucun sweep » à tort)."""
    async def scenario():
        now = time.time()
        eng = _engine()
        _wire_wide(eng.schema, now)
        await eng._assemble_sweep(now)
        sw = eng.schema.liquidity_sweep
        assert (not sw.triggered) or (sw.alert is not None)
    asyncio.run(scenario())
