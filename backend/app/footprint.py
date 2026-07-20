"""Footprint + détection d'imbalances (D-037).

Agrège le flux Time & Sales (prints OBSERVÉS, §2.1) par BOUGIE (bucket temporel) puis par
NIVEAU de prix (quantifié sur la grille de tick) : BUY = agresseur à l'ASK (`ask_vol`), SELL =
agresseur au BID (`bid_vol`). Par bougie : OHLC, POC (volume total max), et IMBALANCES
DIAGONALES (comparaison en diagonale ask[k]↔bid[k−1] / bid[k]↔ask[k+1]).

Pur et déterministe (aucun LLM, aucun état caché) : `build_footprint(prints, …)` ne dépend que
de ses entrées. FAIL-CLOSED (§3) : prix/taille non-fini, côté inconnu → ignorés (jamais un
volume inventé)."""
from __future__ import annotations

import math


def _bucket(ts: float, candle_seconds: float) -> float:
    return math.floor(ts / candle_seconds) * candle_seconds


def build_footprint(prints: list[dict], candle_seconds: float, tick: float,
                    ratio: float, min_vol: float, max_candles: int) -> list[dict]:
    """Construit les bougies footprint depuis les prints. Retourne les `max_candles` bougies les
    plus récentes, triées par `start_ts` croissant. Chaque bougie : `{start_ts, end_ts, open,
    high, low, close, poc, total_volume, levels}` où chaque niveau est `{price, bid_vol, ask_vol,
    imbalance ∈ ASK|BID|None}` (trié prix décroissant)."""
    if candle_seconds <= 0 or tick <= 0:
        return []

    # regroupe les prints par bucket ; chaque bucket agrège par index de tick k = round(prix/tick).
    buckets: dict[float, dict] = {}
    for p in prints:
        price, size, side = p.get("price"), p.get("size"), p.get("side")
        ts = p.get("ts")
        if not (isinstance(price, (int, float)) and math.isfinite(price)
                and isinstance(size, (int, float)) and math.isfinite(size) and size > 0
                and isinstance(ts, (int, float)) and math.isfinite(ts)
                and side in ("BUY", "SELL")):
            continue                                   # fail-closed : print invalide ignoré (§3)
        start = _bucket(float(ts), candle_seconds)
        b = buckets.get(start)
        if b is None:
            b = buckets[start] = {"start_ts": start, "levels": {},   # k → [bid_vol, ask_vol]
                                  "first_ts": ts, "last_ts": ts,
                                  "open": float(price), "close": float(price),
                                  "high": float(price), "low": float(price)}
        k = round(float(price) / tick)
        lvl = b["levels"].get(k)
        if lvl is None:
            lvl = b["levels"][k] = [0.0, 0.0]
        if side == "BUY":
            lvl[1] += float(size)                      # ask volume
        else:
            lvl[0] += float(size)                      # bid volume
        # OHLC par ordre chronologique des prints
        if ts <= b["first_ts"]:
            b["first_ts"], b["open"] = ts, float(price)
        if ts >= b["last_ts"]:
            b["last_ts"], b["close"] = ts, float(price)
        b["high"] = max(b["high"], float(price))
        b["low"] = min(b["low"], float(price))

    candles = [_finalize_candle(b, candle_seconds, tick, ratio, min_vol)
               for b in buckets.values()]
    candles.sort(key=lambda c: c["start_ts"])
    return candles[-max_candles:] if max_candles > 0 else candles


def _finalize_candle(b: dict, candle_seconds: float, tick: float, ratio: float, min_vol: float) -> dict:
    vols = b["levels"]                                 # k → [bid, ask]

    def imbalance(k: int) -> str | None:
        bid, ask = vols[k]
        below_bid = vols.get(k - 1, (0.0, 0.0))[0]     # bid du niveau EN DESSOUS (diagonale ask)
        above_ask = vols.get(k + 1, (0.0, 0.0))[1]     # ask du niveau AU DESSUS (diagonale bid)
        is_ask = ask >= ratio * below_bid and ask >= min_vol
        is_bid = bid >= ratio * above_ask and bid >= min_vol
        if is_ask and is_bid:                          # les deux : côté au volume dominant
            return "ASK" if ask >= bid else "BID"
        return "ASK" if is_ask else "BID" if is_bid else None

    levels = []
    total = 0.0
    poc_k, poc_total = None, -1.0
    for k in sorted(vols, reverse=True):               # prix décroissant
        bid, ask = vols[k]
        lvl_total = bid + ask
        total += lvl_total
        if lvl_total > poc_total:                      # POC = volume total max (1er = prix haut sur égalité)
            poc_total, poc_k = lvl_total, k
        levels.append({"price": round(k * tick, 10), "bid_vol": bid, "ask_vol": ask,
                       "imbalance": imbalance(k)})
    return {
        "start_ts": b["start_ts"], "end_ts": b["start_ts"] + candle_seconds,
        "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
        "poc": round(poc_k * tick, 10) if poc_k is not None else None,
        "total_volume": total, "levels": levels,
    }
