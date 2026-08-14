"""Footprint, imbalances, delta et fusion carnet L2 (D-037 + D-042).

Agrège le flux Time & Sales (prints OBSERVÉS, §2.1) par BOUGIE puis par NIVEAU de prix (quantifié
sur la grille de tick) : BUY = agresseur à l'ASK (`ask_vol`), SELL = agresseur au BID (`bid_vol`).
Par bougie : OHLC, POC (volume total max), IMBALANCES DIAGONALES (ask[k]↔bid[k−1] / bid[k]↔ask[k+1]),
DELTA (agresseur net) et, sur la bougie en formation, la LIQUIDITÉ AU REPOS du carnet L2.

Notes de conception :
- **Bougies** : bucket temporel (`candle_seconds`) ou TICK-BASED (`ticks_per_candle` prints par
  bougie). En mode tick, les prints sont triés chronologiquement d'abord — le tampon amont arrive
  dans l'ordre d'accumulation, pas nécessairement trié ; sans ce tri le découpage ne serait pas
  déterministe.
- **Delta** : par niveau `ask_vol − bid_vol`, par bougie la somme. L'accumulation suit le MÊME
  ordre que la construction des niveaux, donc l'identité `delta_bougie == Σ delta_niveaux` est
  exacte bit à bit (aucune dérive de virgule flottante entre les deux).
- **Carnet L2** : c'est un instantané COURANT. Il n'enrichit QUE la bougie en formation ; l'attacher
  aux bougies passées fabriquerait une association historique fausse (le carnet d'il y a dix minutes
  n'est pas celui d'alors).

Pur et déterministe (aucun LLM, aucun état caché) : `build_footprint(prints, …)` ne dépend que de
ses entrées. FAIL-CLOSED (§3) : print malformé, prix/taille non-fini, côté inconnu → ignorés ;
carnet absent/gelé/aberrant → aucune liquidité exposée ; agrégat qui déborde → bougie retirée.
Jamais un volume, un mur ou une mesure inventés."""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

# Print normalisé, validé : (ts, prix, taille, côté)
Print = tuple[float, float, float, str]


def _bucket(ts: float, candle_seconds: float) -> float:
    return math.floor(ts / candle_seconds) * candle_seconds


def _valid(p: Any) -> Print | None:
    """Print normalisé `(ts, price, size, side)` ou None si invalide (fail-closed §3). Une entrée
    NON-DICT (None, str, nombre) est écartée SEULE : garbage is not data, et une liste de prints
    corrompue ne doit jamais faire tomber le hot path."""
    if not isinstance(p, dict):
        return None
    price, size, side, ts = p.get("price"), p.get("size"), p.get("side"), p.get("ts")
    if (isinstance(price, (int, float)) and math.isfinite(price)
            and isinstance(size, (int, float)) and math.isfinite(size) and size > 0
            and isinstance(ts, (int, float)) and math.isfinite(ts)
            and side in ("BUY", "SELL")):
        return float(ts), float(price), float(size), side
    return None


def build_footprint(prints: Sequence[Any], candle_seconds: float, tick: float,
                    ratio: float, min_vol: float, max_candles: int,
                    ticks_per_candle: int = 0, book: Any = None) -> list[dict]:
    """Construit les bougies footprint depuis les prints. Retourne les `max_candles` bougies les
    plus récentes, triées par `start_ts` croissant. Chaque bougie : `{start_ts, end_ts, open,
    high, low, close, poc, total_volume, delta, n_prints, book_state, levels}` où chaque niveau est
    `{price, bid_vol, ask_vol, delta, imbalance ∈ ASK|BID|None}` (trié prix décroissant), plus
    `bid_liq`/`ask_liq` quand le carnet est vivant.

    `prints` est délibérément `Sequence[Any]` : la source peut livrer des entrées corrompues, et
    chacune est validée puis écartée isolément (§3) plutôt que de faire confiance au type déclaré.
    `ticks_per_candle > 0` bascule en bougies TICK-BASED (sinon bucket temporel) ; `book` est
    l'instantané L2 courant, appliqué à la seule bougie en formation. Voir les notes de conception
    en tête de module."""
    if tick <= 0 or (ticks_per_candle <= 0 and candle_seconds <= 0):
        return []

    valid = [v for v in (_valid(p) for p in prints) if v is not None]
    buckets: list[dict] = []

    if ticks_per_candle > 0:
        # TICK-BASED : ordre chronologique stable (l'ordre d'arrivée départage les ts égaux),
        # puis découpage en paquets de N prints.
        ordered = sorted(valid, key=lambda v: v[0])
        for i in range(0, len(ordered), ticks_per_candle):
            chunk = ordered[i:i + ticks_per_candle]
            b = _new_bucket(chunk[0])
            for v in chunk:
                _add(b, v, tick)
            b["end_ts"] = b["last_ts"]                 # borne réelle : ts du dernier print
            buckets.append(b)
    else:
        by_start: dict[float, dict] = {}
        for v in valid:
            start = _bucket(v[0], candle_seconds)
            b = by_start.get(start)
            if b is None:
                b = by_start[start] = _new_bucket(v)
                b["start_ts"] = start
                b["end_ts"] = start + candle_seconds
            _add(b, v, tick)
        buckets = sorted(by_start.values(), key=lambda b: b["start_ts"])

    book_maps = _book_maps(book, tick)
    last = len(buckets) - 1
    candles = [_finalize_candle(b, tick, ratio, min_vol, book_maps if i == last else None)
               for i, b in enumerate(buckets)]
    # Agrégat non-fini (volumes absurdes → débordement de la somme) : on ne publie JAMAIS un
    # `delta`/`total_volume` égal à `inf`, qui s'afficherait comme une mesure réelle. La bougie
    # corrompue est retirée — pas de donnée plutôt qu'une fausse (§3).
    candles = [c for c in candles
               if math.isfinite(c["delta"]) and math.isfinite(c["total_volume"])]
    candles.sort(key=lambda c: c["start_ts"])
    return candles[-max_candles:] if max_candles > 0 else candles


