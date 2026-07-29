"""MacroNewsProvider & Porte F0 — hard lock macro sur le calendrier économique (D-050).

Trader un sweep DANS la fenêtre d'une publication USD à fort impact, c'est trader le chaos :
le spread explose, les stops sont chassés, la microstructure ment. La Porte F0 verrouille
l'évaluation LSR autour de ces instants — **en amont de toute microstructure**.

**États** (`NewsState`) — plusieurs événements → le plus SÉVÈRE gagne, bornes du verrou
INCLUSES (le doute penche toujours vers le verrou) :
- `NORMAL`     : aucun événement à portée ;
- `WARNING`    : [T−15 min, T−2 min) — advisory, la porte laisse passer (l'humain voit) ;
- `HARD_LOCK`  : [T−2 min, T+2 min] — F0 rejette immédiatement, silence ;
- `SAFETY_UNKNOWN` : cache JAMAIS initialisé ou FOSSILE (> `MACRO_NEWS_MAX_AGE_S`) — la couche
  est câblée mais AVEUGLE → F0 rejette aussi (« on ne trade jamais à l'aveugle », D-047).
  Un calendrier fetché avec succès et VIDE est un état CONNU (semaine calme) → NORMAL.

**Deux étages** (même architecture que le NT8 provider, D-048) : un worker async rafraîchit le
cache `(events, fetched_ts)` sur sa cadence (`MACRO_NEWS_REFRESH_SECONDS`, fetch en
`asyncio.to_thread` — l'event loop ne gèle jamais) ; `get_state(now)` est SYNC et PUR — zéro
I/O sur le chemin d'évaluation, horloge injectée. Un fetch raté ou illisible CONSERVE l'ancien
cache, qui vieillit vers `SAFETY_UNKNOWN` par son `fetched_ts` d'origine.

**Parser Forex-Factory JSON** (`parse_ff_json`) : pur et défensif — ne garde que USD × HIGH
(casse tolérée), entrée corrompue ignorée LIGNE À LIGNE (dict manquant, date illisible, titre
absent), flux illisible → None (jamais un crash, jamais un calendrier partiel pris pour vrai
si le JSON entier est cassé). Dates ISO avec offset → UTC.

**Amendement D-046 documenté** : l'isolation de la couche LSR disait « aucune donnée news ici ».
La Porte F0 la traverse par choix du propriétaire de la spec — mais l'état news entre comme un
CHAMP D'ENTRÉE (`LsrInputs.news_state`), calculé ici, jamais lu par `evaluate_lsr` lui-même :
la fonction reste PURE. `news_state=None` = couche non câblée (stack démo) → la porte n'existe
pas ; la protection de facto reste le couplage news du détecteur D-028 et le blackout humain.
Aucun ordre nulle part (§2.1)."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import urllib.request
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel

from . import config

log = logging.getLogger("cholismo.macro_news")


class NewsState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HARD_LOCK = "HARD_LOCK"
    SAFETY_UNKNOWN = "SAFETY_UNKNOWN"


class MacroEvent(BaseModel):
    title: str
    currency: str
    impact: str
    event_time: datetime                                    # UTC (aware)


def parse_ff_json(text: str) -> Optional[list[MacroEvent]]:
    """Flux Forex-Factory JSON → événements USD × HIGH. `None` = flux ILLISIBLE (fail-closed,
    l'appelant garde son ancien cache) ; `[]` = flux lisible et VIDE (état connu). Entrée
    corrompue ignorée ligne à ligne — un calendrier ne meurt pas d'une entrée pourrie."""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, list):
        return None
    events: list[MacroEvent] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title, country, impact = entry.get("title"), entry.get("country"), entry.get("impact")
        if not (isinstance(title, str) and isinstance(country, str) and isinstance(impact, str)):
            continue
        if country.strip().upper() != "USD" or impact.strip().upper() != "HIGH":
            continue
        try:
            when = datetime.fromisoformat(str(entry.get("date")))
        except (ValueError, TypeError):
            continue                                        # date illisible → entrée écartée
        if when.tzinfo is None:
            continue                                        # naïve = fuseau inconnu → écartée (§3)
        events.append(MacroEvent(title=title, currency="USD", impact="HIGH", event_time=when))
    return events


class MacroNewsProvider:
    """Worker calendrier macro — cache async, évaluation d'état PURE (voir docstring module)."""

    def __init__(self, url: str,
                 refresh_seconds: float = None,             # type: ignore[assignment]
                 lock_before_min: float = None,             # type: ignore[assignment]
                 lock_after_min: float = None,              # type: ignore[assignment]
                 warning_before_min: float = None,          # type: ignore[assignment]
                 max_age_s: float = None,                   # type: ignore[assignment]
                 fetcher: Optional[Callable[[], str]] = None):
        self._url = url
        self._refresh_s = refresh_seconds if refresh_seconds is not None else config.MACRO_NEWS_REFRESH_SECONDS
        self._lock_before_s = (lock_before_min if lock_before_min is not None
                               else config.NEWS_LOCK_BEFORE_MIN) * 60.0
        self._lock_after_s = (lock_after_min if lock_after_min is not None
                              else config.NEWS_LOCK_AFTER_MIN) * 60.0
        self._warn_before_s = (warning_before_min if warning_before_min is not None
                               else config.NEWS_WARNING_BEFORE_MIN) * 60.0
        self._max_age_s = max_age_s if max_age_s is not None else config.MACRO_NEWS_MAX_AGE_S
        self._fetcher = fetcher if fetcher is not None else self._fetch_url
        self._cache: Optional[tuple[list[MacroEvent], float]] = None   # (events, fetched_ts)
        self._task: Optional[asyncio.Task] = None

    # -- étage async : rafraîchissement --

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("macro news poll failed (fail-closed: cache ages to SAFETY_UNKNOWN)")
            await asyncio.sleep(max(1.0, self._refresh_s))

    async def refresh(self) -> None:
        """Un cycle fetch+parse — l'I/O part en thread. Échec réseau ou flux illisible →
        l'ancien cache RESTE (et vieillit vers SAFETY_UNKNOWN par son fetched_ts d'origine)."""
        try:
            text = await asyncio.to_thread(self._fetcher)
        except Exception:
            return                                          # feed mort → rejet naturel, silence
        events = parse_ff_json(text)
        if events is None:
            return                                          # flux illisible → cache conservé
        self._cache = (events, __import__("time").time())

    def _fetch_url(self) -> str:
        with urllib.request.urlopen(self._url, timeout=10) as resp:   # dans un thread (to_thread)
            return resp.read().decode("utf-8", errors="replace")

    # -- étage sync : évaluation d'état PURE (zéro I/O, horloge injectée) --

    def get_state(self, now: float) -> NewsState:
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            return NewsState.SAFETY_UNKNOWN                 # horloge douteuse = aveugle
        if self._cache is None:
            return NewsState.SAFETY_UNKNOWN                 # jamais initialisé
        events, fetched_ts = self._cache
        if not math.isfinite(fetched_ts) or fetched_ts > now or now - fetched_ts > self._max_age_s:
            return NewsState.SAFETY_UNKNOWN                 # calendrier fossile/fantôme = aveugle
        state = NewsState.NORMAL
        for e in events:
            try:
                t0 = e.event_time.timestamp()
            except (OverflowError, OSError, ValueError):
                continue                                    # date dégénérée → événement écarté
            delta = now - t0                                # < 0 avant l'événement
            if -self._lock_before_s <= delta <= self._lock_after_s:
                return NewsState.HARD_LOCK                  # le plus sévère — verdict immédiat
            if -self._warn_before_s <= delta < -self._lock_before_s:
                state = NewsState.WARNING
        return state
