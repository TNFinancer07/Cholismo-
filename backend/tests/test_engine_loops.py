"""Régression — dérive de cadence de la _slow_loop (RUNTIME_LOOPS Loop D, piège drift).

Bug capturé : la boucle lente dormait SLOW_TICK_SECONDS fixe APRÈS le travail →
intervalle réel = cadence + durée du tick. Le contrat (CLAUDE §6) est une cadence,
pas une pause : l'intervalle doit rester ≈ SLOW_TICK_SECONDS quelle que soit la durée
du tick (comme la _fast_loop, qui compense déjà).
"""
import asyncio
import time

from app import config
from app.engine import Engine


class _SlowTickDS:
    """Datasource stub dont le tick lent consomme une part significative de la cadence."""

    def __init__(self, delay: float):
        self.delay = delay

    async def tick_slow(self, state) -> None:
        await asyncio.sleep(self.delay)

    async def tick_fast(self, state) -> None:  # jamais appelé ici
        pass


def test_slow_loop_interval_stays_on_cadence(monkeypatch):
    cadence = 0.3
    tick_duration = 0.25
    monkeypatch.setattr(config, "SLOW_TICK_SECONDS", cadence)

    engine = Engine(_SlowTickDS(tick_duration), state=object())
    stamps: list[float] = []

    async def record_assemble(now: float) -> None:
        stamps.append(time.monotonic())

    engine._assemble_slow = record_assemble  # isole la cadence du reste (Redis/SSE)

    async def run() -> None:
        task = asyncio.create_task(engine._slow_loop())
        # 4 cadences + marge : au rythme correct on observe >= 4 assemblages
        await asyncio.sleep(cadence * 4 + tick_duration + 0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    assert len(stamps) >= 3, f"trop peu d'itérations observées : {len(stamps)}"
    intervals = [b - a for a, b in zip(stamps, stamps[1:])]
    # Bug : intervalle = cadence + tick = ~0.55 s. Corrigé : ~0.30 s. Seuil à mi-chemin,
    # large vis-à-vis du jitter d'ordonnanceur.
    assert all(i < cadence + tick_duration / 2 for i in intervals), (
        f"dérive de cadence : intervalles {[round(i, 3) for i in intervals]} "
        f"(attendu ≈ {cadence} s, pas cadence+tick ≈ {cadence + tick_duration} s)")
