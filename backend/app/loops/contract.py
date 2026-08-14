"""Contrat commun des boucles d'exécution (D-073).

`RUNTIME_LOOPS.md` décrit les patterns ; `lsr_driver.py` (D-052) en est le gabarit durci, au
prix d'une passe `/devil` complète. Le dépôt comptait déjà **quatre** boucles Loop-D écrites
à la main ; le Pont Options v2 en ajoute **trois**. Refaire sept fois les mêmes parades, c'est
sept occasions de rouvrir la faille que D-052 résume ainsi :

> **une boucle morte ressemble à une boucle calme.**

Ce module factorise ces parades en un contrat unique, et — c'est le vrai apport — rend la
santé de chaque boucle **observable**. C'est `CLAUDE §3` (« no signal without data ») appliqué
aux boucles elles-mêmes : l'UI doit pouvoir afficher « boucle O5 morte » plutôt qu'un kurtosis
figé qui a l'air frais.

**Les parades héritées de D-052, ici en un seul endroit :**

1. **Cadence à l'ÉCHÉANCE** (`loop.time()` monotone), jamais « travail puis sieste fixe » —
   sinon la période réelle vaut `période + durée du travail` et la cadence annoncée est un
   mensonge silencieux. **Aucun rattrapage** : après un tick long on se réancre à maintenant,
   parce qu'une rafale de rattrapage évaluerait le PASSÉ (doctrine D-045 T3).
2. **Backpressure** — les créneaux manqués sont COMPTÉS puis abandonnés, jamais empilés ; une
   exécution concurrente du même tick est droppée (deux ticks du même instant, c'est deux fois
   le même ticket).
3. **Plafond de durée** — un `await` qui ne rend jamais la main devient un échec VISIBLE au
   lieu d'une pendaison muette. Corollaire inchangé : un tick **synchrone** bloquant
   (`time.sleep`, calcul lourd) reste indéfendable — il gèle la boucle avant tout point
   d'attente. C'est un contrat de fournisseur de tick, pas un défaut du superviseur ; le
   lourd se déporte (`asyncio.to_thread`).
4. **Filet d'exception** — la boucle ne meurt JAMAIS sur un imprévu ; l'échec est compté et
   journalisé (une panne se voit).
5. **Boucle tuée de l'extérieur** — `done()` sans être `None` : `start()` la relance et le
   signale, au lieu de la laisser morte en silence. `stop()` ne propage pas l'exception d'une
   tâche déjà morte (un arrêt gracieux n'explose pas au pire moment).

**Le battement ne compte QUE les ticks réussis.** Une boucle qui cycle mais échoue à chaque
tour est vivante et ne produit rien : la déclarer `RUNNING` serait précisément le mensonge que
ce module existe pour empêcher. Elle passe donc `STALLED` — fail-closed (§3).

**Ce module ne DÉCIDE rien** et n'exécute aucun ordre (§2.1) : il cadence des ticks injectés
et rapporte leur santé.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

log = logging.getLogger("cholismo.loops")


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class Cadence(str, Enum):
    """Comment la boucle est déclenchée. La distinction n'est pas cosmétique : elle décide si
    le silence est une panne (voir `heartbeat_stale_s`)."""
    PERIODIC = "PERIODIC"
    EVENT_DRIVEN = "EVENT_DRIVEN"


class Criticality(str, Enum):
    """`HOT` = chemin de décision live, budget `CLAUDE §7` (< ~200 ms, zéro LLM synchrone)."""
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class StarvePolicy(str, Enum):
    """Ce que le CONSOMMATEUR doit faire quand la boucle ne produit plus. Déclaratif : le
    superviseur ne l'applique pas à la place du consommateur, il le rend lisible."""
    FAIL_CLOSED = "FAIL_CLOSED"   # absence de donnée → refus (§3)
    DEGRADE = "DEGRADE"           # poids ramené à 0, signal marqué dégradé (cf. A3/§8)
    HOLD_LAST = "HOLD_LAST"       # dernière valeur conservée, MARQUÉE périmée


