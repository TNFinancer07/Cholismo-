"""Détecteur de vide de liquidité (D-111).

Mesure la **densité du carnet** sur les N niveaux les plus proches et signale son effondrement.
Un carnet qui se vide annonce un élargissement du spread : entrer au marché à cet instant fait
payer un slippage que la carte de résilience chiffre en points de taux de réussite.

**Ce module n'empêche rien** (mode G2). Il observe et publie ; l'entrée reste une décision.

---

**Densité par rapport à QUOI.** Une profondeur « faible » n'a de sens que comparée à ce que ce
carnet montre habituellement. On garde donc une **référence glissante** de la profondeur observée,
et le vide se mesure comme une chute relative à cette référence — pas contre un nombre absolu, qui
ne voudrait rien dire entre MES et MNQ, ni entre 09h30 et 14h.

**Fail-closed.** Sans référence suffisante, le verdict est `None` — « non mesurable », jamais
« carnet sain ». Un détecteur qui répond « tout va bien » parce qu'il vient de démarrer serait
pire que pas de détecteur.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Optional

#: Chute de profondeur au-delà de laquelle on lève le drapeau. PLACEHOLDER — non calibré.
VACUUM_DROP_RATIO = 0.70
#: Nombre de niveaux pris en compte de chaque côté.
DEPTH_LEVELS = 10
#: Observations nécessaires avant de pouvoir conclure. Sous ce seuil : `None`.
MIN_OBSERVATIONS = 20
#: Taille de la fenêtre glissante de référence.
REFERENCE_WINDOW = 200


def _side_depth(levels: Any, limit: int) -> Optional[float]:
    """Somme des tailles sur `limit` niveaux. `None` si le côté est illisible — un carnet
    partiellement lisible ne doit pas produire une profondeur qui a l'air complète."""
    if not isinstance(levels, list) or not levels:
        return None
    total = 0.0
    vus = 0
    for lvl in levels[:limit]:
        size = None
        if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
            size = lvl[1]
        elif isinstance(lvl, dict):
            size = lvl.get("size")
        try:
            f = float(size)
        except (TypeError, ValueError):
            continue
        if f == f and f >= 0:
            total += f
            vus += 1
    return total if vus else None


def book_depth(book: Any, *, levels: int = DEPTH_LEVELS) -> Optional[float]:
    """Profondeur totale des deux côtés. `None` dès qu'un côté manque : une profondeur calculée
    sur un seul côté sous-estimerait de moitié et se lirait comme un vide."""
    if not isinstance(book, dict):
        return None
    bid = _side_depth(book.get("bids"), levels)
    ask = _side_depth(book.get("asks"), levels)
    if bid is None or ask is None:
        return None
    return bid + ask


class VacuumDetector:
    """Suit la profondeur et signale son effondrement relatif à une référence glissante."""

    def __init__(self, *, levels: int = DEPTH_LEVELS, drop_ratio: float = VACUUM_DROP_RATIO,
                 min_observations: int = MIN_OBSERVATIONS,
                 window: int = REFERENCE_WINDOW) -> None:
        self._levels = max(1, levels)
        self._drop = drop_ratio
        self._min = max(1, min_observations)
        self._history: deque[float] = deque(maxlen=max(2, window))

    def observe(self, book: Any) -> dict[str, Any]:
        """Enregistre une profondeur et rend le verdict courant.

        Une profondeur illisible n'entre PAS dans la référence : l'y mettre à zéro ferait chuter
        la médiane et déclencherait un faux vide au tick suivant.
        """
        depth = book_depth(book, levels=self._levels)
        if depth is not None:
            self._history.append(depth)
        return self.verdict(depth)

    def reference(self) -> Optional[float]:
        """Médiane de la fenêtre — pas la moyenne : un seul mur énorme la tirerait, et le vide
        semblerait permanent après son retrait."""
        if len(self._history) < self._min:
            return None
        ordonne = sorted(self._history)
        n = len(ordonne)
        milieu = n // 2
        return ordonne[milieu] if n % 2 else (ordonne[milieu - 1] + ordonne[milieu]) / 2.0

    def verdict(self, depth: Optional[float]) -> dict[str, Any]:
        ref = self.reference()
        base = {"depth": depth, "reference": ref, "levels": self._levels,
                "observations": len(self._history), "min_observations": self._min,
                "drop_ratio_threshold": self._drop, "calibrated": False}
        if depth is None:
            return {**base, "vacuum": None, "drop_ratio": None,
                    "detail": "profondeur non mesurable — carnet absent ou illisible"}
        if ref is None or ref <= 0:
            return {**base, "vacuum": None, "drop_ratio": None,
                    "detail": (f"référence insuffisante ({len(self._history)}/{self._min} "
                               "observations) — « non mesurable », pas « carnet sain »")}
        drop = round(1.0 - (depth / ref), 4)
        vide = drop >= self._drop
        return {**base, "vacuum": vide, "drop_ratio": drop,
                "detail": (f"profondeur à {round(depth / ref * 100, 1)} % de sa référence"
                           + (" — SLIPPAGE ACCRU probable au marché" if vide else ""))}
