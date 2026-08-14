"""Comportement de la liquidité par niveau — icebergs et churn (D-106).

Affine `OF1` (rechargement du mur) et `OF2` en distinguant, sur un niveau donné, la liquidité qui
**se fait consommer** de celle qui **disparaît sans être touchée**. Les deux ressemblent à un mur
qui s'efface ; elles ne disent pas du tout la même chose d'un sweep.

Le carnet MBO suit déjà, par niveau et sur la session, `added_volume`, `cancelled_volume`,
`traded_volume` et désormais `peak_size`. Ce module ne mesure rien de neuf : il **dérive**.

---

**« Churn », pas « spoofing ».**

Le spoofing est une intention — placer pour tromper, sans intention d'exécuter. Une intention ne
s'observe pas dans un carnet. Ce qu'on observe est un **taux d'annulation élevé sur du volume
jamais exécuté**, ce qui a beaucoup de causes légitimes : market-making, couverture, retrait sur
mouvement de prix, algorithme de repositionnement.

Étiqueter un niveau `SPOOF` dans un terminal de trading serait présenter une accusation comme une
mesure — et un opérateur qui agit dessus agirait sur une inférence déguisée en fait. Le champ
s'appelle donc `churn`, et son libellé écran dit ce qu'il est : « annulé sans exécution ».

**`None` n'est pas `False`.** Un niveau sans volume ajouté n'est pas « vérifié sans iceberg » : il
est **non mesurable**. Rendre `False` ferait lire une absence de signal comme une absence de
phénomène (§3).

**Seuils PLACEHOLDER.** Aucun n'est calibré. Ils sont isolés ici, nommés, et le rapport porte les
valeurs qui l'ont produit — pour qu'une conclusion tirée d'eux reste rattachable à eux.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

#: Volume échangé ≥ N × le pic jamais affiché → réinjection masquée probable. PLACEHOLDER.
ICEBERG_TRADED_MULTIPLE = 3.0
#: Sous ce volume ajouté, le niveau est trop peu actif pour conclure quoi que ce soit.
MIN_ADDED_VOLUME = 20.0
#: Part annulée du volume ajouté. PLACEHOLDER — un market-maker normal annule beaucoup.
CHURN_CANCEL_RATIO = 0.85


@dataclass(frozen=True)
class LevelBehaviour:
    """Lecture d'un niveau. Chaque verdict est `True`, `False` ou `None` — jamais deux états."""

    price: float
    side: str
    added: float
    cancelled: float
    traded: float
    peak_size: float
    displayed: float
    cancel_ratio: Optional[float]
    fill_ratio: Optional[float]
    #: `traded / peak_size` — combien de fois le niveau a rejoué sa propre taille visible.
    refill_multiple: Optional[float]
    iceberg: Optional[bool]
    churn: Optional[bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price, "side": self.side,
            "added": self.added, "cancelled": self.cancelled, "traded": self.traded,
            "peak_size": self.peak_size, "displayed": self.displayed,
            "cancel_ratio": self.cancel_ratio, "fill_ratio": self.fill_ratio,
            "refill_multiple": self.refill_multiple,
            "iceberg": self.iceberg, "churn": self.churn,
        }


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    """`None` si le dénominateur est nul — un rapport sur rien n'est pas zéro."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def analyse_level(level: Any, side: str) -> Optional[LevelBehaviour]:
    """Dérive le comportement d'un `LevelState`. `None` si l'objet n'en est pas un."""
    try:
        price = float(level.price)
        added = float(level.added_volume)
        cancelled = float(level.cancelled_volume)
        traded = float(level.traded_volume)
        peak = float(getattr(level, "peak_size", 0.0))
        displayed = float(level.size)
    except (AttributeError, TypeError, ValueError):
        return None

    cancel_ratio = _ratio(cancelled, added)
    fill_ratio = _ratio(traded, added)
    refill = _ratio(traded, peak)

    # Sous le plancher d'activité, on ne conclut RIEN — ni iceberg ni churn. Deux ordres posés
    # puis retirés donneraient un taux d'annulation de 100 % qui ne décrit que deux ordres.
    assez = added >= MIN_ADDED_VOLUME
    iceberg = (refill is not None and refill >= ICEBERG_TRADED_MULTIPLE) if (assez and refill is not None) else None
    churn = (cancel_ratio >= CHURN_CANCEL_RATIO and traded <= 0) if (assez and cancel_ratio is not None) else None

    return LevelBehaviour(
        price=price, side=side, added=added, cancelled=cancelled, traded=traded,
        peak_size=peak, displayed=displayed, cancel_ratio=cancel_ratio,
        fill_ratio=fill_ratio, refill_multiple=refill, iceberg=iceberg, churn=churn)


def analyse_book(book: Any, *, max_levels: int = 10) -> dict[str, Any]:
    """Comportement des niveaux les plus proches du marché, des deux côtés.

    Ne lève jamais : un carnet inexploitable rend un rapport vide plutôt qu'une exception qui
    remonterait dans la boucle d'armement (le mode consultatif ne bloque rien — `COMMANDS §2`).
    """
    thresholds = {"iceberg_traded_multiple": ICEBERG_TRADED_MULTIPLE,
                  "min_added_volume": MIN_ADDED_VOLUME,
                  "churn_cancel_ratio": CHURN_CANCEL_RATIO,
                  "calibrated": False}
    out: dict[str, Any] = {"bids": [], "asks": [], "thresholds": thresholds}
    try:
        for side, cle in (("B", "bids"), ("A", "asks")):
            levels = _closest_levels(book, side, max_levels)
            out[cle] = [b.to_dict() for b in
                        (analyse_level(lv, side) for lv in levels) if b is not None]
    except Exception:                                   # noqa: BLE001 — observation, pas décision
        return {"bids": [], "asks": [], "thresholds": thresholds,
                "error": "carnet inexploitable"}
    return out


def _closest_levels(book: Any, side: str, limit: int) -> list[Any]:
    """Niveaux triés du plus proche du marché vers le plus loin. Un carnet sans le côté demandé
    rend une liste vide — pas une exception."""
    mapping = getattr(book, "_bids" if side == "B" else "_asks", None)
    if not isinstance(mapping, dict) or not mapping:
        return []
    # Côté BID le meilleur est le prix le plus HAUT, côté ASK le plus BAS.
    keys = sorted(mapping.keys(), reverse=(side == "B"))
    return [mapping[k] for k in keys[:limit]]


def summarise(report: dict[str, Any]) -> str:
    """Ligne lisible en tête. Un dict de nombres n'est pas un message (/polish)."""
    icebergs = [lv for cote in ("bids", "asks") for lv in report.get(cote, []) if lv.get("iceberg")]
    churns = [lv for cote in ("bids", "asks") for lv in report.get(cote, []) if lv.get("churn")]
    if report.get("error"):
        return "comportement de liquidité non mesurable"
    if not icebergs and not churns:
        return "aucun niveau ne se distingue (ou activité insuffisante pour conclure)"
    morceaux = []
    if icebergs:
        morceaux.append(f"{len(icebergs)} niveau(x) à réinjection masquée")
    if churns:
        morceaux.append(f"{len(churns)} niveau(x) annulé(s) sans exécution")
    return " · ".join(morceaux) + " — seuils NON calibrés"
