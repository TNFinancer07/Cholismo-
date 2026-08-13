"""Câblage des boucles réellement branchées (D-075).

`registry.py` DÉCLARE les cinq boucles ; ce module en câble **deux** — `options.sync` (L2) et
`ui.broadcast` (L5). Les trois autres restent `NOT_IMPLEMENTED`, donc visibles comme telles
dans la projection de santé : une capacité annoncée et absente n'est pas un état neutre.

**Pourquoi le tick de L2 publie même quand il échoue.** Le rafraîchissement lève sur panne (afin
que la boucle compte l'échec, cf. `options_context`), mais la publication est dans un `finally` :
sans elle, une source qui tombe laisserait l'UI sur le dernier contexte reçu, **figé et d'allure
fraîche**. C'est exactement l'inverse du but. La projection est calculée depuis l'âge du cache,
donc elle bascule d'elle-même en `STALE` puis le dit. L'échec, lui, remonte quand même.

**Pourquoi la santé des boucles n'est pas publiée à chaque tick.** À 0,25 s, ce serait 4
messages/s dont le contenu ne change quasiment jamais. On publie sur **changement d'état**
(RUNTIME_LOOPS Loop B, *dirty flag*), plus un rappel périodique pour que l'âge affiché ne se
fige pas entre deux changements.

**Limite connue et assumée** : c'est `ui.broadcast` qui publie la santé. Si elle meurt, la santé
cesse d'être poussée — le client le voit au silence du canal, pas par un message. Un watchdog
externe (Loop G) est le vrai remède ; il n'est pas dans cette tranche.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from .registry import CORE_TICK, GATES_EVAL, O5_KURTOSIS, OPTIONS_SYNC, UI_BROADCAST
from .supervisor import LoopSupervisor

#: Rappel périodique de la santé même sans changement d'état, pour que l'âge affiché côté client
#: ne se fige pas. PLACEHOLDER — compromis lisibilité/bruit, pas une valeur mesurée.
HEALTH_REPUBLISH_SECONDS = 2.0


def _fingerprint(snapshot: dict[str, Any]) -> str:
    """Ce qui constitue un CHANGEMENT d'état. Volontairement sans les âges ni les compteurs de
    ticks : ils bougent à chaque tour, et les inclure reviendrait à publier en continu — donc à
    n'avoir aucun *dirty flag* du tout."""
    return json.dumps([[e["name"], e["status"], e["failures"], e["timeouts"], e["drops"] > 0]
                       for e in snapshot["loops"]], sort_keys=True)


def build_supervisor(reader: Any, broadcaster: Any, *,
                     clock: Optional[Callable[[], float]] = None) -> LoopSupervisor:
    """Monte le superviseur avec L2 et L5 câblées. `reader` est un `OptionsContextReader`."""
    now = clock or time.time
    sup = LoopSupervisor(clock=now)
    state: dict[str, Any] = {"fingerprint": None, "last_publish": 0.0}

    async def options_tick() -> None:
        try:
            await reader.refresh()
        finally:
            # TOUJOURS publier l'état honnête du contexte — y compris (surtout) quand il vient
            # de se dégrader. Sans ce `finally`, une source morte laisserait le dernier contexte
            # affiché comme s'il était frais.
            broadcaster.publish("options", "options_context", reader.to_event(now()))

    async def broadcast_tick() -> None:
        snapshot = sup.health(now())
        fingerprint = _fingerprint(snapshot)
        elapsed = now() - state["last_publish"]
        if fingerprint == state["fingerprint"] and elapsed < HEALTH_REPUBLISH_SECONDS:
            return
        state["fingerprint"] = fingerprint
        state["last_publish"] = now()
        # `replay=False` : la santé est DATÉE. La rejouer pour hydrater un abonné neuf lui
        # servirait un âge d'avant sa connexion — un état, ça se rejoue ; une mesure, non.
        broadcaster.publish("options", "loops_health", snapshot, replay=False)

    sup.register(CORE_TICK)                       # déjà assurée par engine.py — migration = refactor
    sup.register(OPTIONS_SYNC, options_tick)
    sup.register(O5_KURTOSIS)                     # arrive avec le port O5 (P2)
    sup.register(GATES_EVAL)                      # arrive avec le port O1-O4 (P2)
    sup.register(UI_BROADCAST, broadcast_tick)
    return sup
