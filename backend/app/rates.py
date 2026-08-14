"""Courbe des taux et différentiels — bloc `yield_curve` (D-053, canal LENT).

Module **pur** (aucune horloge, aucune I/O) qui normalise des taux BRUTS en une courbe
affichable. Deux règles gouvernent tout :

1. **Un spread ne se calcule jamais à partir d'un trou.** Un ténor absent, non fini ou
   invraisemblable fait disparaître *tous* les spreads qui en dépendent — et seulement ceux-là.
   Un différentiel affiché sur une patte manquante serait un chiffre inventé qui a l'air d'une
   mesure : la pire forme de mensonge dans un terminal (§3).
2. **Les spreads sont DÉRIVÉS, jamais alimentés.** Recevoir la pente d'une source indépendante
   ouvrirait la porte à une contradiction entre le spread affiché et les taux affichés
   juste au-dessus. Une seule source de vérité : les ténors.

`inverted` n'est renseigné que pour une **pente** (deux ténors de la même courbe) : un
différentiel transatlantique négatif n'est pas une « inversion », l'étiquette serait un
contresens. C'est un FAIT observable, pas une prévision de récession — le panneau montre,
l'opérateur décide (§2.1).

Bornes de plausibilité : un taux à 900 % ou −50 % est une erreur d'unité ou de parsing, pas un
régime de marché. La borne écarte l'absurde, **pas l'inhabituel** — un Bund à −0,55 % est réel
et doit passer.
"""
from __future__ import annotations

import math
from typing import Any, Optional

# Ordre d'affichage = ordre de la courbe (court → long, US puis DE).
TENORS: tuple[tuple[str, str], ...] = (
    ("US02Y", "US 2 ans"),
    ("US10Y", "US 10 ans"),
    ("DE02Y", "Bund 2 ans"),
    ("DE10Y", "Bund 10 ans"),
)

# `slope` : deux ténors de la MÊME courbe → l'inversion a un sens.
SPREADS: tuple[dict, ...] = (
    {"code": "US10Y-US02Y", "label": "Pente US 10a−2a", "long": "US10Y", "short": "US02Y",
     "slope": True},
    {"code": "US10Y-DE10Y", "label": "Différentiel US−DE 10a", "long": "US10Y", "short": "DE10Y",
     "slope": False},
)

_MIN_PCT, _MAX_PCT = -5.0, 25.0        # bornes de plausibilité (écartent l'absurde, pas l'inhabituel)


def _rate(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x) if _MIN_PCT <= x <= _MAX_PCT else None


def _change(x: Any) -> Optional[float]:
    """Variation en points de base. `None` reste `None` : 0 bp signifie « inchangé », ce qui est
    une information — l'absence de mesure n'en est pas une."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return round(float(x), 1)


def build_yield_curve(raw: Any) -> Optional[dict]:
    """Normalise `{tenors: {CODE: pct}, changes_bp: {CODE: bp}}` en
    `{tenors: [...], spreads: [...]}`. Rend `None` si aucun ténor n'est exploitable — un objet
    vide s'afficherait comme « connecté », ce qui est plus trompeur qu'un bloc franchement ABSENT.
    """
    if not isinstance(raw, dict):
        return None
    source = raw.get("tenors")
    if not isinstance(source, dict) or not source:
        return None
    changes = raw.get("changes_bp") if isinstance(raw.get("changes_bp"), dict) else {}

    values: dict[str, float] = {}
    tenors: list[dict] = []
    for code, label in TENORS:                       # ténors INCONNUS ignorés (jamais affichés)
        value = _rate(source.get(code))
        if value is None:
            continue
        values[code] = value
        tenors.append({"code": code, "label": label, "value_pct": round(value, 3),
                       "change_bp": _change(changes.get(code))})
    if not tenors:
        return None

    spreads = []
    for spec in SPREADS:
        long_v, short_v = values.get(spec["long"]), values.get(spec["short"])
        if long_v is None or short_v is None:
            continue                                 # patte manquante → le spread DISPARAÎT
        value_bp = round((long_v - short_v) * 100.0, 1)
        spreads.append({
            "code": spec["code"], "label": spec["label"], "value_bp": value_bp,
            "long": spec["long"], "short": spec["short"],
            # `None` hors pente : « inversé » n'a pas de sens sur un différentiel inter-pays.
            "inverted": (value_bp < 0) if spec["slope"] else None,
        })
    return {"tenors": tenors, "spreads": spreads}
