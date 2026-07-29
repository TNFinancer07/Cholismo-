"""Feature — MacroNewsProvider & Porte F0 (hard lock macro) — D-050.

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- `MacroEvent` (title, currency, impact, event_time UTC) + `NewsState` :
  NORMAL / WARNING / HARD_LOCK / SAFETY_UNKNOWN ;
- fenêtres (config env, minutes) : WARNING = [T−15, T−2), HARD_LOCK = [T−2, T+2] — bornes du
  lock INCLUSES (le doute penche toujours vers le verrou), au-delà de T+2 → NORMAL ;
  plusieurs événements → l'état le plus SÉVÈRE gagne ;
- parser Forex-Factory JSON pur et défensif : ne garde que USD × HIGH, entrée corrompue ignorée
  ligne à ligne, flux illisible → None (jamais un crash) ;
- worker async (refresh 3600 s, fetch injectable, I/O en thread) → cache `(events, fetched_ts)` ;
  `get_state(now)` SYNC et PUR — zéro I/O sur le chemin d'évaluation ; cache jamais initialisé
  OU fossile → SAFETY_UNKNOWN ; fetch raté → l'ancien cache reste (et vieillit) ;
- Porte F0 TOUT AU DÉBUT d'`evaluate_lsr` : HARD_LOCK → None immédiat sans évaluer la
  microstructure ; SAFETY_UNKNOWN → None aussi (couche câblée mais AVEUGLE = on ne trade pas) ;
  `news_state=None` (couche non câblée, stack démo) → la porte n'existe pas — amendement
  D-046 documenté : l'état news est un CHAMP D'ENTRÉE, la fonction reste pure.
"""
import asyncio
import json
import time

from app import config
from app.macro_news import MacroEvent, MacroNewsProvider, NewsState, parse_ff_json

T0 = 1_753_500_000.0                                        # instant de l'événement (epoch)
MIN = 60.0


def _ff_entry(**over):
    base = {"title": "Non-Farm Payrolls", "country": "USD", "impact": "High",
            "date": "2026-07-29T08:30:00-04:00"}
    base.update(over)
    return base


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _provider(events=None, fetched_ts=None, **over) -> MacroNewsProvider:
    p = MacroNewsProvider(url="http://test.invalid/feed", **over)
    if events is not None:
        # cache timbré AVANT le plus ancien instant d'évaluation des tests (T0−1 h) — un cache
        # daté APRÈS `now` serait « du futur » → SAFETY_UNKNOWN (garde légitime, pas le sujet ici)
        p._cache = (events, fetched_ts if fetched_ts is not None else T0 - 3600.0)
    return p


def _event(ts=T0) -> MacroEvent:
    from datetime import datetime, timezone
    return MacroEvent(title="NFP", currency="USD", impact="HIGH",
                      event_time=datetime.fromtimestamp(ts, tz=timezone.utc))


# --- Parser : USD × HIGH, défensif ligne à ligne --------------------------------------------

def test_parser_ne_garde_que_usd_high():
    feed = json.dumps([
        _ff_entry(),
        _ff_entry(title="CPI zone euro", country="EUR"),
        _ff_entry(title="Retail Sales", impact="Medium"),
        _ff_entry(title="FOMC", impact="high"),             # casse tolérée
        _ff_entry(title="GDP", country="usd", impact="HIGH"),
    ])
    events = parse_ff_json(feed)
    assert events is not None
    assert [e.title for e in events] == ["Non-Farm Payrolls", "FOMC", "GDP"]
    assert all(e.currency == "USD" and e.impact == "HIGH" for e in events)


def test_parser_date_iso_avec_offset_convertie_utc():
    from datetime import datetime, timezone
    events = parse_ff_json(json.dumps([_ff_entry(date="2026-07-29T08:30:00-04:00")]))
    assert events is not None and len(events) == 1
    expected = datetime(2026, 7, 29, 12, 30, tzinfo=timezone.utc).timestamp()   # 08:30 ET = 12:30 UTC
    assert events[0].event_time.timestamp() == expected


def test_parser_entrees_corrompues_ignorees_sans_crash():
    feed = json.dumps([
        "pas un dict", 42, None,
        _ff_entry(date="hier soir tard"),                   # date illisible
        {"title": "SansDate", "country": "USD", "impact": "High"},
        _ff_entry(title=None),
        _ff_entry(),                                        # la seule VALIDE
    ])
    events = parse_ff_json(feed)
    assert events is not None and len(events) == 1


def test_parser_flux_illisible_none_fail_closed():
    for garbage in ("", "{pas du json", "42", '{"pas": "une liste"}'):
        assert parse_ff_json(garbage) is None, repr(garbage)
    assert parse_ff_json(json.dumps([])) == []              # liste VIDE valide ≠ flux illisible


# --- get_state : les fenêtres exactes de la spec --------------------------------------------

def test_fenetres_exactes_de_la_spec():
    p = _provider(events=[_event()])
    assert p.get_state(T0 - 3 * MIN) == NewsState.WARNING    # T−3m
    assert p.get_state(T0 - 1 * MIN) == NewsState.HARD_LOCK  # T−1m
    assert p.get_state(T0 + 1 * MIN) == NewsState.HARD_LOCK  # T+1m
    assert p.get_state(T0 + 3 * MIN) == NewsState.NORMAL     # T+3m


def test_bornes_des_fenetres_le_doute_penche_vers_le_verrou():
    p = _provider(events=[_event()])
    assert p.get_state(T0 - 15 * MIN) == NewsState.WARNING   # entrée de fenêtre warning
    assert p.get_state(T0 - 15 * MIN - 1) == NewsState.NORMAL
    assert p.get_state(T0 - 2 * MIN) == NewsState.HARD_LOCK  # borne INCLUSE
    assert p.get_state(T0 + 2 * MIN) == NewsState.HARD_LOCK  # borne INCLUSE
    assert p.get_state(T0 + 2 * MIN + 1) == NewsState.NORMAL
    assert p.get_state(T0) == NewsState.HARD_LOCK            # l'instant T lui-même


