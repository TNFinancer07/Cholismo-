"""Intra-session state in Redis (CLAUDE §4): raw readings, source up/down, scenario,
decision window (C3), self-checks (C5), streak audit acks (C2), engine heartbeat.

Fail-closed: callers treat any Redis failure as `dependency down` -> Phase 0 BLOCKED.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import redis.asyncio as aioredis

from . import config

NS = "cholismo"


class RedisState:
    def __init__(self, url: Optional[str] = None):
        self._redis = aioredis.from_url(url or config.REDIS_URL, decode_responses=True)

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    # -- raw readings written by the data source (mock -> Redis -> schema -> SSE) --

    async def write_raw(self, field: str, value: Any, source: str,
                        ts: Optional[float] = None, flags: Optional[list[str]] = None) -> None:
        payload = {"value": value, "ts": ts if ts is not None else time.time(),
                   "source": source, "flags": flags or []}
        await self._redis.set(f"{NS}:raw:{field}", json.dumps(payload))

    async def read_raw(self, field: str) -> Optional[dict[str, Any]]:
        raw = await self._redis.get(f"{NS}:raw:{field}")
        return json.loads(raw) if raw else None

    async def read_raw_many(self, fields: list[str]) -> dict[str, Optional[dict[str, Any]]]:
        keys = [f"{NS}:raw:{f}" for f in fields]
        values = await self._redis.mget(keys)
        return {f: (json.loads(v) if v else None) for f, v in zip(fields, values)}

    # -- sources up/down (TASKS 2.4: cutting a source must visibly produce STALE/ABSENT) --

    async def set_source_up(self, source: str, up: bool) -> None:
        await self._redis.set(f"{NS}:source:{source}:up", "1" if up else "0")

    async def source_up(self, source: str) -> bool:
        v = await self._redis.get(f"{NS}:source:{source}:up")
        return v != "0"  # default: up

    # -- scenario --

    async def set_scenario(self, scenario: dict[str, Any]) -> None:
        await self._redis.set(f"{NS}:scenario", json.dumps(scenario))

    async def scenario(self) -> Optional[dict[str, Any]]:
        raw = await self._redis.get(f"{NS}:scenario")
        return json.loads(raw) if raw else None

    # -- engine heartbeat (Phase 0 rule ENGINE_FRESH) --

    async def beat(self) -> None:
        await self._redis.set(f"{NS}:engine:heartbeat", str(time.time()))

    async def heartbeat_age(self) -> Optional[float]:
        raw = await self._redis.get(f"{NS}:engine:heartbeat")
        return None if raw is None else time.time() - float(raw)

    # -- C3 decision window --

    async def set_decision_window(self, window: Optional[dict[str, Any]]) -> None:
        key = f"{NS}:decision_window"
        if window is None:
            await self._redis.delete(key)
        else:
            await self._redis.set(key, json.dumps(window))

    async def decision_window(self) -> Optional[dict[str, Any]]:
        raw = await self._redis.get(f"{NS}:decision_window")
        return json.loads(raw) if raw else None

    async def set_decision_cooldown(self, seconds: float) -> None:
        await self._redis.set(f"{NS}:decision_cooldown", "1", ex=max(1, int(seconds)))

    async def in_decision_cooldown(self) -> bool:
        return await self._redis.exists(f"{NS}:decision_cooldown") == 1

    # -- C5 cognitive self-check (per operator, TTL) --

    async def set_selfcheck(self, operator: str, answers: dict[str, Any]) -> None:
        await self._redis.set(f"{NS}:selfcheck:{operator}",
                              json.dumps({"answers": answers, "ts": time.time()}),
                              ex=int(config.SELF_CHECK_TTL_SECONDS))

    async def selfcheck(self, operator: str) -> Optional[dict[str, Any]]:
        raw = await self._redis.get(f"{NS}:selfcheck:{operator}")
        return json.loads(raw) if raw else None

    # -- C2 streak audit ack (keyed by streak bucket so a NEW streak needs a NEW audit) --

    async def ack_streak_audit(self, operator: str, streak: int) -> None:
        await self._redis.set(f"{NS}:streak_ack:{streak}", operator)

    async def streak_audit_acked(self, streak: int) -> bool:
        return await self._redis.exists(f"{NS}:streak_ack:{streak}") == 1

    # -- operational mode (session-level, D-015) --

    async def set_mode(self, mode: str) -> None:
        await self._redis.set(f"{NS}:mode", mode)

    async def mode(self) -> str:
        return await self._redis.get(f"{NS}:mode") or "PRE_SESSION"

    async def close(self) -> None:
        await self._redis.aclose()
