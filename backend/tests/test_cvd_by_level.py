"""Feature — CVD par niveau + réinitialisation événementielle (`s1_state.cvd_by_level`, D-029).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- accumulation du DELTA agresseur (buy − sell) PAR NIVEAU de prix, alimentée à chaque tick
  par les prints NEUFS du tape (seq > dernier seq traité) — pas de double comptage ;
- exécution SUR LE HOT PATH : déterministe, cheap, budget < 200 ms/tick (§7) ;
- RÉINITIALISATION événementielle liée à `econ_calendar` : quand un événement Tier-1 franchit
  `now` (heure programmée passée), l'accumulateur repart à zéro (profil de delta frais par
  régime de news) ; reset une seule fois par événement ;
- fail-closed : tape ABSENT → accumulation GELÉE + `stale=True`, jamais un niveau inventé (§3) ;
- ordre OBSERVÉ, jamais un ordre de l'opérateur (§2.1).
"""
import time

from app.engine import CVD_MAX_LEVELS, Engine
from app.meta import Freshness, MetaField
from app.redis_state import RedisState


def _fresh(value, now):
    return MetaField(value=value, last_update_ts=now, source="test", freshness=Freshness.FRESH)


def _engine():
    return Engine(MetaDataStub(), RedisState())


class MetaDataStub:
    """DataSource factice — le CVD ne tick pas la source, il lit le tape déjà validé."""


def test_cvd_accumulates_delta_by_price_level():
    now = time.time()
    eng = _engine()
    prints = [
        {"ts": now, "price": 5000.00, "size": 10, "side": "BUY", "seq": 1},
        {"ts": now, "price": 5000.00, "size": 4, "side": "SELL", "seq": 2},
        {"ts": now, "price": 5000.25, "size": 3, "side": "SELL", "seq": 3},
    ]
    cvd = eng._build_cvd(_fresh(prints, now), now)
    by_price = {level.price: level for level in cvd.levels}
    assert by_price[5000.00].buy == 10 and by_price[5000.00].sell == 4
    assert by_price[5000.00].delta == 6.0        # net acheteur
    assert by_price[5000.25].delta == -3.0       # net vendeur
    assert cvd.total_delta == 3.0                # +6 − 3
    assert cvd.levels == sorted(cvd.levels, key=lambda le: le.price)  # trié par prix
    assert len(cvd.levels) <= CVD_MAX_LEVELS


def test_cvd_does_not_double_count_the_same_prints():
    now = time.time()
    eng = _engine()
    tape = _fresh([{"ts": now, "price": 5000.0, "size": 8, "side": "BUY", "seq": 1}], now)
    eng._build_cvd(tape, now)
    cvd = eng._build_cvd(tape, now)              # même fenêtre, seq déjà traité
    assert cvd.total_delta == 8.0                # pas 16 : aucun re-comptage


def test_cvd_resets_when_tier1_event_crosses_now():
    now = time.time()
    eng = _engine()
    eng._build_cvd(_fresh(
        [{"ts": now, "price": 5000.0, "size": 10, "side": "BUY", "seq": 1}], now), now)
    # NFP Tier-1 programmé à now+10 ; on rejoue APRÈS son heure → reset événementiel.
    eng.schema.econ_calendar.events = _fresh(
        [{"ts": now + 10, "name": "NFP — emplois US", "tier": 1, "region": "US"}], now)
    cvd = eng._build_cvd(_fresh(
        [{"ts": now + 20, "price": 5001.0, "size": 5, "side": "BUY", "seq": 2}], now + 20), now + 20)
    assert cvd.reset_reason == "NFP — emplois US"
    assert cvd.last_reset_ts is not None
    by_price = {level.price: level for level in cvd.levels}
    assert 5000.0 not in by_price                # niveau pré-reset effacé
    assert by_price[5001.0].delta == 5.0         # seul le post-reset compte
    assert cvd.total_delta == 5.0


def test_cvd_resets_only_once_per_event():
    now = time.time()
    eng = _engine()
    eng.schema.econ_calendar.events = _fresh(
        [{"ts": now, "name": "FOMC", "tier": 1, "region": "US"}], now)
    eng._build_cvd(_fresh(
        [{"ts": now + 1, "price": 5000.0, "size": 4, "side": "BUY", "seq": 1}], now + 1), now + 1)
    # même événement, tick suivant → PAS de nouveau reset : l'accumulation continue
    cvd = eng._build_cvd(_fresh(
        [{"ts": now + 2, "price": 5000.0, "size": 3, "side": "BUY", "seq": 2}], now + 2), now + 2)
    assert cvd.total_delta == 7.0                # 4 + 3, pas re-remis à zéro


def test_cvd_freezes_and_flags_stale_when_tape_absent():
    now = time.time()
    eng = _engine()
    eng._build_cvd(_fresh([{"ts": now, "price": 5000.0, "size": 9, "side": "BUY", "seq": 1}], now), now)
    absent = MetaField(value=None, last_update_ts=None, source="test", freshness=Freshness.ABSENT)
    cvd = eng._build_cvd(absent, now + 1)
    assert cvd.stale is True                     # accumulation gelée, honnête
    assert cvd.total_delta == 9.0                # dernier profil connu conservé, rien d'inventé


