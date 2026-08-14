"""Heatmap de liquidité (LOB) — colonne courante du carnet L2 (D-036, DELTA depuis /polish).

Diffusion en DELTA : à chaque tick rapide (4 Hz) le backend n'émet QUE la colonne courante
`{ts, bids, asks}` (les `levels` meilleurs niveaux FINIS par côté). Le frontend Canvas accumule
les colonnes successives en fenêtre glissante et calcule lui-même la normalisation couleur.
Payload allégé ~60× vs. l'envoi de toute la fenêtre à chaque tick (le heatmap est une viz
éphémère : l'historique se reconstruit côté client en ~15 s après une reconnexion).

FAIL-CLOSED (§3) : carnet non FRESH ou vide → colonne `None` (jamais une profondeur inventée) ;
le frontend conserve/dégrade son tampon selon la fraîcheur. OBSERVATION seule (§2.1).
"""
from __future__ import annotations

import math

from .meta import Freshness, MetaField


def _finite_levels(levels, n: int) -> list[list[float]]:
    """Garde-fou (§3) : ne retient que les `n` premiers niveaux `[prix, taille]` FINIS et bien
    formés. Garantit que le bloc heatmap ne contient jamais NaN/Inf (sinon le JSON SSE serait
    invalide et casserait le parse frontend). Le carnet est déjà validé en amont ; double
    sécurité au niveau du heatmap."""
    out: list[list[float]] = []
    for lvl in (levels or [])[:n]:
        try:
            price, size = float(lvl[0]), float(lvl[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if math.isfinite(price) and math.isfinite(size):
            out.append([price, size])
    return out


def latest_column(order_book: MetaField, now: float, levels: int) -> dict | None:
    """Construit LA colonne courante `{ts, bids, asks}` du heatmap depuis le carnet, ou `None`
    si le carnet n'est pas FRESH ou est vide (fail-closed §3). `ts = now` (temps du tick) : une
    colonne par tick même si le carnet est identique, pour une trame temporelle régulière côté
    frontend."""
    if order_book.freshness != Freshness.FRESH or not isinstance(order_book.value, dict):
        return None
    bids = _finite_levels(order_book.value.get("bids"), levels)
    asks = _finite_levels(order_book.value.get("asks"), levels)
    if not bids or not asks:
        return None
    return {"ts": now, "bids": bids, "asks": asks}
