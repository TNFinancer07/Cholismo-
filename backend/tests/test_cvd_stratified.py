"""Feature — CVD Granulaire stratifié par taille d'ordre (D-038).

Approche mathématique figée AVANT implémentation (Loop 1 étape 3) :
- flux Time & Sales agrégé par BUCKET temporel (`bucket_seconds`) ; chaque print classé par
  TAILLE via un seuil (`size_threshold`) : `institutional` si `size ≥ seuil`, sinon `retail` ;
- DELTA agresseur par print : BUY = +size, SELL = −size ;
- CVD = delta NET CUMULÉ chronologique PAR STRATE (retail / institutional / total) ;
- chaque point de série porte le prix REPRÉSENTATIF du bucket = dernier prix (ts max) ;
- DIVERGENCE (advisory §2.1) entre le PRIX et le CVD INSTITUTIONNEL sur la fenêtre `lookback` :
  BULLISH = prix ↓ mais CVD inst ↑ (accumulation cachée) ; BEARISH = prix ↑ mais CVD inst ↓
  (distribution) ; deadbands `min_price_move` / `min_delta_move` → jamais un faux signal ;
- FAIL-CLOSED (§3) : prix/taille non-fini, côté inconnu → ignorés (jamais un delta inventé) ;
- OBSERVATION seule (§2.1) : agrégation de prints OBSERVÉS, jamais un ordre.
"""
from app.cvd_stratified import build_cvd_stratified


def _p(ts, price, size, side):
    return {"ts": ts, "price": price, "size": size, "side": side}


# params de test explicites (indépendants de config) : seuil 10, bucket 60 s, 100 pts,
# lookback 5, deadbands prix 0.5 / delta 5.
def _build(prints, threshold=10, bucket=60, max_points=100, lookback=5, minp=0.5, mind=5):
    return build_cvd_stratified(prints, threshold, bucket, max_points, lookback, minp, mind)


def test_classifies_by_size_threshold():
    # size 5 < 10 → retail ; size 20 ≥ 10 → institutional ; même bucket
    prints = [_p(0, 5000, 5, "BUY"), _p(1, 5000, 20, "BUY")]
    pt = _build(prints)["series"][-1]
    assert pt["retail"] == 5 and pt["institutional"] == 20 and pt["total"] == 25


def test_threshold_is_inclusive_institutional():
    # size == seuil → institutional (≥)
    pt = _build([_p(0, 5000, 10, "BUY")])["series"][-1]
    assert pt["institutional"] == 10 and pt["retail"] == 0


def test_delta_sign_buy_plus_sell_minus():
    prints = [_p(0, 5000, 8, "BUY"), _p(1, 5000, 3, "SELL")]   # retail : +8 −3 = +5
    assert _build(prints)["series"][-1]["retail"] == 5


def test_cumulative_across_buckets():
    prints = [_p(0, 5000, 5, "BUY"), _p(60, 5000, 3, "SELL")]  # bucket0 +5 ; bucket1 −3
    series = _build(prints)["series"]
    assert len(series) == 2
    assert series[0]["retail"] == 5 and series[1]["retail"] == 2   # cumul : 5 puis 5−3=2


def test_buckets_by_time():
    prints = [_p(0, 5000, 1, "BUY"), _p(30, 5000, 1, "BUY"), _p(65, 5001, 1, "BUY")]
    series = _build(prints)["series"]
    assert len(series) == 2 and series[0]["ts"] == 0.0 and series[1]["ts"] == 60.0


def test_series_price_is_last_in_bucket():
    # prix représentatif = dernier par ts (pas l'ordre d'entrée)
    prints = [_p(0, 5000, 1, "BUY"), _p(10, 5002, 1, "BUY"), _p(5, 4999, 1, "BUY")]
    assert _build(prints)["series"][-1]["price"] == 5002


def test_bullish_divergence_price_down_inst_cvd_up():
    # institutionnel ACHÈTE (delta ↑) pendant que le prix BAISSE → accumulation cachée
    prints = [_p(0, 5000, 20, "BUY"), _p(60, 4999, 20, "BUY"), _p(120, 4998, 20, "BUY")]
    div = _build(prints)["divergence"]
    assert div is not None and div["kind"] == "BULLISH"
    assert div["price_change"] < 0 and div["inst_change"] > 0


def test_bearish_divergence_price_up_inst_cvd_down():
    # institutionnel VEND (delta ↓) pendant que le prix MONTE → distribution
    prints = [_p(0, 5000, 20, "SELL"), _p(60, 5001, 20, "SELL"), _p(120, 5002, 20, "SELL")]
    div = _build(prints)["divergence"]
    assert div is not None and div["kind"] == "BEARISH"
    assert div["price_change"] > 0 and div["inst_change"] < 0


def test_no_divergence_when_aligned():
    # prix ↑ ET CVD inst ↑ → aligné, aucune divergence
    prints = [_p(0, 5000, 20, "BUY"), _p(60, 5001, 20, "BUY"), _p(120, 5002, 20, "BUY")]
    assert _build(prints)["divergence"] is None


