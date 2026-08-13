"""Barres ES 1 min pour O5 (D-077).

O5 consomme des barres `{timestamp, close}` sur une fenêtre de 121 barres — deux heures. Rien
ne les produisait : le footprint agrège bien par bougie, mais son tampon est borné à
`FOOTPRINT_MAX_PRINTS` prints, de quoi couvrir quelques minutes. **Une fenêtre de deux heures ne
se reconstruit pas depuis un tampon de prints ; elle s'accumule.** D'où cet agrégateur, qui
échantillonne le dernier print observé et clôt une barre à chaque frontière de minute.

**Trois choix qui ne sont pas cosmétiques :**

1. **La largeur de barre est INDÉPENDANTE de `FOOTPRINT_CANDLE_SECONDS`.** Ce réglage pilote un
   affichage, et peut basculer en mode tick (`FOOTPRINT_TICKS_PER_CANDLE`). Adosser une mesure
   de risque à un réglage d'affichage, c'est accepter qu'un changement de vue modifie le
   kurtosis sans que personne ne fasse le lien. `O5_BAR_PERIOD_SECONDS` lui appartient en propre.
2. **Seules les barres CLOSES entrent dans le tampon.** La bougie en formation a une clôture
   mouvante ; `push_bar` rejetant les doublons d'horodatage, la première valeur partielle serait
   **gelée** comme clôture définitive de la minute.
3. **Tape non FRESH → aucune observation.** Répéter le dernier prix connu fabriquerait des
   rendements nuls : une série calme *inventée*, donc un kurtosis rassurant sur des données qui
   n'existent pas. Fail-closed (§3) — et un trou reste un trou, c'est à `has_temporal_gap` de le
   voir, pas à nous de le combler.

Observation seule (§2.1) : ce module lit des prints déjà passés, il n'émet rien.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from . import config
from .o5_tail_risk import push_bar


class EsBarsUnavailable(Exception):
    """Aucun prix exploitable. Levée par le tick L3 pour que la boucle COMPTE l'échec : sans
    elle, L3 battrait `RUNNING` en n'observant rien — le mensonge que D-073 empêche."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def last_trade_price(tape_field: Any) -> Optional[float]:
    """Dernier prix traité, lu en tête du tape (plus récent en tête, D-026). Rend `None` sur
    tout ce qui n'est pas une mesure fraîche — jamais un prix relayé d'un tape périmé."""
    if not isinstance(tape_field, dict):
        return None
    freshness = tape_field.get("freshness")
    freshness = getattr(freshness, "value", freshness)
    if freshness != "FRESH":
        return None
    prints = tape_field.get("value")
    if not isinstance(prints, list) or not prints:
        return None
    head = prints[0]
    if not isinstance(head, dict):
        return None
    price = head.get("price")
    # Un prix nul ou négatif n'est pas un prix : `to_log_returns` en ferait un `nan`, et O5
    # traiterait toute la fenêtre comme invalide. Autant le refuser à la source.
    if not _finite(price) or price <= 0:
        return None
    return float(price)


class EsBarAggregator:
    """Synthétise des barres 1 min à partir d'échantillons de prix. État injecté, pas d'horloge
    propre : `observe` reçoit son `ts`, ce qui rend le rejeu déterministe."""

    def __init__(self, *, bar_seconds: Optional[float] = None,
                 max_bars: Optional[int] = None):
        self._bar_s = float(bar_seconds if bar_seconds is not None
                            else config.O5_BAR_PERIOD_SECONDS)
        # Borné à la fenêtre utile : sans cela, une séance de 8 h accumulerait 480 barres pour
        # une fenêtre qui en lit 121 — une fuite lente (piège RUNTIME_LOOPS Loop D).
        self._max_bars = int(max_bars if max_bars is not None
                             else config.O5_BAR_BUFFER_SIZE)
        self._bars: tuple = ()
        self._bucket: Optional[float] = None
        self._last_price: Optional[float] = None

    @property
    def bars(self) -> tuple:
        return self._bars

    def observe(self, price: Any, ts: Any) -> bool:
        """Enregistre un échantillon. Rend `True` si une barre vient de CLORE (seul moment où
        un recalcul O5 a du sens). Ne lève jamais : les prix viennent d'un feed."""
        if not _finite(price) or price <= 0 or not _finite(ts):
            return False
        bucket = math.floor(float(ts) / self._bar_s) * self._bar_s

        if self._bucket is None:
            self._bucket, self._last_price = bucket, float(price)
            return False
        if bucket == self._bucket:
            self._last_price = float(price)
            return False
        if bucket < self._bucket:
            # Horloge qui recule (pas NTP arrière) : on ne réécrit pas le passé. La barre
            # antérieure serait de toute façon rejetée par `push_bar`, mais mieux vaut ne pas
            # non plus corrompre le bucket en cours.
            return False

        # Frontière franchie : la minute précédente est close sur son dernier prix observé.
        closed = self._close_bucket()
        self._bucket, self._last_price = bucket, float(price)
        return closed

    def _close_bucket(self) -> bool:
        if self._bucket is None or self._last_price is None:
            return False
        bar = {
            # Horodatage en MILLISECONDES et à la FIN du bucket : O5 raisonne en ms
            # (`max_bar_gap_ms`), et mélanger les unités ferait passer chaque barre pour un
            # trou temporel.
            "timestamp": (self._bucket + self._bar_s) * 1000.0,
            "close": self._last_price,
        }
        # On passe par `push_bar` plutôt que d'ajouter nous-mêmes : c'est lui qui porte le rejet
        # des doublons et de l'hors-ordre. Contourner la protection ici la rendrait décorative.
        self._bars, accepted, _ = push_bar(self._bars, bar, self._max_bars)
        return accepted