class LoopStatus(str, Enum):
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"   # spec déclarée, aucun tick câblé — dit tel quel
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    STALLED = "STALLED"                   # vivante mais plus de battement frais
    DEAD = "DEAD"                         # tâche terminée sans qu'on l'ait demandé


@dataclass(frozen=True)
class LoopSpec:
    """Déclaration d'une boucle. Validée à la CONSTRUCTION : une cadence incohérente doit être
    refusée ici, pas découverte en production."""
    name: str
    cadence: Cadence
    period_s: Optional[float]
    criticality: Criticality
    tick_budget_s: float
    heartbeat_stale_s: Optional[float]
    starve: StarvePolicy
    purpose: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("LoopSpec.name est obligatoire")
        if not _finite(self.tick_budget_s) or self.tick_budget_s <= 0:
            raise ValueError(f"{self.name}: tick_budget_s doit être fini et > 0")
        if self.cadence is Cadence.PERIODIC:
            if not _finite(self.period_s) or self.period_s <= 0:      # type: ignore[arg-type]
                raise ValueError(f"{self.name}: une boucle PERIODIC exige period_s > 0")
            if not _finite(self.heartbeat_stale_s) or self.heartbeat_stale_s is None:
                raise ValueError(f"{self.name}: une boucle PERIODIC exige heartbeat_stale_s")
            # RUNTIME_LOOPS Loop G : « seuil > durée max normale ». Un watchdog qui se
            # déclenche avant même qu'un tick nominal ait eu lieu crie en permanence — donc
            # on apprend à l'ignorer, ce qui est pire que pas de watchdog du tout.
            if self.heartbeat_stale_s <= self.period_s:               # type: ignore[operator]
                raise ValueError(
                    f"{self.name}: heartbeat_stale_s ({self.heartbeat_stale_s}) doit dépasser "
                    f"period_s ({self.period_s}) — sinon le watchdog est en alerte permanente")
        else:
            if self.period_s is not None:
                raise ValueError(
                    f"{self.name}: une boucle EVENT_DRIVEN ne doit pas annoncer une période "
                    "qu'elle n'a pas")
            # Le silence d'une boucle événementielle n'est pas une panne : aucun setup n'est
            # peut-être survenu. Lui donner un seuil de péremption fabriquerait de la fausse
            # alerte — exactement le bruit qui fait ignorer les vraies.
            if self.heartbeat_stale_s is not None:
                raise ValueError(
                    f"{self.name}: une boucle EVENT_DRIVEN n'a pas de seuil de péremption "
                    "(son silence n'est pas une panne)")


@dataclass(frozen=True)
class LoopHealth:
    """Photo de santé d'une boucle. `last_beat_ts`/`age_s` valent `None` tant qu'aucun tick
    n'a réussi — jamais un 0 fabriqué qui se lirait comme « à jour » (§3)."""
    name: str
    status: LoopStatus
    cadence: Cadence
    criticality: Criticality
    starve: StarvePolicy
    period_s: Optional[float]
    last_beat_ts: Optional[float]
    age_s: Optional[float]
    ticks: int
    failures: int
    timeouts: int
    drops: int
    last_error: Optional[str]
    purpose: str