def test_plusieurs_evenements_le_plus_severe_gagne():
    p = _provider(events=[_event(T0), _event(T0 + 10 * MIN)])
    # T0+9m : NORMAL vis-à-vis du 1er (T+9), HARD_LOCK vis-à-vis du 2e (T−1) → HARD_LOCK
    assert p.get_state(T0 + 9 * MIN) == NewsState.HARD_LOCK
    # T0−5m : WARNING vis-à-vis du 1er, NORMAL vis-à-vis du 2e (T−15m pile → WARNING) → WARNING
    assert p.get_state(T0 - 5 * MIN) == NewsState.WARNING


def test_calendrier_vide_fetche_avec_succes_normal():
    p = _provider(events=[])                                # semaine calme CONNUE
    assert p.get_state(T0) == NewsState.NORMAL


def test_cache_jamais_initialise_safety_unknown():
    p = _provider()                                         # aucun fetch réussi
    assert p.get_state(T0) == NewsState.SAFETY_UNKNOWN


def test_cache_fossile_safety_unknown():
    now = time.time()
    p = _provider(events=[_event(now + 600)], fetched_ts=now - config.MACRO_NEWS_MAX_AGE_S - 1)
    assert p.get_state(now) == NewsState.SAFETY_UNKNOWN     # calendrier fossile = aveugle


# --- Worker : refresh async, fetch raté = cache conservé ------------------------------------

def test_refresh_alimente_le_cache_via_fetch_injecte():
    now = time.time()
    feed = json.dumps([_ff_entry(date=_iso(now + MIN))])    # événement à T+1m du réel
    p = MacroNewsProvider(url="http://test.invalid/feed", fetcher=lambda: feed)
    asyncio.run(p.refresh())
    assert p.get_state(now + 1) == NewsState.HARD_LOCK


def test_fetch_rate_conserve_l_ancien_cache():
    calls = {"n": 0}

    now = time.time()

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps([_ff_entry(date=_iso(now + MIN))])
        raise ConnectionError("feed mort")
    p = MacroNewsProvider(url="http://test.invalid/feed", fetcher=flaky)
    asyncio.run(p.refresh())
    asyncio.run(p.refresh())                                # échec → cache intact, pas d'exception
    assert p.get_state(now + 1) == NewsState.HARD_LOCK


def test_fetch_garbage_conserve_l_ancien_cache():
    calls = {"n": 0}

    now = time.time()

    def degrading():
        calls["n"] += 1
        return json.dumps([_ff_entry(date=_iso(now + MIN))]) if calls["n"] == 1 else "{corrompu"
    p = MacroNewsProvider(url="http://test.invalid/feed", fetcher=degrading)
    asyncio.run(p.refresh())
    asyncio.run(p.refresh())
    assert p.get_state(now + 1) == NewsState.HARD_LOCK


# --- Porte F0 dans evaluate_lsr --------------------------------------------------------------

def test_f0_hard_lock_rejette_avant_toute_microstructure():
    from tests.test_lsr_engine import _inputs
    assert _inputs().news_state is None                     # défaut : couche non câblée
    from app.lsr_engine import evaluate_lsr
    assert evaluate_lsr(_inputs()) is not None              # contrôle : setup au vert
    assert evaluate_lsr(_inputs(news_state="HARD_LOCK")) is None
    # F0 est PREMIÈRE : même un setup entièrement invalide ne change rien au verdict
    assert evaluate_lsr(_inputs(news_state="HARD_LOCK", prints=[], book=None)) is None


def test_f0_safety_unknown_rejette_aussi():
    """Couche news CÂBLÉE mais aveugle (cache vide/fossile) : on ne trade pas à l'aveugle."""
    from tests.test_lsr_engine import _inputs
    from app.lsr_engine import evaluate_lsr
    assert evaluate_lsr(_inputs(news_state="SAFETY_UNKNOWN")) is None


def test_f0_warning_et_normal_laissent_passer():
    from tests.test_lsr_engine import _inputs
    from app.lsr_engine import evaluate_lsr
    assert evaluate_lsr(_inputs(news_state="WARNING")) is not None
    assert evaluate_lsr(_inputs(news_state="NORMAL")) is not None


# --- Intégration engine : le provider câblé bloque l'émission --------------------------------

def test_engine_hard_lock_aucune_emission():
    from tests.test_account_provider import MockAccountProvider, _drain_manifests, _wire_setup
    from app.datasource.mock import MockDataSource
    from app.engine import Engine
    from app.redis_state import RedisState
    from app.risk_sizer import APEX_EOD_50K, apex_eod_account

    async def scenario(news_events):
        now = time.time()
        news = _provider(events=news_events, fetched_ts=now)
        eng = Engine(MockDataSource(), RedisState(),
                     account_provider=MockAccountProvider(
                         state=apex_eod_account(APEX_EOD_50K), always_fresh=True),
                     news_provider=news)
        _wire_setup(eng, now)
        from app.sse import broadcaster
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        eng._maybe_emit_lsr(now)
        out = _drain_manifests(q)
        broadcaster.unsubscribe("fast", q)
        return out

    now = time.time()
    locked = asyncio.run(scenario([_event(now + MIN)]))      # événement à T+1m → HARD_LOCK
    assert locked == []                                      # F0 : silence
    normal = asyncio.run(scenario([_event(now + 3600)]))     # événement à T+60m → NORMAL
    assert len(normal) == 1                                  # la porte laisse passer
