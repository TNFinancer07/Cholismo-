"""Positionnement Long/Short agrégé — bloc `long_short_ratio` (D-053, canal LENT).

Ce module **ne produit aucun signal**. Il normalise un flux de positionnement brut (venue retail
type SSI, ou COT hebdomadaire) en une valeur affichable, et **refuse** tout ce qui n'est pas
exploitable : le panneau montre la donnée, l'opérateur décide (§2.1). Aucune lecture d'un
contrarien, d'un « sentiment extrême = signal » ou d'une pondération — ce serait de la logique
métier inventée (§11 : en cas de doute, PLACEHOLDER).

Trois refus assumés, tous vérifiés par test :

1. **Des pourcentages qui ne totalisent pas 100** signifient qu'une catégorie a été perdue par la
   venue. Afficher la jauge reviendrait à **inventer la part manquante** — la ligne sort, et
   l'écart est COMPTÉ (`dropped`) pour rester visible à l'écran.
2. **Un short à 0** rend le ratio infini. Les pourcentages, eux, restent une donnée réelle : on
   garde la jauge et on retire le ratio. Jamais « ∞ », jamais un nombre géant.
3. **Un flux obèse est un flux empoisonné** (doctrine D-050) : au-delà de `SENTIMENT_MAX_ROWS`,
   on refuse le lot ENTIER. Tronquer masquerait des instruments sans le dire.

Le module est **pur** : aucune lecture d'horloge, aucune I/O, `now` n'est même pas nécessaire —
la fraîcheur est portée par le `MetaField` qui l'enveloppe (§3).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from . import config

# Arrondis de venue : 59,7 + 40,2 = 99,9. Au-delà, c'est une catégorie perdue, pas un arrondi.
_SUM_TOLERANCE_PCT = 0.5


def _pct(x: Any) -> Optional[float]:
    """Un pourcentage exploitable : fini et dans [0, 100]. `True` n'est pas 1 %."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x) if 0.0 <= x <= 100.0 else None


def _optional_finite(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return round(float(x), 2)


def build_long_short(raw: Any, *, extreme_pct: Optional[float] = None,
                     max_rows: Optional[int] = None) -> Optional[dict]:
    """Normalise `{venue, rows: [...]}` en `{venue, instruments: [...], dropped: n}`.

    Rend `None` dès que **rien** n'est exploitable : un objet à zéro instrument s'afficherait
    comme « connecté mais vide », ce qui est plus trompeur qu'un bloc franchement ABSENT.
    """
    threshold = extreme_pct if extreme_pct is not None else config.SENTIMENT_EXTREME_PCT
    cap = max_rows if max_rows is not None else config.SENTIMENT_MAX_ROWS

    if not isinstance(raw, dict):
        return None
    rows = raw.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > cap:
        return None                                   # vide, malformé, ou obèse → fail-closed

    instruments: list[dict] = []
    seen: set[str] = set()
    dropped = 0
    for row in rows:
        if not isinstance(row, dict):
            dropped += 1
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            dropped += 1
            continue
        symbol = symbol.strip().upper()
        if symbol in seen:
            dropped += 1                              # doublon contradictoire : la 1re gagne
            continue
        long_pct, short_pct = _pct(row.get("long_pct")), _pct(row.get("short_pct"))
        if long_pct is None or short_pct is None:
            dropped += 1
            continue
        if abs(long_pct + short_pct - 100.0) > _SUM_TOLERANCE_PCT:
            dropped += 1                              # catégorie perdue → on n'invente pas
            continue
        seen.add(symbol)
        instruments.append({
            "symbol": symbol,
            "long_pct": round(long_pct, 1),
            "short_pct": round(short_pct, 1),
            # Ratio absent plutôt qu'infini quand plus personne n'est short.
            "ratio": round(long_pct / short_pct, 2) if short_pct > 0 else None,
            "delta_24h_pct": _optional_finite(row.get("delta_24h_pct")),
            "accounts": int(row["accounts"]) if isinstance(row.get("accounts"), int) else None,
            # Fait observable (« ≥ seuil d'un côté »), jamais une lecture contrarienne.
            "imbalanced": max(long_pct, short_pct) >= threshold,
        })

    if not instruments:
        return None
    venue = raw.get("venue")
    return {
        "venue": venue.strip() if isinstance(venue, str) and venue.strip() else "?",
        "instruments": instruments,
        "dropped": dropped,
        "extreme_pct": threshold,
    }