class ManagedLoop:
    """Boucle ÉVÉNEMENTIELLE : pas de cadence propre, mais les mêmes garde-fous sur le tick
    (drop-if-busy, plafond de durée, filet d'exception, battement). C'est la classe de base de
    `PeriodicLoop`, et le runner tel quel pour L4 (gates O1-O5 sur armement)."""

    def __init__(self, spec: LoopSpec, tick: Optional[Callable[..., Any]] = None, *,
                 clock: Optional[Callable[[], float]] = None):
        self.spec = spec
        self._tick = tick
        if clock is None:
            import time as _time
            clock = _time.time
        self._clock = clock
        self._gate = asyncio.Lock()
        self._beat_ts: Optional[float] = None
        self._ticks = 0
        self._failures = 0
        self._timeouts = 0
        self._drops = 0
        self._last_error: Optional[str] = None

    async def run_once(self, *args: Any) -> bool:
        """Un tick, borné et isolé. Rend True si le tick est allé au bout.

        Ne lève JAMAIS (hors annulation, qui doit remonter) : c'est ce qui permet à un appelant
        — cadence interne ou détecteur de sweep — de ne pas avoir à se protéger lui-même."""
        if self._tick is None:
            return False
        if self._gate.locked():
            # Backpressure : une exécution en vol suffit. Rejet NATUREL, pas une panne — donc
            # compté (l'invisible se paie plus tard) mais pas journalisé (hygiène D-046).
            self._drops += 1
            return False
        async with self._gate:
            return await self._invoke(*args)

    async def _invoke(self, *args: Any) -> bool:
        try:
            result = self._tick(*args)                        # type: ignore[misc]
            if inspect.isawaitable(result):
                # `asyncio.timeout` et NON `asyncio.wait_for` : en 3.11, `wait_for` AVALE une
                # annulation externe quand sa future interne vient de se terminer — la boucle
                # survivait alors à son propre `cancel()` et l'arrêt gracieux restait pendu
                # (mesuré en D-052).
                async with asyncio.timeout(self.spec.tick_budget_s):
                    await result
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self._timeouts += 1
            self._last_error = f"tick dépassé ({self.spec.tick_budget_s}s)"
            log.error("boucle %s : tick DÉPASSÉ après %.3fs — traité comme un échec "
                      "(fail-closed : rien de produit ce tour)",
                      self.spec.name, self.spec.tick_budget_s)
            return False
        except Exception as exc:
            self._failures += 1
            self._last_error = repr(exc)
            log.exception("boucle %s : tick en échec (borné : la boucle survit)", self.spec.name)
            return False
        # Battement sur SUCCÈS seulement : une boucle qui cycle sans rien produire n'est pas
        # saine, et l'afficher RUNNING serait le mensonge que ce module existe pour empêcher.
        self._ticks += 1
        self._beat_ts = self._clock()
        return True

    # -- santé --

    def _status(self, now: float) -> LoopStatus:
        if self._tick is None:
            return LoopStatus.NOT_IMPLEMENTED
        return LoopStatus.RUNNING            # événementielle : le silence n'est pas une panne

    def health(self, now: Optional[float] = None) -> LoopHealth:
        now = self._clock() if now is None else now
        age = None if self._beat_ts is None else now - self._beat_ts
        return LoopHealth(
            name=self.spec.name, status=self._status(now), cadence=self.spec.cadence,
            criticality=self.spec.criticality, starve=self.spec.starve,
            period_s=self.spec.period_s, last_beat_ts=self._beat_ts, age_s=age,
            ticks=self._ticks, failures=self._failures, timeouts=self._timeouts,
            drops=self._drops, last_error=self._last_error, purpose=self.spec.purpose)


