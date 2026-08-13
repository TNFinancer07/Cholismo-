"""Jointure des entrées externes sur une séance rejouée (D-084, phase P2).

Le rejeu MBO ne portait ni VIX, ni calendrier, ni ATR : les gates qui en dépendent refusaient, et
la matrice de calibration restait vide (D-083). Ce module les joint — **sans jamais introduire le
biais qui tuerait la mesure**.

---

**Pourquoi les fournisseurs d'`app/external/` ne peuvent pas être appelés tels quels.**

`FredVix.fetch(now=…)` et `FinnhubCalendar.fetch(now=…)` interrogent une API **au présent**.
Rejouer une séance du mois dernier en appelant `fetch()` injecterait le VIX **d'aujourd'hui**
dans une séance d'alors : une donnée du futur, présentée comme le contexte de l'époque. C'est la
forme la plus coûteuse du lookahead, parce qu'elle est invisible — les chiffres sont réels, ils
sont simplement de la mauvaise date.

Ce module lit donc une **série historique fournie**, et fait une jointure **point-in-time** :
à l'instant `t`, on ne voit que ce qui était **déjà publié** à `t`.

**Trois garde-fous, tous testés :**

1. **Aucun lookahead.** Une valeur horodatée après `t` n'est jamais rendue. Comparaison stricte
   sur `ts <= t` — une valeur publiée exactement à `t` est connue à `t`.
2. **La péremption reste la péremption.** Une valeur trop vieille ne se traîne pas indéfiniment :
   au-delà du seuil, elle devient `ABSENT`. Un VIX de la veille n'est pas le VIX de la séance.
3. **Série absente → `ABSENT`, jamais un défaut.** Sans série fournie, les gates continuent de
   refuser. Injecter « VIX = 15 parce que c'est une valeur courante » fabriquerait le contexte
   qu'on prétend mesurer.

**L'ATR ne vient PAS d'une source externe.** Il se dérive des barres de la séance elle-même —
donc du flux MBO. Aller le chercher ailleurs introduirait une seconde vérité sur le même
instrument. Il est calculé ici à partir des transactions rejouées.
"""
from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

#: Au-delà, une valeur jointe est traitée comme périmée. Le VIX est une donnée quotidienne ;
#: 24 h la couvre, 48 h la ferait déborder sur une autre séance. PLACEHOLDER.
VIX_MAX_AGE_S = 24 * 3600.0

#: Fenêtre de blackout autour d'une publication Tier 1. Reprise de la doctrine existante ;
#: PLACEHOLDER tant qu'elle n'est pas confirmée auprès de la prop firm (voir `CLAUDE` v1.7 §6).
NEWS_BLACKOUT_BEFORE_S = 5 * 60.0
NEWS_BLACKOUT_AFTER_S = 2 * 60.0


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class TimedValue:
    ts: float
    value: float


@dataclass(frozen=True)
class CalendarPoint:
    ts: float
    name: str
    tier1: bool = False


@dataclass
class SessionContext:
    """Contexte externe d'une séance, joint point-in-time. État injecté : aucune horloge propre,
    aucun appel réseau — c'est ce qui rend le rejeu reproductible."""

    vix: list[TimedValue] = field(default_factory=list)
    calendar: list[CalendarPoint] = field(default_factory=list)
    vix_max_age_s: float = VIX_MAX_AGE_S

    def __post_init__(self) -> None:
        # Tri à la construction : la jointure suppose l'ordre, et un fichier fourni ne le
        # garantit pas. Le faire une fois vaut mieux que le supposer à chaque requête.
        self.vix = sorted((v for v in self.vix if _finite(v.ts) and _finite(v.value)),
                          key=lambda v: v.ts)
        self.calendar = sorted((c for c in self.calendar if _finite(c.ts)), key=lambda c: c.ts)
        self._vix_ts = [v.ts for v in self.vix]

    # -- jointure point-in-time --

    def vix_at(self, ts: float) -> Optional[float]:
        """Dernière valeur VIX **déjà publiée** à `ts`. Rend `None` si aucune, ou si la plus
        récente est perimée — un VIX de la veille n'est pas le VIX de la séance."""
        if not _finite(ts) or not self.vix:
            return None
        # `bisect_right` sur `ts` : on prend tout ce qui est <= ts. Une valeur publiée
        # exactement à `ts` est connue à `ts` ; une valeur publiée après ne l'est pas.
        index = bisect.bisect_right(self._vix_ts, ts) - 1
        if index < 0:
            return None
        candidate = self.vix[index]
        if ts - candidate.ts > self.vix_max_age_s:
            return None                              # péremption : ABSENT, pas un vieux chiffre
        return candidate.value

    def events_known_at(self, ts: float, *, horizon_s: float = 12 * 3600.0) -> list[dict]:
        """Événements du calendrier visibles à `ts`.

        Un calendrier est **annoncé à l'avance** : contrairement au VIX, ses entrées futures sont
        légitimement connues (c'est tout leur intérêt — F5 protège d'une publication À VENIR).
        Le lookahead ici ne porte pas sur l'horodatage de l'événement mais sur son CONTENU : on
        expose la date et l'importance, jamais un résultat publié après `ts`."""
        if not _finite(ts):
            return []
        return [{"ts": c.ts, "name": c.name, "tier1": c.tier1}
                for c in self.calendar if c.ts <= ts + horizon_s]

    def news_state_at(self, ts: float) -> Optional[str]:
        """État de la porte F0 à `ts`. **`None` = inconnu**, jamais `SAFE` par défaut : sans
        calendrier fourni, la porte reste fail-closed (leçon D-050). Avec un calendrier, on
        peut enfin répondre `SAFE` en connaissance de cause."""
        if not _finite(ts) or not self.calendar:
            return None
        for point in self.calendar:
            if not point.tier1:
                continue
            if point.ts - NEWS_BLACKOUT_BEFORE_S <= ts <= point.ts + NEWS_BLACKOUT_AFTER_S:
                return "HARD_LOCK"
        return "SAFE"

    # -- chargement --

    @classmethod
    def from_dict(cls, data: Any, *, vix_max_age_s: float = VIX_MAX_AGE_S) -> "SessionContext":
        """Charge depuis un dict. Fail-closed : toute entrée illisible est **écartée**, jamais
        interprétée — un contexte approximatif produirait un refus (ou une autorisation)
        approximatif présenté comme mesuré."""
        if not isinstance(data, dict):
            return cls(vix_max_age_s=vix_max_age_s)
        vix: list[TimedValue] = []
        for row in data.get("vix") or ():
            ts, value = _pair(row, "ts", "value")
            if _finite(ts) and _finite(value):
                vix.append(TimedValue(float(ts), float(value)))
        calendar: list[CalendarPoint] = []
        for row in data.get("calendar") or ():
            if not isinstance(row, dict) or not _finite(row.get("ts")):
                continue
            calendar.append(CalendarPoint(float(row["ts"]), str(row.get("name") or ""),
                                          bool(row.get("tier1", False))))
        return cls(vix=vix, calendar=calendar, vix_max_age_s=vix_max_age_s)

    @classmethod
    def from_json_file(cls, path: str, **kw: Any) -> "SessionContext":
        with open(path, encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle), **kw)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "vix_points": len(self.vix),
            "calendar_points": len(self.calendar),
            "tier1_events": sum(1 for c in self.calendar if c.tier1),
            "vix_span": ([self.vix[0].ts, self.vix[-1].ts] if self.vix else None),
            "vix_max_age_s": self.vix_max_age_s,
        }


