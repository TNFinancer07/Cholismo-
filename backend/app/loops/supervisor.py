"""Superviseur de boucles (D-073).

Démarre, arrête et surveille N boucles déclarées. Il ne DÉCIDE rien et n'exécute aucun ordre
(§2.1) : il cadence des ticks injectés et rapporte leur santé.

Deux choix qui méritent leur justification :

- **Une spec sans tick est enregistrable.** C'est ce qui permet de déclarer les cinq boucles
  du système avant que leurs corps existent, sans écrire un stub qui feint de tourner : elle
  ressort `NOT_IMPLEMENTED`, donc `all_healthy: false`. La capacité annoncée et absente est
  VISIBLE, ce qui est le contraire d'un mensonge par omission.
- **`stop_all()` arrête tout le monde, quoi qu'il arrive.** Une boucle déjà morte au moment de
  l'arrêt ne doit pas empêcher les suivantes de se fermer proprement (RUNTIME_LOOPS Loop H) ;
  l'arrêt est idempotent et se termine toujours.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from .contract import Cadence, LoopHealth, LoopSpec, ManagedLoop, PeriodicLoop
from .health import project

log = logging.getLogger("cholismo.loops.supervisor")


class LoopSupervisor:
    """Registre vivant des boucles : `register` → `start_all` → `health` → `stop_all`."""

    def __init__(self, *, clock: Optional[Callable[[], float]] = None):
        self._clock = clock
        self._loops: dict[str, ManagedLoop] = {}

    def register(self, spec: LoopSpec, tick: Optional[Callable[..., Any]] = None) -> ManagedLoop:
        """Déclare une boucle. `tick=None` = déclarée mais pas câblée (`NOT_IMPLEMENTED`).

        Un doublon de nom est REFUSÉ : deux boucles homonymes rendraient la projection de santé
        ambiguë, et c'est précisément la lisibilité qu'on cherche ici."""
        if spec.name in self._loops:
            raise ValueError(f"boucle déjà enregistrée : {spec.name}")
        cls = PeriodicLoop if spec.cadence is Cadence.PERIODIC else ManagedLoop
        loop = cls(spec, tick, clock=self._clock)
        self._loops[spec.name] = loop
        return loop

    def get(self, name: str) -> ManagedLoop:
        return self._loops[name]

    async def start_all(self) -> None:
        """Démarre les boucles cadencées câblées. Les boucles événementielles n'ont pas de
        tâche : elles sont pilotées par leur déclencheur (armement, message Redis)."""
        for loop in self._loops.values():
            if isinstance(loop, PeriodicLoop):
                await loop.start()
        declared = len(self._loops)
        wired = sum(1 for loop in self._loops.values() if loop._tick is not None)
        if wired < declared:
            # INFO et non WARNING : à ce stade du build, des boucles déclarées-non-câblées sont
            # l'état NORMAL et attendu. Ce qui compte est que ce soit dit.
            log.info("boucles : %d déclarées, %d câblées — les autres restent NOT_IMPLEMENTED "
                     "(déclarées, pas simulées)", declared, wired)

    async def stop_all(self) -> None:
        """Arrêt gracieux. Chaque arrêt est isolé : une boucle qui échoue à se fermer ne doit
        pas laisser les suivantes tourner derrière elle."""
        for loop in self._loops.values():
            if not isinstance(loop, PeriodicLoop):
                continue
            try:
                await loop.stop()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("boucle %s : arrêt en échec (les autres sont arrêtées quand même)",
                              loop.spec.name)

    def healths(self, now: Optional[float] = None) -> list[LoopHealth]:
        return [loop.health(now) for loop in self._loops.values()]

    def health(self, now: Optional[float] = None) -> dict:
        """Projection sérialisable — destinée au canal SSE `options` et à un futur endpoint."""
        return project(self.healths(now), now=now)