def test_cvd_accumulation_stays_within_hot_path_budget():
    """Garde-fou de perf (§7) : l'accumulation par tick doit rester très en-dessous de 200 ms."""
    now = time.time()
    eng = _engine()
    start = time.perf_counter()
    for i in range(300):
        prints = [{"ts": now + i, "price": 5000.0 + (i % 60) * 0.25,
                   "size": 2, "side": "BUY" if i % 2 else "SELL", "seq": i + 1}]
        eng._build_cvd(_fresh(prints, now + i), now + i)
    per_tick_ms = (time.perf_counter() - start) / 300 * 1000
    assert per_tick_ms < 200, f"CVD {per_tick_ms:.2f} ms/tick > budget hot path 200 ms"
    assert per_tick_ms < 10, f"CVD trop lent pour le hot path : {per_tick_ms:.2f} ms/tick"


# ---------- /devil — régression seq, prix aberrant, course reset, saturation (Loop 4) ----------

from app.engine import CVD_MAX_TRACKED  # noqa: E402


def test_seq_regression_does_not_freeze_accumulation_forever():
    """seq qui RECULE (redémarrage de source, seq repart bas) ne doit PAS geler le CVD :
    re-baseline + reprise. Sinon tout print futur < last_seq est ignoré → gel SILENCIEUX
    (tape FRESH mais accumulation morte — le pire, pas signalé)."""
    now = time.time()
    eng = _engine()
    eng._build_cvd(_fresh([{"ts": now, "price": 5000.0, "size": 5, "side": "BUY", "seq": 900}], now), now)
    cvd = eng._build_cvd(  # la source redémarre : seq repart à 1 (< 900)
        _fresh([{"ts": now + 1, "price": 5001.0, "size": 7, "side": "BUY", "seq": 1}], now + 1), now + 1)
    by_price = {le.price: le for le in cvd.levels}
    assert 5001.0 in by_price and by_price[5001.0].delta == 7.0, "gel silencieux sur régression de seq"


def test_out_of_order_straggler_is_skipped_not_a_full_rebaseline():
    """Un seul traînard (seq < last mais max de fenêtre >= last) est ignoré (déjà passé),
    PAS une régression → pas de re-baseline destructeur."""
    now = time.time()
    eng = _engine()
    eng._build_cvd(_fresh([
        {"ts": now, "price": 5000.0, "size": 5, "side": "BUY", "seq": 10},
        {"ts": now, "price": 5000.0, "size": 5, "side": "BUY", "seq": 11},
    ], now), now)
    cvd = eng._build_cvd(_fresh([
        {"ts": now + 1, "price": 5000.0, "size": 3, "side": "BUY", "seq": 12},   # neuf
        {"ts": now + 1, "price": 5000.0, "size": 99, "side": "SELL", "seq": 9},  # traînard → ignoré
    ], now + 1), now + 1)
    assert cvd.total_delta == 13.0               # 5+5+3, le SELL 99 (seq 9) ignoré


def test_aberrant_price_print_does_not_dominate_or_crash():
    """Print à un prix aberrant (+50 ticks) : tracké mais faible volume → HORS du top affiché ;
    total_delta le reflète (réel) ; aucun crash."""
    now = time.time()
    eng = _engine()
    # 30 niveaux actifs près du marché (vol 20) + 1 print aberrant loin (vol 1)
    prints = [{"ts": now, "price": 5000.0 + k * 0.25, "size": 20, "side": "BUY", "seq": k + 1}
              for k in range(30)]
    prints.append({"ts": now, "price": 5000.0 + 50 * 0.25, "size": 1, "side": "SELL", "seq": 31})
    cvd = eng._build_cvd(_fresh(prints, now), now)
    shown = {le.price for le in cvd.levels}
    assert (5000.0 + 50 * 0.25) not in shown, "le print aberrant (faible volume) ne doit pas s'afficher"
    assert len(cvd.levels) == CVD_MAX_LEVELS


def test_reset_and_incoming_prints_same_tick_count_post_reset():
    """Reset événementiel ET prints entrants dans le MÊME _build_cvd (course) : les prints
    neufs comptent dans l'accumulateur FRAIS (post-reset), pas perdus."""
    now = time.time()
    eng = _engine()
    eng._build_cvd(_fresh([{"ts": now, "price": 5000.0, "size": 8, "side": "BUY", "seq": 1}], now), now)
    eng.schema.econ_calendar.events = _fresh([{"ts": now + 5, "name": "NFP", "tier": 1, "region": "US"}], now)
    cvd = eng._build_cvd(_fresh([{"ts": now + 10, "price": 5002.0, "size": 6, "side": "SELL", "seq": 2}], now + 10), now + 10)
    assert cvd.reset_reason == "NFP"
    by_price = {le.price: le for le in cvd.levels}
    assert 5000.0 not in by_price                # pré-reset effacé
    assert by_price[5002.0].delta == -6.0        # le print neuf compté POST-reset
    assert cvd.total_delta == -6.0


def test_saturated_tape_caps_tracked_prices_and_flags_capped():
    """Flux saturé : 600 prix DISTINCTS → l'accumulateur reste BORNÉ (CVD_MAX_TRACKED), garde
    les plus actifs (éviction du moins actif), et signale `capped` honnêtement."""
    now = time.time()
    eng = _engine()
    prints = [{"ts": now, "price": 5000.0 + k * 0.25, "size": 1 + (k % 7),
               "side": "BUY" if k % 2 else "SELL", "seq": k + 1} for k in range(600)]
    cvd = eng._build_cvd(_fresh(prints, now), now)
    assert len(eng._cvd_levels) <= CVD_MAX_TRACKED, "accumulateur NON borné (fuite)"
    assert cvd.capped is True                    # saturation signalée
