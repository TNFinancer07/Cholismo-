"""Détecteur de balayage MICROSTRUCTUREL PUR (D-087, phase P2).

Corrige une **erreur de catégorie** de D-083 : j'utilisais `SWEEP_GRAPH` comme déclencheur
d'armement LSR. Or ce graphe définit un sweep comme

    « anomalie microstructure **COUPLÉE à une news Tier-1 imminente** » (±30 min)

et sa propre docstring précise qu'il n'émet **qu'une alerte** à afficher, jamais un ordre. Deux
notions portent le même mot sans désigner la même chose :

| | `SWEEP_GRAPH` (D-028) | LSR — Liquidity Sweep **Reversion** |
|---|---|---|
| Objet | alerte « la liquidité s'évapore autour d'une publication » | événement de microstructure exploitable |
| News | **prérequis de déclenchement** (ET) | **filtre de blocage** (F0/F5), en aval |
| Sortie | affichage / scoring async | armement d'un setup |

Conséquence de l'erreur : le rejeu n'aurait mesuré que les balayages survenus à ±30 min d'une
news Tier-1 — pas la population de setups LSR. Arbitré par l'opérateur : **le déclencheur est
microstructurel pur, la news reste un filtre en aval.**

---

**Les seuils sont IMPORTÉS de `liquidity_sweep`, jamais recopiés.** Les deux détecteurs
regardent la même microstructure ; en dupliquer les constantes garantirait qu'elles divergent
au premier ajustement.

**La direction se déduit du côté CONSOMMÉ.** Un balayage qui mange les bids est un `BID_SWEEP`,
et le LSR y cherche une réversion **acheteuse** (`is_long = sweep_direction == "BID_SWEEP"`).
Se tromper de sens inverserait tous les trades du rejeu sans qu'aucun test d'usage ne tombe —
c'est pourquoi elle se lit sur le passif consommé, résolu par le carnet (D-079/D-086), et
jamais sur un drapeau.

**Fail-closed (§3).** Sans micro évaluable — ni carnet, ni tape — on ne tranche pas : `data_ok`
reste faux et aucune alerte n'est émise. On ne confond jamais « pas de balayage » et « je ne
peux pas savoir ». En revanche, contrairement à `SWEEP_GRAPH`, **l'absence de calendrier ne
bloque plus la détection** : elle bloquera la décision, en aval, là où c'est sa place.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

# Seuils IMPORTÉS — source unique de vérité de la microstructure (voir docstring).
from ..graph.liquidity_sweep import (
    BURST_COUNT_THRESHOLD, BURST_WINDOW_S, SPREAD_TICKS_THRESHOLD, TICK_SIZE,
)


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class MicroSweep:
    """Un balayage observé. `direction` suit la convention du moteur : `BID_SWEEP` = les bids
    ont été consommés → le LSR y cherche une réversion acheteuse."""
    ts: float
    direction: str                       # BID_SWEEP | ASK_SWEEP
    labels: tuple[str, ...]              # TAPE_BURST, WIDE_SPREAD, CROSSED_BOOK
    burst_count: int
    spread_ticks: Optional[float]
    delta_volume: float

    def as_alert(self) -> dict[str, Any]:
        return {"ts": self.ts, "direction": self.direction,
                "reason": "+".join(self.labels), "burst_count": self.burst_count,
                "spread_ticks": self.spread_ticks, "delta_volume": self.delta_volume}


@dataclass(frozen=True)
class MicroSweepResult:
    """`data_ok=False` = « impossible à évaluer », distinct de « pas de balayage » — un
    détecteur honnête ne confond pas les deux (doctrine reprise de `SWEEP_GRAPH`)."""
    data_ok: bool
    sweep: Optional[MicroSweep]
    reason: str


def _spread_labels(spread_ticks: Optional[float]) -> tuple[str, ...]:
    """Mêmes deux anomalies que `SWEEP_GRAPH` : carnet anormalement large, ou croisé."""
    if not _finite(spread_ticks):
        return ()
    if spread_ticks > SPREAD_TICKS_THRESHOLD:
        return ("WIDE_SPREAD",)
    if spread_ticks <= 0:
        return ("CROSSED_BOOK",)
    return ()


def detect(prints: Any, *, now: float, spread_ticks: Optional[float] = None,
           burst_window_s: float = BURST_WINDOW_S,
           burst_count: int = BURST_COUNT_THRESHOLD) -> MicroSweepResult:
    """Détecte un balayage sur la fenêtre `[now − burst_window_s, now]`.

    `prints` suit la convention du tape (plus récent en tête) : `{ts, price, size, side}`, où
    `side` est l'**agresseur**. Ne lève jamais.
    """
    if not _finite(now):
        return MicroSweepResult(False, None, "horloge non exploitable")

    usable = isinstance(prints, list)
    window = []
    if usable:
        for entry in prints:
            if not isinstance(entry, dict):
                continue
            ts, size, side = entry.get("ts"), entry.get("size"), entry.get("side")
            if not _finite(ts) or not _finite(size) or side not in ("BUY", "SELL"):
                continue
            if 0 <= now - ts <= burst_window_s:
                window.append((float(ts), float(size), side))

    has_spread = _finite(spread_ticks)
    if not window and not has_spread:
        # Ni tape ni carnet : on ne peut pas trancher. Fail-closed, et on le DIT.
        return MicroSweepResult(False, None,
                                "micro inévaluable (ni tape ni carnet) — aucune alerte inventée")

    labels: list[str] = []
    if len(window) >= burst_count:
        labels.append("TAPE_BURST")
    labels.extend(_spread_labels(spread_ticks))
    if not labels:
        # État CONNU : la micro était évaluable, il n'y a simplement pas de balayage.
        return MicroSweepResult(True, None, "aucune anomalie microstructure")

    # Delta agresseur net : positif = acheteurs dominants (ils mangent l'ASK), négatif =
    # vendeurs dominants (ils mangent le BID).
    delta = sum(size if side == "BUY" else -size for _, size, side in window)
    if delta == 0:
        # Anomalie réelle mais sans côté dominant : le sens de la réversion serait un tirage au
        # sort, et un sens inversé retourne tous les trades du rejeu (§3).
        return MicroSweepResult(True, None,
                                "anomalie sans côté dominant — direction indéterminable")

    # Vendeurs dominants → les BIDS ont été consommés → BID_SWEEP → réversion acheteuse.
    direction = "BID_SWEEP" if delta < 0 else "ASK_SWEEP"
    return MicroSweepResult(
        True,
        MicroSweep(ts=now, direction=direction, labels=tuple(labels),
                   burst_count=len(window),
                   spread_ticks=float(spread_ticks) if has_spread else None,
                   delta_volume=delta),
        "balayage détecté : " + "+".join(labels))


def spread_ticks_from_book(book: Any, tick: float = TICK_SIZE) -> Optional[float]:
    """Spread en ticks depuis un carnet agrégé `{bids, asks}`. `None` si un côté manque — un
    spread calculé sur une moitié de marché n'est pas un spread."""
    if not isinstance(book, dict):
        return None
    bids, asks = book.get("bids"), book.get("asks")
    if not bids or not asks:
        return None
    try:
        spread = (float(asks[0][0]) - float(bids[0][0])) / tick
    except (TypeError, ValueError, IndexError):
        return None
    return spread if math.isfinite(spread) else None