def _new_bucket(v: Print) -> dict:
    ts, price, _size, _side = v
    return {"start_ts": ts, "end_ts": ts, "levels": {},   # k → [bid_vol, ask_vol]
            "first_ts": ts, "last_ts": ts, "n_prints": 0,
            "open": price, "close": price, "high": price, "low": price}


def _add(b: dict, v: Print, tick: float) -> None:
    ts, price, size, side = v
    k = round(price / tick)
    lvl = b["levels"].get(k)
    if lvl is None:
        lvl = b["levels"][k] = [0.0, 0.0]
    if side == "BUY":
        lvl[1] += size                                 # ask volume (agresseur à l'ask)
    else:
        lvl[0] += size                                 # bid volume
    b["n_prints"] += 1
    # OHLC : open = print au ts le plus PETIT (rafale à ts égal → 1er de l'ordre d'entrée, d'où le
    # `<` strict) ; close = ts le plus GRAND (rafale → dernier, d'où le `>=`).
    if ts < b["first_ts"]:
        b["first_ts"], b["open"] = ts, price
    if ts >= b["last_ts"]:
        b["last_ts"], b["close"] = ts, price
    b["high"] = max(b["high"], price)
    b["low"] = min(b["low"], price)


def _book_maps(book: Any, tick: float) -> tuple[dict[int, float], dict[int, float]] | None:
    """Carnet L2 `{bids: [[prix, taille]…], asks: […]}` → deux cartes `k → liquidité au repos`.
    None si absent/mal formé, ou si AUCUNE entrée n'est exploitable : un carnet vide ou corrompu
    n'est pas « vivant » — on ne fabrique jamais de mur de liquidité (§3)."""
    if not isinstance(book, dict):
        return None
    out: list[dict[int, float]] = [{}, {}]
    for i, key in enumerate(("bids", "asks")):
        rows = book.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not (isinstance(row, (list, tuple)) and len(row) >= 2):
                continue
            price, size = row[0], row[1]
            # `price > 0` exigé, comme la validation DOM du moteur : un carnet dont AUCUNE
            # entrée n'est exploitable doit retomber sur ABSENT. Le déclarer « vivant » le ferait
            # affirmer 0 liquidité sur des niveaux réels — une affirmation FAUSSE, pire qu'une
            # absence (§3).
            if not (isinstance(price, (int, float)) and math.isfinite(price) and price > 0
                    and isinstance(size, (int, float)) and math.isfinite(size) and size > 0):
                continue                               # entrée aberrante/non-finie → ignorée (§3)
            k = round(float(price) / tick)
            out[i][k] = out[i].get(k, 0.0) + float(size)
    return (out[0], out[1]) if (out[0] or out[1]) else None


def _finalize_candle(b: dict, tick: float, ratio: float, min_vol: float,
                     book_maps: tuple[dict[int, float], dict[int, float]] | None) -> dict:
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
    delta = 0.0
    poc_k, poc_total = None, -1.0
    for k in sorted(vols, reverse=True):               # prix décroissant
        bid, ask = vols[k]
        lvl_total = bid + ask
        total += lvl_total
        delta += ask - bid                             # agresseur net du niveau (D-042)
        if lvl_total > poc_total:                      # POC = volume total max (1er = prix haut sur égalité)
            poc_total, poc_k = lvl_total, k
        lvl = {"price": round(k * tick, 10), "bid_vol": bid, "ask_vol": ask,
               "delta": ask - bid, "imbalance": imbalance(k)}
        if book_maps is not None:                      # liquidité AU REPOS (carnet vivant seulement)
            lvl["bid_liq"] = book_maps[0].get(k, 0.0)
            lvl["ask_liq"] = book_maps[1].get(k, 0.0)
        levels.append(lvl)
    return {
        "start_ts": b["start_ts"], "end_ts": b["end_ts"],
        "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
        "poc": round(poc_k * tick, 10) if poc_k is not None else None,
        "total_volume": total, "delta": delta, "n_prints": b["n_prints"],
        "book_state": "LIVE" if book_maps is not None else "ABSENT",
        "levels": levels,
    }
