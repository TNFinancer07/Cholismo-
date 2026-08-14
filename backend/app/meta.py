"""Field-level metadata wrapper — every ContextSchema field carries a pedigree (PRD §0).

freshness ∈ FRESH | STALE | ABSENT. `No signal without data` (CLAUDE §2.3): a missing or
NaN value is ABSENT with value=None — never a fabricated number rendered as real.
"""
from __future__ import annotations

import math
import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    ABSENT = "ABSENT"


class MetaField(BaseModel):
    value: Any = None
    last_update_ts: Optional[float] = None
    source: str = ""
    freshness: Freshness = Freshness.ABSENT
    # Additive quality flags (e.g. cross-source contradiction, clock desync) — D-012/D-016.
    flags: list[str] = Field(default_factory=list)


def make_meta(
    value: Any,
    source: str,
    last_update_ts: Optional[float],
    stale_after: float,
    absent_after: float,
    now: Optional[float] = None,
    flags: Optional[list[str]] = None,
) -> MetaField:
    """Classify a raw reading. NaN or no timestamp -> ABSENT (fail-closed)."""
    now = now if now is not None else time.time()
    is_nan = isinstance(value, float) and math.isnan(value)
    if value is None or is_nan or last_update_ts is None:
        return MetaField(value=None, last_update_ts=last_update_ts, source=source,
                         freshness=Freshness.ABSENT, flags=flags or [])
    age = now - last_update_ts
    if age > absent_after:
        # Too old to trust at all: value withheld, not displayed as real (CLAUDE §2.3).
        return MetaField(value=None, last_update_ts=last_update_ts, source=source,
                         freshness=Freshness.ABSENT, flags=flags or [])
    freshness = Freshness.STALE if age > stale_after else Freshness.FRESH
    return MetaField(value=value, last_update_ts=last_update_ts, source=source,
                     freshness=freshness, flags=flags or [])