class PeriodicLoop(ManagedLoop):
    """Boucle CADENCÉE. Possède sa tâche ; se démarre, s'arrête, et se surveille."""

    def __init__(self, spec: LoopSpec, tick: Optional[Callable[..., Any]] = None, *,
                 clock: Optional[Callable[[], float]] = None):
        if spec.cadence is not Cadence.PERIODIC:
            raise ValueError(f"{spec.name}: PeriodicLoop exige une spec PERIODIC")
        super().__init__(spec, tick, clock=clock)
        self._task: Optional[asyncio.Task] = None
        self._started_ts: Optional[float] = None

    async def start(self) -> None:
        """Idempotent tant que la boucle est VIVANTE. Mais une tâche morte — annulation
        externe, arrêt d'un TaskGroup — est `done()` sans être `None` : la garde naïve
        laisserait la boucle morte en silence (D-052 faille E). On la relance, et ça se voit."""
        if self._tick is None:
            return                                            # rien à cadencer, et on ne feint pas
        task = self._task
        if task is not None and not task.done():
            return
        if task is not None:
            log.warning("boucle %s était morte (%s) — relancée", self.spec.name,
                        _death_reason(task))
        self._started_ts = self._clock()
        self._task = asyncio.create_task(self._run(), name=f"loop:{self.spec.name}")

    async def stop(self) -> None:
        """Idempotent et NON propageant : `await task` re-lève l'exception d'une tâche déjà
        morte, ce qui faisait exploser l'arrêt gracieux au pire moment (RUNTIME_LOOPS Loop H)."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        if task is asyncio.current_task():
            # `stop()` appelé DEPUIS la boucle : s'attendre soi-même lève « Task cannot await
            # on itself ». L'annulation prendra effet au prochain point d'attente.
            return
        try:
            await task
        except asyncio.CancelledError:
            # Distinguer « la boucle s'est bien arrêtée » de « c'est MOI qu'on annule » :
            # pendant un shutdown, `await stop()` peut lui-même être annulé, et l'avaler ferait
            # croire à l'appelant que son arrêt s'est déroulé normalement.
            current = asyncio.current_task()
            if current is not None and current.cancelling() > 0:
                raise
        except Exception:
            log.exception("boucle %s était déjà morte avant stop()", self.spec.name)

    async def _run(self) -> None:
        """Cadence à l'ÉCHÉANCE sur l'horloge MONOTONE de la boucle (pas l'horloge murale, qui
        peut faire un pas NTP). Les créneaux manqués sont comptés puis ABANDONNÉS : les
        rejouer évaluerait le passé (D-045 T3)."""
        loop = asyncio.get_running_loop()
        period = float(self.spec.period_s)                    # validé > 0 par LoopSpec
        next_at = loop.time()
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Filet de dernier recours : `run_once` capture déjà tout, mais la boucle ne
                # doit JAMAIS mourir sur un imprévu (RUNTIME_LOOPS).
                log.exception("boucle %s : tick non capturé (fail-closed)", self.spec.name)
            next_at += period
            now = loop.time()
            if next_at <= now:
                missed = int((now - next_at) // period) + 1
                self._drops += missed                         # sauté ≠ invisible
                next_at = now                                 # réancrage, pas de rafale
                delay = 0.001                                 # mais on rend TOUJOURS la main
            else:
                delay = next_at - now
            await asyncio.sleep(delay)

    def _status(self, now: float) -> LoopStatus:
        if self._tick is None:
            return LoopStatus.NOT_IMPLEMENTED
        if self._task is None:
            return LoopStatus.STOPPED
        if self._task.done():
            return LoopStatus.DEAD
        stale = self.spec.heartbeat_stale_s
        # Référence de fraîcheur : le dernier tick RÉUSSI, ou à défaut le démarrage. La grâce
        # accordée à une boucle qui n'a pas encore produit son premier battement est BORNÉE par
        # le même seuil — sinon une boucle qui échoue à *chaque* tour resterait `RUNNING` pour
        # toujours (trouvée à l'essai manuel : `o5.kurtosis` en échec systématique passait pour
        # saine). C'est exactement la panne que ce module existe pour rendre visible.
        reference = self._beat_ts if self._beat_ts is not None else self._started_ts
        if reference is None:
            return LoopStatus.RUNNING                         # démarrée à l'instant, rien à dire
        if stale is not None and (now - reference) > stale:
            return LoopStatus.STALLED
        return LoopStatus.RUNNING


def _death_reason(task: "asyncio.Task") -> str:
    """Pourquoi la boucle est morte — lu SANS lever : `task.exception()` explose sur une tâche
    annulée. Le lire ici évite aussi le « exception was never retrieved » à la collecte."""
    if task.cancelled():
        return "cancelled"
    exc = task.exception()
    return repr(exc) if exc is not None else "returned"
