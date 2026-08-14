"""SSE broadcaster — the schema is ONE object but travels on cadence-segmented channels
(CLAUDE §6): `fast` (sub-second: s1, bridge, sync, signal, statut) and `slow` (s2/cascade/
matrix). Events are PARTIAL, per block: event name = block name, data = block JSON.
Macro is never re-pushed on microstructure ticks.

Troisième canal `options` (D-075) — cadence propre au Pont Options : le worker publie toutes
les 5 s, la macro toutes les 15 s, la microstructure 4×/s. Les mêler forcerait le plus lent à
la cadence du plus rapide (`CLAUDE §6` : « ne jamais re-pousser la macro à chaque tick
microstructure »). Arbitrage transport en D-074 : SSE conservé, pas de passerelle WebSocket.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

CHANNELS = ("fast", "slow", "options")


class Broadcaster:
    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = {c: set() for c in CHANNELS}
        self._last: dict[str, dict[str, str]] = {c: {} for c in CHANNELS}  # replay cache per block

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers[channel].add(queue)
        # Hydrate the new subscriber with the last known state of each block.
        for event_name, data in self._last[channel].items():
            queue.put_nowait({"event": event_name, "data": data})
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        self._subscribers[channel].discard(queue)

    def publish(self, channel: str, event_name: str, payload: Any, replay: bool = True) -> None:
        """`replay=False` pour un ÉVÉNEMENT éphémère (ex: `trade_manifest`, D-046) : le cache de
        replay hydrate les abonnés neufs avec l'ÉTAT des blocs — re-livrer un ticket d'avant la
        connexion serait un signal zombie (la garde mort-né D-045 le jetterait, mais un ticket
        encore dans son TTL serait ré-affiché → double ACK possible). Un événement ne se rejoue pas."""
        data = json.dumps(payload, ensure_ascii=False)
        if replay:
            self._last[channel][event_name] = data
        for queue in list(self._subscribers[channel]):
            try:
                queue.put_nowait({"event": event_name, "data": data})
            except asyncio.QueueFull:
                # Slow consumer: drop oldest to keep latency bounded (hot path stays fast).
                try:
                    queue.get_nowait()
                    queue.put_nowait({"event": event_name, "data": data})
                except Exception:
                    pass


broadcaster = Broadcaster()
