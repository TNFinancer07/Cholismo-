"""Schéma d'événements MBO canonique (D-079, phase P3).

Port de `io/events.ts` (artefact v1.7). Le format s'aligne sur le schéma MBO de Databento
(GLBX.MDP3), qui est aussi celui de son flux live — même code en rejeu et en direct.

**L'invariant de déterminisme, et pourquoi il change de nature en Python.** L'artefact impose
`bigint` : un epoch nanoseconde vaut ~1,78 × 10¹⁸, très au-dessus de `Number.MAX_SAFE_INTEGER`
(9,0 × 10¹⁵), si bien qu'en `number` deux événements distincts **collapsent** sur la même valeur
et l'ordre de rejeu cesse d'être reproductible. Les entiers Python sont illimités : l'invariant
est acquis **tant qu'on reste en `int`**. Un `float` porte exactement la même mantisse de 53 bits
que le `number` JS — stocker des ns en flottant réintroduirait le bug à l'identique. C'est
verrouillé par test.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


class MboAction:
    """Sémantique MDP 3.0 / Databento."""
    ADD = "A"
    CANCEL = "C"
    MODIFY = "M"
    TRADE = "T"
    FILL = "F"
    CLEAR = "R"


class MboSide:
    BID = "B"
    ASK = "A"
    NONE = "N"


@dataclass(frozen=True)
class MboEvent:
    """Événement de carnet canonique. Prix en unités réelles (déjà déscalé du fixed-point
    source), horodatages en **nanosecondes entières**."""
    ts_event: int
    ts_recv: int
    action: str
    side: str
    price: float
    size: float
    order_id: int
    sequence: int
    symbol: str


class RejectCode:
    NON_FINITE_PRICE = "NON_FINITE_PRICE"
    NON_POSITIVE_SIZE = "NON_POSITIVE_SIZE"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    UNKNOWN_SIDE = "UNKNOWN_SIDE"
    MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
    MISSING_COLUMN = "MISSING_COLUMN"
    OUT_OF_ORDER = "OUT_OF_ORDER"


@dataclass
class IngestStats:
    """Remontées à l'opérateur, **jamais silencieuses** : aucune ligne n'est écartée sans être
    comptée avec son motif. Un fichier à moitié rejeté qui produit un backtest d'allure normale
    est le pire résultat possible."""
    rows_read: int = 0
    events_emitted: int = 0
    rows_rejected: int = 0
    rejections_by_reason: dict[str, int] = field(default_factory=dict)
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None
    out_of_order_count: int = 0
    gaps: list[dict[str, int]] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rows_rejected += 1
        self.rejections_by_reason[reason] = self.rejections_by_reason.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_read": self.rows_read,
            "events_emitted": self.events_emitted,
            "rows_rejected": self.rows_rejected,
            "rejections_by_reason": dict(self.rejections_by_reason),
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "out_of_order_count": self.out_of_order_count,
            "gaps": list(self.gaps),
            # Un taux de rejet élevé ne doit pas se lire seulement dans un compteur : il se
            # calcule ici une fois pour toutes, pour que l'appelant n'ait pas à y penser.
            "reject_ratio": (self.rows_rejected / self.rows_read) if self.rows_read else 0.0,
        }


def finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
