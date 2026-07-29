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


# --- /devil D-050 : fuseaux, cascades, payloads empoisonnés, frontières à la seconde --------

def test_devil_offset_exotique_0530_conversion_utc_a_la_seconde():
    """Événement en heure indienne (+05:30) : la fenêtre de verrou doit se placer à la SECONDE
    exacte de l'équivalent UTC — pas à l'heure murale du feed."""
    from datetime import datetime, timezone
    events = parse_ff_json(json.dumps([_ff_entry(date="2026-11-01T18:00:00+05:30")]))
    assert events is not None and len(events) == 1
    t0 = events[0].event_time.timestamp()
    assert t0 == datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc).timestamp()
    p = _provider(events=events, fetched_ts=t0 - 3600)
    assert p.get_state(t0 - 120.0) == NewsState.HARD_LOCK   # T−2:00 pile, en UTC
    assert p.get_state(t0 - 121.0) == NewsState.WARNING     # une seconde avant


def test_devil_bascule_dst_les_deux_offsets_convertis_exactement():
    """DST américain : le MÊME 08:30 mural est -04:00 en été et -05:00 en hiver — deux instants
    UTC différents d'une heure. Chaque offset doit tomber sur SON instant, jamais l'autre."""
    from datetime import datetime, timezone
    summer = parse_ff_json(json.dumps([_ff_entry(date="2026-10-30T08:30:00-04:00")]))
    winter = parse_ff_json(json.dumps([_ff_entry(date="2026-11-06T08:30:00-05:00")]))
    assert summer[0].event_time.timestamp() == datetime(2026, 10, 30, 12, 30,
                                                        tzinfo=timezone.utc).timestamp()
    assert winter[0].event_time.timestamp() == datetime(2026, 11, 6, 13, 30,
                                                        tzinfo=timezone.utc).timestamp()
    assert (winter[0].event_time.timestamp() - summer[0].event_time.timestamp()
            ) == 7 * 86400 + 3600                           # le décalage DST est bien LÀ


def test_devil_suffixe_z_utc_accepte():
    events = parse_ff_json(json.dumps([_ff_entry(date="2026-07-29T12:30:00Z")]))
    assert events is not None and len(events) == 1


def test_devil_cascade_5_evenements_verrou_continu_sans_trou_d_air():
    """5 événements High espacés de 2 min : les fenêtres [Ti−2, Ti+2] se touchent bord à bord
    (bornes incluses) → HARD_LOCK CONTINU de T0−2:00 à T4+2:00, balayé à la seconde."""
    events = [_event(T0 + k * 120.0) for k in range(5)]     # T0, +2m, +4m, +6m, +8m
    p = _provider(events=events)
    for s in range(-120, 601):                              # union des fenêtres : [T0−2:00, T4+2:00]
        assert p.get_state(T0 + s) == NewsState.HARD_LOCK, f"trou d'air à T0+{s}s"
    assert p.get_state(T0 - 121) == NewsState.WARNING       # juste avant l'entrée de cascade
    assert p.get_state(T0 + 601) == NewsState.NORMAL        # juste après la sortie (T4+2:01)


def test_devil_html_derriere_un_200_cache_preserve():
    """Cloudflare/404 déguisé : HTTP 200 avec du HTML au lieu du JSON — rejeté, cache intact."""
    now = time.time()
    pages = ["<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title>"
             "</head><body>Checking your browser…</body></html>",
             "<html><body><h1>404 Not Found</h1></body></html>",
             "Bad Gateway"]
    calls = {"n": 0}

    def degrading():
        calls["n"] += 1
        return (json.dumps([_ff_entry(date=_iso(now + MIN))]) if calls["n"] == 1
                else pages[(calls["n"] - 2) % len(pages)])
    p = MacroNewsProvider(url="http://test.invalid/feed", fetcher=degrading)
    asyncio.run(p.refresh())
    for _ in range(4):
        asyncio.run(p.refresh())                            # 4 pages HTML → toutes rejetées
    assert p.get_state(now + 1) == NewsState.HARD_LOCK      # le cache initial tient toujours


def test_devil_tableau_50000_elements_empoisonne_rejete_et_borne_cpu():
    """Un tableau de 50 000 entrées n'est pas un calendrier, c'est une attaque : le TRONQUER
    serait pire que le rejeter (si l'événement imminent est le n° 50 001, la porte s'ouvre à
    tort). Flux obèse → rejeté ENTIER, cache préservé, en temps borné."""
    now = time.time()
    calls = {"n": 0}
    flood = json.dumps([_ff_entry(title=f"E{k}") for k in range(50_000)])

    def degrading():
        calls["n"] += 1
        return json.dumps([_ff_entry(date=_iso(now + MIN))]) if calls["n"] == 1 else flood
    p = MacroNewsProvider(url="http://test.invalid/feed", fetcher=degrading)
    asyncio.run(p.refresh())
    t0 = time.perf_counter()
    asyncio.run(p.refresh())                                # flood → rejeté
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5                                    # borné (pas 50 000 parses d'entrée)
    assert p.get_state(now + 1) == NewsState.HARD_LOCK      # l'ancien cache tient
    # et get_state reste O(petit) : jamais 50 000 événements en cache
    assert len(p._cache[0]) < 100


def test_devil_frontiere_de_deverrouillage_a_la_milliseconde():
    p = _provider(events=[_event()])
    assert p.get_state(T0 + 120.0) == NewsState.HARD_LOCK   # T+2:00.000 : verrou (borne incluse)
    assert p.get_state(T0 + 120.001) == NewsState.NORMAL    # T+2:00.001 : libre
    assert p.get_state(T0 - 120.0) == NewsState.HARD_LOCK   # symétrique à l'entrée
    assert p.get_state(T0 - 120.001) == NewsState.WARNING


# --- /polish : visibilité opérateur (Zone 0 via extras) --------------------------------------

def test_polish_extras_porte_l_etat_news_pour_la_zone_0():
    """L'opérateur voit F0 : `extras.news_state` suit le provider — jamais un verrou invisible."""
    from app.datasource.mock import MockDataSource
    from app.engine import Engine
    from app.redis_state import RedisState

    async def scenario(news_provider):
        eng = Engine(MockDataSource(), RedisState(), news_provider=news_provider)
        await eng._assemble_fast(time.time())
        return eng._extras.get("news_state")

    now = time.time()
    assert asyncio.run(scenario(None)) is None              # couche non câblée → pas de porte
    locked = _provider(events=[_event(now + MIN)], fetched_ts=now - 60)
    assert asyncio.run(scenario(locked)) == "HARD_LOCK"
    blind = MacroNewsProvider(url="http://test.invalid/feed")   # jamais fetché
    assert asyncio.run(scenario(blind)) == "SAFETY_UNKNOWN"
