"""Feature — Footprint + détection d'imbalances (D-037).

Approche mathématique figée AVANT implémentation (Loop 1 étape 3) :
- flux Time & Sales agrégé par BOUGIE (bucket temporel `candle_seconds`) puis par NIVEAU de prix
  quantifié sur la grille de tick (`k = round(prix/tick)`) : BUY = agresseur à l'ASK
  (`ask_vol`), SELL = agresseur au BID (`bid_vol`) ;
- IMBALANCE DIAGONALE (ratio R, plancher M) : niveau `k` = **ASK imbalance** si
  `ask_vol[k] ≥ R·bid_vol[k−1]` ET `ask_vol[k] ≥ M` ; **BID imbalance** si
  `bid_vol[k] ≥ R·ask_vol[k+1]` ET `bid_vol[k] ≥ M` ;
- POC = niveau au volume total (bid+ask) maximal ;
- FAIL-CLOSED (§3) : prix/taille non-fini, côté inconnu → ignorés (jamais un volume inventé) ;
- OBSERVATION seule (§2.1) : agrégation de prints OBSERVÉS, jamais un ordre.
"""
from app.footprint import build_footprint


def _p(ts, price, size, side):
    return {"ts": ts, "price": price, "size": size, "side": side}


def _levels(candle):
    return {lvl["price"]: lvl for lvl in candle["levels"]}


def test_aggregates_bid_ask_per_level():
    prints = [_p(0, 5000.0, 10, "BUY"), _p(1, 5000.0, 4, "SELL"), _p(2, 5000.25, 6, "BUY")]
    lv = _levels(build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0])
    assert lv[5000.0]["ask_vol"] == 10 and lv[5000.0]["bid_vol"] == 4
    assert lv[5000.25]["ask_vol"] == 6 and lv[5000.25]["bid_vol"] == 0


def test_poc_is_max_total_volume_level():
    prints = [_p(0, 5000.0, 10, "BUY"), _p(0, 5000.25, 3, "BUY"), _p(0, 5000.0, 5, "SELL")]
    assert build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0]["poc"] == 5000.0   # 15 vs 3


def test_ask_imbalance_diagonal():
    # ask_vol[5000.25]=30 vs bid_vol[5000.0]=5 → 30 ≥ 3·5 → ASK imbalance à 5000.25
    prints = [_p(0, 5000.25, 30, "BUY"), _p(0, 5000.0, 5, "SELL")]
    lv = _levels(build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0])
    assert lv[5000.25]["imbalance"] == "ASK"
    assert lv[5000.0]["imbalance"] is None                     # bid 5 vs ask 30 au-dessus → non


def test_no_imbalance_when_below_ratio():
    prints = [_p(0, 5000.25, 10, "BUY"), _p(0, 5000.0, 5, "SELL")]   # 10 ≥ 3·5=15 ? non
    assert _levels(build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0])[5000.25]["imbalance"] is None


def test_bid_imbalance_diagonal():
    # bid_vol[5000.0]=30 vs ask_vol[5000.25]=5 → 30 ≥ 15 → BID imbalance à 5000.0
    prints = [_p(0, 5000.0, 30, "SELL"), _p(0, 5000.25, 5, "BUY")]
    assert _levels(build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0])[5000.0]["imbalance"] == "BID"


def test_imbalance_vs_empty_diagonal_gated_by_min_vol():
    prints = [_p(0, 5000.25, 10, "BUY")]                         # diagonale bid[5000.0] = 0
    assert _levels(build_footprint(prints, 60, 0.25, 3.0, 5, 12)[0])[5000.25]["imbalance"] == "ASK"
    assert _levels(build_footprint(prints, 60, 0.25, 3.0, 20, 12)[0])[5000.25]["imbalance"] is None


def test_buckets_prints_into_candles_by_time():
    prints = [_p(0, 5000.0, 1, "BUY"), _p(30, 5000.0, 1, "BUY"), _p(65, 5001.0, 1, "BUY")]
    candles = build_footprint(prints, 60, 0.25, 3.0, 1, 12)
    assert len(candles) == 2
    assert candles[0]["start_ts"] == 0.0 and candles[1]["start_ts"] == 60.0


