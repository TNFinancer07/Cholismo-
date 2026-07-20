"""CVD granulaire stratifié par taille d'ordre (D-038).

Agrège le flux Time & Sales (prints OBSERVÉS, §2.1) en un **Cumulative Volume Delta segmenté
par STRATE DE TAILLE** : chaque print est classé `institutional` (`size ≥ size_threshold`) ou
`retail` (sinon) ; le delta agresseur (BUY = +size, SELL = −size) est cumulé chronologiquement
par strate, échantillonné par BUCKET temporel. Détecte les DIVERGENCES majeures entre le prix et
le CVD institutionnel (advisory : annote, ne bloque ni ne trade jamais, §2.1).

Pur et déterministe (aucun LLM, aucun état caché) : `build_cvd_stratified(prints, …)` ne dépend
que de ses entrées. FAIL-CLOSED (§3) : prix/taille non-fini, côté inconnu → ignorés (jamais un
delta inventé). Le seuil retail/institutionnel est **v1 provisional** (pas d'AUTORITÉ dans
/reference — calibration owner: Sony)."""
from __future__ import annotations

import math


def _bucket(ts: float, bucket_seconds: float) -> float:
    return math.floor(ts / bucket_seconds) * bucket_seconds


def build_cvd_stratified(prints: list[dict], size_threshold: float, bucket_seconds: float,
                         max_points: int, divergence_lookback: int,
                         min_price_move: float, min_delta_move: float) -> dict:
    """Construit le CVD stratifié depuis les prints. Retourne `{size_threshold, series,
    divergence}` où `series` est la liste chronologique (croissante) des `max_points` derniers
    points `{ts, price, retail, institutional, total}` (CVD cumulé par strate, `price` = dernier
    prix du bucket), et `divergence ∈ {kind ∈ BULLISH|BEARISH, price_change, inst_change, bars}
    | None`."""
    out: dict = {"size_threshold": size_threshold, "series": [], "divergence": None}
    if bucket_seconds <= 0:
        return out

    # 1) agrège par bucket : delta par strate + dernier prix (ts max) du bucket.
    buckets: dict[float, dict] = {}
    for p in prints:
        price, size, side = p.get("price"), p.get("size"), p.get("side")
        ts = p.get("ts")
        if not (isinstance(price, (int, float)) and math.isfinite(price)
                and isinstance(size, (int, float)) and math.isfinite(size) and size > 0
                and isinstance(ts, (int, float)) and math.isfinite(ts)
                and side in ("BUY", "SELL")):
            continue                                   # fail-closed : print invalide ignoré (§3)
        start = _bucket(float(ts), bucket_seconds)
        b = buckets.get(start)
        if b is None:
            b = buckets[start] = {"ts": start, "retail": 0.0, "institutional": 0.0,
                                  "last_ts": ts, "price": float(price)}
        signed = float(size) if side == "BUY" else -float(size)
        b["institutional" if float(size) >= size_threshold else "retail"] += signed
        if ts >= b["last_ts"]:                         # prix représentatif = dernier par ts
            b["last_ts"], b["price"] = ts, float(price)

    # 2) cumule chronologiquement par strate → série de CVD.
    series: list[dict] = []
    cum_r = cum_i = 0.0
    for start in sorted(buckets):
        b = buckets[start]
        cum_r += b["retail"]
        cum_i += b["institutional"]
        series.append({"ts": b["ts"], "price": b["price"], "retail": cum_r,
                       "institutional": cum_i, "total": cum_r + cum_i})
    if max_points > 0:
        series = series[-max_points:]
    out["series"] = series

    # 3) divergence prix ↔ CVD institutionnel sur la fenêtre lookback (advisory §2.1).
    out["divergence"] = _divergence(series, divergence_lookback, min_price_move, min_delta_move)
    return out


def _divergence(series: list[dict], lookback: int, min_price_move: float,
                min_delta_move: float) -> dict | None:
    if len(series) < 2:
        return None                                    # pas assez de points → jamais de faux signal
    window = series[-lookback:] if lookback > 0 else series
    if len(window) < 2:
        return None
    start, last = window[0], window[-1]
    price_change = last["price"] - start["price"]
    inst_change = last["institutional"] - start["institutional"]
    # deadband → une variation sous le seuil est traitée comme PLATE (direction 0), pas un signal.
    price_dir = 1 if price_change >= min_price_move else -1 if price_change <= -min_price_move else 0
    inst_dir = 1 if inst_change >= min_delta_move else -1 if inst_change <= -min_delta_move else 0
    if price_dir != 0 and inst_dir != 0 and price_dir != inst_dir:
        # prix ↓ + inst ↑ = accumulation cachée (BULLISH) ; prix ↑ + inst ↓ = distribution (BEARISH)
        return {"kind": "BULLISH" if price_dir < 0 else "BEARISH",
                "price_change": price_change, "inst_change": inst_change, "bars": len(window)}
    return None
