"""Heatmap de liquidité (LOB) — accumulation temporelle du carnet L2 (D-036).

Transforme la série de carnets `s1_state.order_book` (D-025) en une fenêtre glissante de
COLONNES temporelles (une par tick rapide, 4 Hz) que le frontend Canvas dessine comme une
profondeur historique. Pure et déterministe (aucun état caché) : l'historique est passé en
entrée et retourné, l'appelant (le moteur) le conserve.

FAIL-CLOSED (§3) : si le carnet n'est pas FRESH ou est vide, AUCUNE colonne n'est ajoutée
(jamais une profondeur inventée) — l'historique est conservé tel quel et la fraîcheur du bloc
suit le carnet. OBSERVATION seule (§2.1) : donnée de rendu, jamais un ordre.
"""
from __future__ import annotations

from .meta import Freshness, MetaField


def accumulate_heatmap(history: list[dict], order_book: MetaField, now: float,
                       max_cols: int, levels: int) -> tuple[list[dict], dict]:
    """Ajoute (si le carnet est FRESH et non vide) une colonne `{ts, bids, asks}` — les `levels`
    meilleurs niveaux par côté — puis borne l'historique aux `max_cols` colonnes les plus
    récentes. Retourne `(nouvel_historique, value)` où `value = {columns, max_size}` (max_size =
    plus grande taille toutes colonnes/côtés confondus, pour la normalisation couleur)."""
    columns = list(history)
    if order_book.freshness == Freshness.FRESH and isinstance(order_book.value, dict):
        bids = (order_book.value.get("bids") or [])[:levels]
        asks = (order_book.value.get("asks") or [])[:levels]
        if bids and asks:
            columns.append({"ts": now, "bids": bids, "asks": asks})
    if max_cols > 0:
        columns = columns[-max_cols:]

    max_size = 0.0
    for col in columns:
        for _, size in col["bids"]:
            if size > max_size:
                max_size = size
        for _, size in col["asks"]:
            if size > max_size:
                max_size = size

    return columns, {"columns": columns, "max_size": max_size}