def _pair(row: Any, key_ts: str, key_value: str) -> tuple[Any, Any]:
    """Accepte `{"ts":…, "value":…}` ou `[ts, value]` — les deux formes circulent dans les
    exports, et exiger la seule qu'on préfère ferait rejeter un fichier valide."""
    if isinstance(row, dict):
        return row.get(key_ts), row.get(key_value)
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return row[0], row[1]
    return None, None


class AtrTracker:
    """ATR dérivé des barres de la séance REJOUÉE, pas d'une source externe.

    Aller chercher l'ATR ailleurs introduirait une seconde vérité sur le même instrument, et
    rien ne garantirait que ses barres coïncident avec celles du flux. Ici il se calcule sur les
    transactions rejouées — donc sur exactement le marché qu'on mesure.

    True range simplifié : `high − low` de la barre. Sans clôture précédente fiable en début de
    séance, le gap n'est pas mesurable ; le supposer nul serait une invention, et l'écart reste
    borné sur des barres 1 min de futures liquides."""

    def __init__(self, *, bar_seconds: float = 60.0, fast: int = 14, slow: int = 50):
        self.bar_s = float(bar_seconds)
        self.fast, self.slow = int(fast), int(slow)
        self._ranges: list[float] = []
        self._bucket: Optional[float] = None
        self._high: Optional[float] = None
        self._low: Optional[float] = None

    def observe(self, price: Any, ts: Any) -> None:
        """Ne lève jamais : les prix viennent d'un fichier."""
        if not _finite(price) or price <= 0 or not _finite(ts):
            return
        bucket = math.floor(float(ts) / self.bar_s) * self.bar_s
        if self._bucket is None:
            self._bucket, self._high, self._low = bucket, float(price), float(price)
            return
        if bucket != self._bucket:
            if self._high is not None and self._low is not None:
                self._ranges.append(self._high - self._low)
                # Borné à la plus longue fenêtre utile : une séance entière n'apporte rien de
                # plus et ferait croître la liste sans fin.
                if len(self._ranges) > self.slow * 4:
                    self._ranges = self._ranges[-self.slow * 2:]
            self._bucket, self._high, self._low = bucket, float(price), float(price)
            return
        self._high = max(self._high or price, float(price))
        self._low = min(self._low if self._low is not None else price, float(price))

    def _mean(self, window: int) -> Optional[float]:
        """`None` sous la fenêtre complète : une moyenne sur 3 barres annoncée comme un ATR 14
        serait un chiffre au nom trompeur."""
        if len(self._ranges) < window:
            return None
        recent = self._ranges[-window:]
        return sum(recent) / len(recent)

    @property
    def atr_fast(self) -> Optional[float]:
        return self._mean(self.fast)

    @property
    def atr_slow(self) -> Optional[float]:
        return self._mean(self.slow)

    def diagnostics(self) -> dict[str, Any]:
        return {"bars_closed": len(self._ranges), "atr_fast": self.atr_fast,
                "atr_slow": self.atr_slow, "fast_window": self.fast, "slow_window": self.slow}
