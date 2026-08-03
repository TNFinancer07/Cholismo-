"""Feature — Heatmap de liquidité (LOB) : colonne courante du carnet L2 (D-036, DELTA /polish).

Comportement figé :
- le backend n'émet que la COLONNE courante `{ts, bids, asks}` (les `levels` meilleurs niveaux
  FINIS par côté) ; le frontend accumule la fenêtre glissante (payload allégé ~60×) ;
- FAIL-CLOSED (§3) : carnet non FRESH / vide / non-fini → colonne `None` (jamais inventée) ;
- OBSERVATION seule (§2.1) : donnée de rendu, jamais un ordre.
"""
import math

from app import config
from app.heatmap import latest_column
from app.meta import Freshness, MetaField


def _ob(bids, asks, fresh=Freshness.FRESH):
    return MetaField(value={"bids": bids, "asks": asks}, last_update_ts=0.0,
                     source=config.MICROSTRUCTURE_SOURCE, freshness=fresh)


def test_builds_current_column_when_fresh():
    col = latest_column(_ob([[5000.0, 10.0]], [[5000.5, 8.0]]), 42.0, 10)
    assert col == {"ts": 42.0, "bids": [[5000.0, 10.0]], "asks": [[5000.5, 8.0]]}


def test_ts_is_the_tick_time_not_the_book_ts():
    col = latest_column(_ob([[5000.0, 1.0]], [[5000.5, 1.0]]), 99.0, 10)
    assert col["ts"] == 99.0                            # une colonne par tick, trame régulière


def test_stale_book_returns_none():
    assert latest_column(_ob([[5000.0, 10.0]], [[5000.5, 8.0]], fresh=Freshness.STALE), 1.0, 10) is None


def test_absent_book_returns_none():
    assert latest_column(_ob(None, None, fresh=Freshness.ABSENT), 1.0, 10) is None


def test_empty_book_returns_none():
    assert latest_column(_ob([], []), 1.0, 10) is None


def test_truncates_each_side_to_levels():
    bids = [[5000.0 - i * 0.5, 5.0] for i in range(20)]
    asks = [[5000.5 + i * 0.5, 5.0] for i in range(20)]
    col = latest_column(_ob(bids, asks), 1.0, 10)
    assert len(col["bids"]) == 10 and len(col["asks"]) == 10


# ---------- /devil (D-036) : durcissement (conservé après passage en DELTA) ----------

def test_filters_non_finite_prices_and_sizes():
    col = latest_column(_ob([[5000.0, 10.0], [float("nan"), 5.0], [4999.5, float("inf")]],
                            [[5000.5, 8.0]]), 1.0, 10)
    assert col["bids"] == [[5000.0, 10.0]] and col["asks"] == [[5000.5, 8.0]]
    assert all(math.isfinite(p) and math.isfinite(s) for p, s in col["bids"] + col["asks"])


def test_all_levels_non_finite_returns_none():
    assert latest_column(_ob([[float("nan"), 1.0]], [[5000.5, float("nan")]]), 1.0, 10) is None


def test_crossed_book_still_produces_column():
    # carnet croisé (bid ≥ ask) = donnée finie pathologique → colonne CONSERVÉE (honnête, §3)
    col = latest_column(_ob([[5001.0, 10.0]], [[5000.0, 8.0]]), 1.0, 10)
    assert col is not None and col["bids"] == [[5001.0, 10.0]]


def test_massive_influx_is_bounded_per_column():
    big_bids = [[5000.0 - i * 0.25, 1.0] for i in range(5000)]
    big_asks = [[5000.5 + i * 0.25, 1.0] for i in range(5000)]
    col = latest_column(_ob(big_bids, big_asks), 1.0, 10)
    assert len(col["bids"]) == 10 and len(col["asks"]) == 10   # tronqué à `levels`