def test_no_divergence_below_deadband():
    # prix bouge mais CVD inst quasi plat (< deadband delta) → pas de signal
    prints = [_p(0, 5000, 20, "BUY"), _p(60, 4999, 20, "BUY"), _p(120, 4998, 20, "SELL")]
    # inst cumul : +20, +40, +20 → variation nette sur fenêtre = 0 < deadband → None
    assert _build(prints, mind=25)["divergence"] is None


def test_no_divergence_single_point():
    assert _build([_p(0, 5000, 20, "BUY")])["divergence"] is None


def test_empty_prints():
    out = _build([])
    assert out["series"] == [] and out["divergence"] is None


def test_fail_closed_ignores_non_finite_and_bad_side():
    prints = [_p(0, float("nan"), 20, "BUY"), _p(0, 5000, float("inf"), "SELL"),
              _p(0, 5000, 5, "HOLD"), _p(0, 5000, 8, "BUY")]
    pt = _build(prints)["series"][-1]
    assert pt["retail"] == 8 and pt["institutional"] == 0 and pt["total"] == 8


def test_caps_to_max_points_keeps_recent():
    prints = [_p(i * 60, 5000 + i, 1, "BUY") for i in range(200)]
    series = _build(prints, max_points=50)["series"]
    assert len(series) == 50 and series[-1]["price"] == 5199


def test_zero_or_negative_bucket_returns_empty():
    assert _build([_p(0, 5000, 1, "BUY")], bucket=0)["series"] == []
    assert _build([_p(0, 5000, 1, "BUY")], bucket=-1)["series"] == []


def test_size_threshold_echoed_in_output():
    assert _build([], threshold=42)["size_threshold"] == 42


# ---------- /devil (D-038) : anomalies de flux critiques ----------

import math  # noqa: E402


def test_massive_flow_bounded_and_finite():
    # 50 000 prints → série bornée à max_points, valeurs TOUTES finies, pas d'explosion
    prints = [_p(i, 5000 + (i % 20) * 0.25, (i % 30) + 1, "BUY" if i % 2 else "SELL")
              for i in range(50_000)]
    out = _build(prints, bucket=5, max_points=120)
    assert len(out["series"]) == 120
    for pt in out["series"]:
        assert all(math.isfinite(pt[k]) for k in ("retail", "institutional", "total", "price"))


def test_sizes_straddling_threshold_exact_ge():
    # 9.99 < 10 → retail ; 10.0 == seuil → institutional (≥) ; 10.01 > seuil → institutional
    prints = [_p(0, 5000, 9.99, "BUY"), _p(1, 5000, 10.0, "BUY"), _p(2, 5000, 10.01, "BUY")]
    pt = _build(prints, threshold=10)["series"][-1]
    assert pt["retail"] == 9.99 and round(pt["institutional"], 2) == 20.01


def test_flat_zero_delta_series_no_divergence_no_error():
    # longue série au delta NET NUL par bucket (buy == sell) → CVD plat, aucune divergence,
    # aucune division par zéro (pente/divergence). Le prix bouge mais l'inst reste plat.
    prints = []
    for i in range(40):
        prints += [_p(i * 5, 5000 + i, 20, "BUY"), _p(i * 5 + 1, 5000 + i, 20, "SELL")]  # +20 −20 = 0
    out = _build(prints, bucket=5)
    assert len(out["series"]) == 40
    assert all(pt["institutional"] == 0 and pt["total"] == 0 for pt in out["series"])
    assert out["divergence"] is None                    # inst plat → deadband → jamais de signal


def test_price_flat_inst_moves_no_divergence():
    # prix CONSTANT (direction 0 via deadband) même si l'inst grimpe → pas de faux signal
    prints = [_p(i * 5, 5000, 20, "BUY") for i in range(10)]   # prix figé 5000, inst ↑
    assert _build(prints)["divergence"] is None


def test_nan_inf_price_and_ts_ignored():
    prints = [_p(0, float("inf"), 20, "BUY"), _p(float("nan"), 5000, 20, "BUY"),
              _p(0, float("-inf"), 20, "SELL"), _p(0, 5000, 7, "BUY")]
    out = _build(prints)
    assert out["series"][-1]["total"] == 7             # seuls les prints entièrement finis comptent


def test_divergence_lookback_larger_than_series():
    # lookback 100 mais série de 3 points → fenêtre = toute la série, pas d'IndexError
    prints = [_p(0, 5002, 20, "BUY"), _p(60, 5001, 20, "BUY"), _p(120, 5000, 20, "BUY")]
    out = _build(prints, lookback=100)
    assert out["divergence"] is None or out["divergence"]["bars"] == 3


def test_zero_or_negative_threshold_no_crash():
    # seuil ≤ 0 → tout print (size>0) est institutionnel ; aucun crash, retail vide
    pt = _build([_p(0, 5000, 5, "BUY")], threshold=0)["series"][-1]
    assert pt["institutional"] == 5 and pt["retail"] == 0
