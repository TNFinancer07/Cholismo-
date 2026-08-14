"""Contrat commun des boucles d'exécution du terminal (D-073).

Un seul gabarit — hérité des parades de D-052 — pour toutes les boucles, et une projection de
santé qui rend visible l'échec que ce module existe pour empêcher : **une boucle morte
ressemble à une boucle calme**.

Voir `contract.py` pour les parades, `registry.py` pour les cinq boucles déclarées.
"""
from .contract import (
    Cadence, Criticality, LoopHealth, LoopSpec, LoopStatus, ManagedLoop, PeriodicLoop,
    StarvePolicy,
)
from .health import is_healthy, project, to_dict
from .registry import (
    CORE_TICK, GATES_EVAL, O5_KURTOSIS, OPTIONS_SYNC, UI_BROADCAST, default_specs,
)
from .supervisor import LoopSupervisor

__all__ = [
    "Cadence", "Criticality", "LoopHealth", "LoopSpec", "LoopStatus", "ManagedLoop",
    "PeriodicLoop", "StarvePolicy",
    "is_healthy", "project", "to_dict",
    "CORE_TICK", "GATES_EVAL", "O5_KURTOSIS", "OPTIONS_SYNC", "UI_BROADCAST", "default_specs",
    "LoopSupervisor",
]
