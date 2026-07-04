"""MarketDataSource — the single seam between the terminal and the world (CLAUDE §4).

Swappable: the mock and any real feed implement the same interface. Implementations write
raw readings into Redis (mock -> Redis -> schema -> SSE, TASKS 2.4); the engine never
knows which one is plugged in.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..redis_state import RedisState


class MarketDataSource(ABC):
    @abstractmethod
    async def tick_fast(self, state: RedisState) -> None:
        """Produce sub-second microstructure readings (s1, bridge, fx)."""

    @abstractmethod
    async def tick_slow(self, state: RedisState) -> None:
        """Produce slow macro readings (cascade, matrix, real rates)."""
