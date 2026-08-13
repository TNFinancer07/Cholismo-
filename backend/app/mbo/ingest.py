"""Ingestion Parquet MBO → événements canoniques (D-079, phase P3).

Port de `io/ingest.ts` + `io/normalize.ts` (artefact v1.7). Lit un fichier Databento
(GLBX.MDP3) et rend des `MboEvent` déscalés, **avec ses statistiques de rejet**.

**`pyarrow` est une dépendance OPTIONNELLE**, importée à l'intérieur de la fonction. Le cœur —
schéma d'événements et carnet — n'en dépend pas : il se teste et tourne sans. Le rejeu Parquet
est une préoccupation de backtest, pas du terminal live, et l'imposer au démarrage de
l'application ferait payer ~100 Mo de dépendance à un chemin qui ne s'en sert jamais.

**Aucune ligne n'est écartée sans être comptée**, avec son motif. Un fichier à moitié rejeté qui
produit un backtest d'allure normale est le pire résultat possible : le taux de rejet est donc
calculé et remonté, pas seulement disponible.

**Le fixed-point Databento.** `price` est un `int64` en unités de 1e-9. On déscale en float :
un prix ES (~5000) vaut 5 × 10¹² en brut, très en dessous des 2⁵³ où un flottant perdrait de la
précision. Les **horodatages**, eux, restent entiers — c'est là que le flottant collapserait
(voir `events.py`).

**Non-monotonie : signalée, jamais réordonnée en silence.** Un recul temporel dans un fichier
est une anomalie de capture. Trier discrètement ferait disparaître le symptôme d'un problème de
données que l'opérateur doit connaître avant d'en tirer des conclusions.
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from .events import IngestStats, MboAction, MboEvent, MboSide, RejectCode, finite

#: Colonnes du schéma MBO Databento. Une colonne manquante est fatale au fichier, pas à la ligne :
#: on ne devine pas une colonne absente.
REQUIRED_COLUMNS = ("ts_event", "action", "side", "price", "size", "order_id", "sequence")

#: Databento : prix int64 en fixed-point 1e-9.
PRICE_SCALE = 1_000_000_000

#: Au-delà, on consigne un trou. 1 s sur un flux MBO ES est déjà énorme. PLACEHOLDER.
GAP_THRESHOLD_NS = 1_000_000_000

_ACTIONS = {MboAction.ADD, MboAction.CANCEL, MboAction.MODIFY, MboAction.TRADE,
            MboAction.FILL, MboAction.CLEAR}
_SIDES = {MboSide.BID, MboSide.ASK, MboSide.NONE}


class MboIngestError(Exception):
    """Fichier inexploitable (illisible, colonne requise absente). Distinct d'une LIGNE rejetée :
    un fichier qu'on ne peut pas lire n'est pas un fichier à moitié bon."""


def read_parquet_rows(path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Lit le Parquet en mémoire. `pyarrow` est importé ICI — voir docstring du module."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:                       # pragma: no cover - dépend de l'install
        raise MboIngestError(
            "pyarrow est requis pour lire un Parquet MBO (pip install -r requirements-dev.txt)"
        ) from exc
    try:
        table = pq.read_table(path)
    except Exception as exc:
        raise MboIngestError(f"Parquet illisible : {type(exc).__name__}") from exc
    columns = list(table.column_names)
    data = table.to_pydict()
    rows = [{col: data[col][i] for col in columns} for i in range(table.num_rows)]
    return rows, columns


def normalize_row(row: dict[str, Any], stats: IngestStats,
                  symbol_default: str = "") -> Optional[MboEvent]:
    """Une ligne brute → un `MboEvent`, ou `None` avec un motif compté. Ne lève jamais."""
    ts_event = row.get("ts_event")
    if not isinstance(ts_event, int) or isinstance(ts_event, bool):
        stats.reject(RejectCode.MISSING_TIMESTAMP)
        return None

    action = row.get("action")
    if action not in _ACTIONS:
        stats.reject(RejectCode.UNKNOWN_ACTION)
        return None

    side = row.get("side")
    if side not in _SIDES:
        stats.reject(RejectCode.UNKNOWN_SIDE)
        return None

    raw_price = row.get("price")
    if not finite(raw_price):
        stats.reject(RejectCode.NON_FINITE_PRICE)
        return None
    price = float(raw_price) / PRICE_SCALE

    size = row.get("size")
    if not finite(size) or size < 0:
        stats.reject(RejectCode.NON_POSITIVE_SIZE)
        return None
    # Un CLEAR porte légitimement une taille nulle ; ailleurs, zéro n'est pas une quantité.
    if size == 0 and action != MboAction.CLEAR:
        stats.reject(RejectCode.NON_POSITIVE_SIZE)
        return None

    ts_recv = row.get("ts_recv")
    return MboEvent(
        ts_event=int(ts_event),
        ts_recv=int(ts_recv) if isinstance(ts_recv, int) and not isinstance(ts_recv, bool)
        else int(ts_event),
        action=str(action), side=str(side), price=price, size=float(size),
        order_id=int(row.get("order_id") or 0), sequence=int(row.get("sequence") or 0),
        symbol=str(row.get("symbol") or symbol_default),
    )


def ingest_parquet(path: str, *, gap_threshold_ns: int = GAP_THRESHOLD_NS,
                   drop_out_of_order: bool = False) -> tuple[list[MboEvent], IngestStats]:
    """Lit un Parquet MBO et rend `(événements, statistiques)`.

    `drop_out_of_order=False` par défaut : un recul temporel est **signalé et conservé**. Trier
    ou jeter en silence ferait disparaître le symptôme d'un problème de capture que l'opérateur
    doit connaître avant d'en tirer la moindre conclusion. Le passer à `True` est un choix
    explicite, et les lignes jetées sont comptées comme les autres.
    """
    rows, columns = read_parquet_rows(path)
    stats = IngestStats()

    missing = [col for col in REQUIRED_COLUMNS if col not in columns]
    if missing:
        # Fatal au FICHIER : on ne devine pas une colonne absente. Compté quand même, pour que
        # le motif apparaisse dans le rapport et pas seulement dans un message d'exception.
        stats.reject(RejectCode.MISSING_COLUMN)
        raise MboIngestError(f"colonnes requises absentes : {', '.join(missing)}")

    events: list[MboEvent] = []
    previous_ts: Optional[int] = None
    for row in rows:
        stats.rows_read += 1
        event = normalize_row(row, stats)
        if event is None:
            continue

        if previous_ts is not None:
            if event.ts_event < previous_ts:
                stats.out_of_order_count += 1
                if drop_out_of_order:
                    stats.reject(RejectCode.OUT_OF_ORDER)
                    continue
            elif event.ts_event - previous_ts > gap_threshold_ns:
                stats.gaps.append({"from": previous_ts, "to": event.ts_event,
                                   "duration_ns": event.ts_event - previous_ts})
        previous_ts = max(previous_ts, event.ts_event) if previous_ts is not None else event.ts_event

        events.append(event)
        stats.events_emitted += 1
        stats.first_ts = event.ts_event if stats.first_ts is None else min(stats.first_ts,
                                                                          event.ts_event)
        stats.last_ts = event.ts_event if stats.last_ts is None else max(stats.last_ts,
                                                                        event.ts_event)
    return events, stats


def replay(events: Iterator[MboEvent], book: Any) -> Iterator[tuple[MboEvent, bool]]:
    """Rejeu tick-by-tick : applique chaque événement au carnet et rend `(événement, changé)`.

    Générateur — le carnet est incrémenté **au fil de l'eau**, sans matérialiser un état par
    événement. C'est ce qui permet d'armer le détecteur de sweep sur l'état exact du carnet à
    l'instant du setup, plutôt que sur une photo de fin de fichier."""
    for event in events:
        yield event, book.apply(event)