def test_ohlc_from_prints_in_candle():
    prints = [_p(0, 5000.0, 1, "BUY"), _p(1, 5002.0, 1, "BUY"),
              _p(2, 4999.0, 1, "SELL"), _p(3, 5001.0, 1, "BUY")]
    c = build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0]
    assert c["open"] == 5000.0 and c["high"] == 5002.0 and c["low"] == 4999.0 and c["close"] == 5001.0


def test_price_quantized_to_tick_grid():
    prints = [_p(0, 5000.10, 10, "BUY"), _p(0, 5000.12, 5, "BUY")]   # tous deux → 5000.0 (tick le plus proche)
    lv = _levels(build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0])
    assert set(lv) == {5000.0} and lv[5000.0]["ask_vol"] == 15


def test_caps_to_max_candles_keeps_recent():
    prints = [_p(i * 60, 5000.0, 1, "BUY") for i in range(20)]
    candles = build_footprint(prints, 60, 0.25, 3.0, 1, 5)
    assert len(candles) == 5 and candles[0]["start_ts"] == 15 * 60.0


def test_empty_prints_no_candles():
    assert build_footprint([], 60, 0.25, 3.0, 1, 12) == []


def test_fail_closed_ignores_non_finite_and_bad_side():
    prints = [_p(0, float("nan"), 10, "BUY"), _p(0, 5000.0, float("inf"), "SELL"),
              _p(0, 5000.0, 5, "HOLD"), _p(0, 5000.0, 8, "BUY")]
    lv = _levels(build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0])
    assert lv[5000.0]["ask_vol"] == 8 and lv[5000.0]["bid_vol"] == 0   # seuls les prints valides comptent


def test_levels_sorted_price_desc_and_total_volume():
    prints = [_p(0, 5000.0, 4, "BUY"), _p(0, 5000.5, 2, "BUY"), _p(0, 5000.25, 6, "SELL")]
    c = build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0]
    prices = [lvl["price"] for lvl in c["levels"]]
    assert prices == sorted(prices, reverse=True)                 # haut → bas
    assert c["total_volume"] == 12


# ---------- /devil (D-037) : anomalies de flux critiques ----------

def test_same_ts_burst_ohlc_open_first_close_last():
    # rafale à timestamps IDENTIQUES : open = 1er print (ordre d'entrée), close = dernier
    prints = [_p(0, 5000.0, 1, "BUY"), _p(0, 5001.0, 1, "BUY"), _p(0, 4999.0, 1, "SELL")]
    c = build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0]
    assert c["open"] == 5000.0 and c["close"] == 4999.0
    assert c["high"] == 5001.0 and c["low"] == 4999.0


def test_single_level_candle_ohlc_equal_no_crash():
    prints = [_p(0, 5000.0, 10, "BUY"), _p(1, 5000.0, 4, "SELL")]   # un seul prix transigé
    c = build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0]
    assert c["open"] == c["high"] == c["low"] == c["close"] == 5000.0
    assert c["poc"] == 5000.0 and len(c["levels"]) == 1


def test_aberrant_far_price_snaps_to_grid_no_crash():
    prints = [_p(0, 5000.0, 5, "BUY"), _p(0, 999999.37, 5, "BUY")]  # prix aberrant hors-grille
    c = build_footprint(prints, 60, 0.25, 3.0, 1, 12)[0]
    prices = {lvl["price"] for lvl in c["levels"]}
    assert 5000.0 in prices and any(abs(pr - 999999.37) <= 0.25 for pr in prices)   # snappé


def test_zero_diagonal_no_division_error():
    # niveau adjacent à volume NUL → formule multiplicative (pas de /0) → imbalance vs vide
    c = build_footprint([_p(0, 5000.0, 10, "BUY")], 60, 0.25, 3.0, 1, 12)[0]
    assert _levels(c)[5000.0]["imbalance"] == "ASK"


def test_zero_or_negative_tick_returns_empty():
    assert build_footprint([_p(0, 5000, 1, "BUY")], 60, 0.0, 3.0, 1, 12) == []
    assert build_footprint([_p(0, 5000, 1, "BUY")], 0.0, 0.25, 3.0, 1, 12) == []
