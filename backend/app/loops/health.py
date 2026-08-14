"""Projection de la santé des boucles (D-073).

C'est le point du module. `CLAUDE §3` — « no signal without data » — s'applique aussi aux
boucles : une boucle O5 morte doit s'afficher comme telle, au lieu de laisser un kurtosis figé
passer pour frais. La projection est un dict **sérialisable tel quel**, destiné au 3ᵉ canal SSE
`options` (arbitrage transport : SSE conservé, pas de WebSocket — voir D-074).

Aucune valeur n'est fabriquée : une boucle qui n'a jamais battu porte `last_beat_ts: null` et
`age_s: null`, jamais un `0` qui se lirait « à jour ».
"""
from __future__ import annotations

from typing import Iterable, Optional

from .contract import Criticality, LoopHealth, LoopStatus

#: Seul `RUNNING` est sain. `NOT_IMPLEMENTED` en fait partie **exprès** : une boucle déclarée
#: mais non câblée n'est pas un état neutre, c'est une capacité annoncée et absente. La faire
#: passer pour saine reproduirait exactement le « stub qui feint de fonctionner » que les
#: règles d'ingénierie interdisent.
_HEALTHY = (LoopStatus.RUNNING,)


def is_healthy(health: LoopHealth) -> bool:
    return health.status in _HEALTHY


def to_dict(health: LoopHealth) -> dict:
    """Une boucle, en JSON. Les enums sortent en texte (elles héritent de `str`), les mesures
    absentes en `None`."""
    return {
        "name": health.name,
        "status": health.status.value,
        "cadence": health.cadence.value,
        "criticality": health.criticality.value,
        "starve": health.starve.value,
        "period_s": health.period_s,
        "last_beat_ts": health.last_beat_ts,
        "age_s": health.age_s,
        "ticks": health.ticks,
        "failures": health.failures,
        "timeouts": health.timeouts,
        "drops": health.drops,
        "last_error": health.last_error,
        "purpose": health.purpose,
    }


def project(healths: Iterable[LoopHealth], now: Optional[float] = None) -> dict:
    """Photo de l'ensemble des boucles. `unhealthy` liste les noms plutôt qu'un simple booléen :
    « quelque chose ne va pas » n'est pas actionnable, « o5.kurtosis est STALLED » l'est."""
    entries = [to_dict(h) for h in healths]
    unhealthy = [h["name"] for h in entries if h["status"] not in
                 {status.value for status in _HEALTHY}]
    # `unhealthy` melange deux choses tres differentes : une boucle DÉCLARÉE-non-câblée
    # (attendu, on sait pourquoi) et une boucle câblée qui MEURT (anormal, il faut agir).
    # Un opérateur réveillé à 3 h a besoin de cette distinction avant toute autre (D-091).
    expected = [e["name"] for e in entries if e["status"] == LoopStatus.NOT_IMPLEMENTED.value]
    broken = [e["name"] for e in entries
              if e["status"] in (LoopStatus.STALLED.value, LoopStatus.DEAD.value)]
    stopped = [e["name"] for e in entries if e["status"] == LoopStatus.STOPPED.value]
    # Le chemin CHAUD a un statut à part : une boucle HOT cassée, c'est le hot path lui-même
    # qui ne tourne plus. Le noyer dans une liste globale le rendrait invisible.
    hot_broken = [e["name"] for e in entries
                  if e["criticality"] == Criticality.HOT.value
                  and e["status"] not in {status.value for status in _HEALTHY}]
    return {
        "generated_at": now,
        "loops": entries,
        "all_healthy": not unhealthy,
        "unhealthy": unhealthy,
        # --- lecture OPÉRATIONNELLE (D-091) ---
        "degraded": {
            # `broken` seul déclenche une intervention. `expected` documente, il n'alerte pas.
            "broken": broken,
            "stopped": stopped,
            "expected": expected,
            "hot_path_broken": hot_broken,
            # Un mot unique pour la barre de statut et pour la supervision externe.
            "verdict": ("HOT_PATH_DOWN" if hot_broken else
                        "DEGRADED" if broken or stopped else
                        "PARTIAL" if expected else "NOMINAL"),
        },
    }
