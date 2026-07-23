"""Volume Profile dynamique (D-041).

Agrège le volume exécuté OBSERVÉ (§2.1) par NIVEAU de prix, puis calcule POC, Value Area (70 %),
VAH/VAL et les Low Volume Nodes. Distinct de `structure.vpoc/vah/val/lvn` (scalaires fournis par la
source) : ici la DISTRIBUTION complète est auto-calculée depuis le tape.

Pur et déterministe (aucun LLM, aucun état caché). FAIL-CLOSED (§3) : prix/volume non-fini →
ignoré ; grille contiguë bornée (un prix aberrant lointain n'explose jamais le profil). Les
paramètres (VA 70 %, ratio LVN) sont fixés ; le 70 % est la convention Market Profile (AUTORITÉ de
facto), le ratio LVN est **v1 provisional**."""
from __future__ import annotations

import math


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def build_volume_profile(volume_by_price, tick: float, va_pct: float,
                         lvn_ratio: float, max_levels: int, buy_by_price=None) -> dict:
    """Construit le profil depuis une distribution `{prix: volume}`. Retourne `{tick, va_pct,
    total_volume, poc, vah, val, levels: [{price, volume}], lvn: [prix]}`. `levels` = grille
    CONTIGUË (lacunes à 0) triée prix croissant ; POC/VAH/VAL/lvn = prix.

    `buy_by_price` (optionnel, source-backed depuis `side` du tape) : quand fourni, chaque niveau
    porte AUSSI `buy`/`sell` (vendeur = total − acheteur, borné ≥ 0, fail-safe §3). Absent par
    défaut → aucune valeur acheteur/vendeur INVENTÉE (§3)."""
    empty = {"tick": tick, "va_pct": va_pct, "total_volume": 0.0, "poc": None,
             "vah": None, "val": None, "levels": [], "lvn": []}
    if tick <= 0 or not isinstance(volume_by_price, dict):
        return empty

    # 1) agrège sur la grille de tick : k = round(prix/tick) ; ignore non-fini (fail-closed §3)
    kvol: dict[int, float] = {}
    for price, vol in volume_by_price.items():
        if not (_finite(price) and _finite(vol) and vol > 0):
            continue
        k = round(float(price) / tick)
        kvol[k] = kvol.get(k, 0.0) + float(vol)
    if not kvol:
        return empty

    # 1b) volume ACHETEUR par niveau (optionnel, même grille) — vendeur = total − acheteur
    kbuy: dict[int, float] = {}
    if isinstance(buy_by_price, dict):
        for price, vol in buy_by_price.items():
            if not (_finite(price) and _finite(vol) and vol > 0):
                continue
            kbuy[round(float(price) / tick)] = kbuy.get(round(float(price) / tick), 0.0) + float(vol)

    # 2) POC = volume max (égalité → k le plus bas = prix le plus bas, déterministe)
    poc_k = max(sorted(kvol), key=lambda k: kvol[k])
    poc_vol = kvol[poc_k]

    # 3) fenêtre CONTIGUË bornée à max_levels autour du POC (prix aberrant lointain borné)
    lo_k, hi_k = min(kvol), max(kvol)
    if max_levels > 0 and (hi_k - lo_k + 1) > max_levels:
        half = max_levels // 2
        lo_k, hi_k = poc_k - half, poc_k + (max_levels - half - 1)
    grid = [(k, kvol.get(k, 0.0)) for k in range(lo_k, hi_k + 1)]   # lacunes remplies à 0
    total = sum(v for _, v in grid)

    # 4) Value Area 70 % : depuis le POC, étend vers le voisin au plus gros volume (égalité → haut)
    va_lo = va_hi = poc_k
    va_vol = poc_vol
    target = va_pct * total
    while va_vol < target and (va_lo > lo_k or va_hi < hi_k):
        up = kvol.get(va_hi + 1, 0.0) if va_hi < hi_k else -1.0
        down = kvol.get(va_lo - 1, 0.0) if va_lo > lo_k else -1.0
        if up < 0 and down < 0:
            break
        if up >= down:                                # égalité → côté haut
            va_hi += 1
            va_vol += kvol.get(va_hi, 0.0)
        else:
            va_lo -= 1
            va_vol += kvol.get(va_lo, 0.0)

    # 5) LVN : minima LOCAUX stricts sous le ratio (une lacune à 0 qualifie)
    lvn_thresh = lvn_ratio * poc_vol
    lvn = []
    for i in range(1, len(grid) - 1):
        k, v = grid[i]
        if v < grid[i - 1][1] and v < grid[i + 1][1] and v <= lvn_thresh:
            lvn.append(round(k * tick, 10))

    def _level(k: int, v: float) -> dict:
        d = {"price": round(k * tick, 10), "volume": v}
        if buy_by_price is not None:                # split acheteur/vendeur seulement si fourni
            buy = min(kbuy.get(k, 0.0), v)          # borné au total (vendeur jamais négatif §3)
            d["buy"], d["sell"] = buy, v - buy
        return d

    return {
        "tick": tick, "va_pct": va_pct, "total_volume": total,
        "poc": round(poc_k * tick, 10),
        "vah": round(va_hi * tick, 10), "val": round(va_lo * tick, 10),
        "levels": [_level(k, v) for k, v in grid],
        "lvn": lvn,
    }
