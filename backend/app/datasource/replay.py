"""ReplayDataSource — rejouer un tape enregistré DANS le terminal (Étape 2).

Troisième implémentation de `MarketDataSource`, au même titre que `MockDataSource` : le moteur
ne sait pas laquelle est branchée (CLAUDE §4, la couture unique).

**Le point dur : le sens du flux.** `MarketDataSource` est TIRÉ — le moteur appelle
`tick_fast(state)` à sa cadence. `ReplayEngine.start()`, lui, POUSSE avec ses propres `sleep`.
Les brancher tels quels mettrait deux horloges en concurrence et gèlerait la boucle
d'événements (§7). La source consomme donc l'itérateur **pur** (`iter_ticks`), sans aucune
cadence propre : à chaque appel du moteur, elle avance une **horloge virtuelle** et publie les
ticks échus. Le terminal reste le seul à cadencer.

**Ce qu'un replay peut honnêtement alimenter, et rien de plus.** Un tape contient des prints et,
quand le fichier les porte, une profondeur au meilleur limite. Il ne contient ni VIX, ni GEX, ni
score SVS, ni matrice Bridgewater. Ces champs ne sont donc **pas écrits** : ils vieillissent
visiblement vers STALE puis ABSENT, exactement comme une source coupée. Fabriquer un SVS à
partir d'un tape rejoué serait un chiffre inventé qui a l'air d'une mesure — le mensonge que
§3 interdit. Un replay dit ce qu'il sait, et se tait sur le reste.

**Profondeur inconnue ≠ carnet vide** (D-055). Si `bid_vol`/`ask_vol` manquent, aucun
`order_book` n'est publié pour ce tick : un carnet à zéro annoncerait une absence de liquidité
qui n'a jamais été observée.

**Horodatage : celui du FICHIER, décalé sur maintenant.** Publier les horodatages bruts d'une
séance de l'an dernier ferait juger toutes les données périmées par la couche de fraîcheur —
le terminal afficherait ABSENT partout et le replay serait inutilisable. On conserve donc les
ÉCARTS du fichier (c'est eux qui portent les rafales et les trous) en les rebasant sur l'instant
de démarrage. Le décalage appliqué est exposé dans l'état, jamais tu.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from ..redis_state import RedisState
from ..replay.replay_engine import MAX_TICKS, ReplayEngine, ReplaySummary, Tick
from .base import MarketDataSource

# Le tape publié est une fenêtre glissante, comme celui de la source mock : le champ EST la
# fenêtre, et le moteur order flow lit dedans.
TAPE_WINDOW = 200
# Nom de source déclaré dans Redis. Volontairement DISTINCT de `sierra_chart` : un opérateur
# doit pouvoir lire, sans rien ouvrir, que ces prints viennent d'un enregistrement et non du
# marché. Un replay qui se fait passer pour du direct est le pire état possible de ce terminal.
SOURCE_NAME = "replay"
# Bornes de vitesse. `speed=0` serait une pause déguisée (utiliser `pause()`, qui le DIT) ;
# au-delà de 1000×, une séance entière défile en une fraction de seconde et plus aucune fenêtre
# temporelle n'a de sens.
MIN_SPEED, MAX_SPEED = 0.01, 1000.0


@dataclass
class ReplayState:
    """État de lecture, tel qu'il est rendu à l'UI et à l'API de contrôle."""
    filepath: str
    playing: bool = False
    speed: float = 1.0
    position: int = 0                       # ticks publiés depuis le début du fichier
    total: Optional[int] = None             # ticks valides du fichier (connu après indexation)
    clock: Optional[float] = None           # horloge virtuelle (temps du FICHIER)
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None
    offset: float = 0.0                     # décalage appliqué aux horodatages publiés
    finished: bool = False
    summary: Optional[ReplaySummary] = None

    @property
    def resume(self) -> str:
        """L'état en UNE ligne — un dict de compteurs n'est pas un message (leçon D-056)."""
        etat = "TERMINÉ" if self.finished else ("LECTURE" if self.playing else "PAUSE")
        total = self.total if self.total is not None else "?"
        avance = ""
        if self.first_ts is not None and self.clock is not None:
            avance = f" · t+{self.clock - self.first_ts:.1f}s de séance"
        ecartes = f" · {self.summary.skipped} ligne(s) écartée(s)" if self.summary \
            and self.summary.skipped else ""
        return f"{etat} ×{self.speed:g} · tick {self.position}/{total}{avance}{ecartes}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "resume": self.resume, "filepath": self.filepath, "playing": self.playing,
            "speed": self.speed, "position": self.position, "total": self.total,
            "clock": self.clock, "first_ts": self.first_ts, "last_ts": self.last_ts,
            "offset": self.offset, "finished": self.finished,
            "source": SOURCE_NAME,
            "skipped": self.summary.skipped if self.summary else 0,
            "skipped_reasons": dict(self.summary.reasons) if self.summary else {},
        }


@dataclass
class _Book:
    """Meilleure limite reconstruite depuis le tape. Un CSV de tape ne porte pas dix niveaux :
    prétendre le contraire fabriquerait une profondeur que personne n'a observée."""
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_vol: Optional[float] = None
    ask_vol: Optional[float] = None
    tick: float = 0.25

    def update(self, t: Tick) -> None:
        """Un print à l'achat s'est exécuté à l'ASK : c'est donc l'ask qu'il révèle, et le bid
        est déduit d'un tick en dessous. L'inverse pour une vente."""
        if t["side"] == "BUY":
            self.ask, self.ask_vol = t["price"], t["ask_vol"]
            self.bid = round(t["price"] - self.tick, 4)
            self.bid_vol = t["bid_vol"]
        else:
            self.bid, self.bid_vol = t["price"], t["bid_vol"]
            self.ask = round(t["price"] + self.tick, 4)
            self.ask_vol = t["ask_vol"]

    def payload(self) -> Optional[dict[str, list[list[float]]]]:
        """`None` dès qu'un côté est inconnu : un carnet à zéro annoncerait une absence de
        liquidité qui n'a jamais été observée (D-055)."""
        if None in (self.bid, self.ask, self.bid_vol, self.ask_vol):
            return None
        return {"bids": [[float(self.bid), float(self.bid_vol)]],      # type: ignore[arg-type]
                "asks": [[float(self.ask), float(self.ask_vol)]]}      # type: ignore[arg-type]


class ReplayDataSource(MarketDataSource):
    """Source de marché alimentée par un tape enregistré. Play / pause / vitesse / seek.

    `now` est injectable (`clock`) : la source ne lit l'horloge que par ce point, ce qui la rend
    testable sans dormir — même discipline que le reste du dépôt.
    """

    def __init__(self, filepath: str, *, speed: float = 1.0, autoplay: bool = True,
                 tape_window: int = TAPE_WINDOW, max_ticks: int = MAX_TICKS,
                 clock: Any = time.time) -> None:
        self._engine = ReplayEngine(filepath, lambda _t: None)
        self._clock = clock
        self._max_ticks = max_ticks
        self._tape: deque[dict[str, Any]] = deque(maxlen=tape_window)
        self._book = _Book()
        self._seq = 0
        self._ticks: list[Tick] = []      # indexé en mémoire : `seek` exige l'accès direct
        self._summary: Optional[ReplaySummary] = None
        self._lock = asyncio.Lock()
        self._wall: Optional[float] = None          # dernier instant RÉEL observé
        self.state = ReplayState(filepath=filepath, speed=_clamp_speed(speed),
                                 playing=bool(autoplay))

    # -- indexation (paresseuse, une seule fois) --

    def _index(self) -> None:
        if self._ticks:
            return
        summary: Optional[ReplaySummary] = None
        for tick, summary in self._engine.iter_ticks(max_ticks=self._max_ticks):
            self._ticks.append(tick)
        self._summary = summary
        self.state.summary = summary
        self.state.total = len(self._ticks)
        if self._ticks:
            self.state.first_ts = self._ticks[0]["timestamp"]
            self.state.last_ts = self._ticks[-1]["timestamp"]
            if self.state.clock is None:
                self.state.clock = self.state.first_ts

    # -- contrôle : play / pause / vitesse / seek --

    def play(self) -> ReplayState:
        self._index()
        if not self.state.finished:
            self.state.playing = True
            self._wall = None                       # on ne rattrape pas le temps de la pause
        return self.state

    def pause(self) -> ReplayState:
        self.state.playing = False
        return self.state

    def set_speed(self, speed: float) -> ReplayState:
        """`speed=0` n'est pas accepté : ce serait une pause qui ne dit pas son nom, et l'UI
        afficherait « LECTURE » sur un flux arrêté."""
        self.state.speed = _clamp_speed(speed)
        return self.state

    def seek(self, *, position: Optional[int] = None, ts: Optional[float] = None,
             fraction: Optional[float] = None) -> ReplayState:
        """Repositionne la lecture. **Le tape et le carnet sont REMIS À ZÉRO** : les garder
        ferait cohabiter des prints d'avant le saut avec ceux d'après, et toute mesure de
        fenêtre (B1/B4) porterait sur un temps qui n'a jamais existé."""
        self._index()
        if not self._ticks:
            return self.state
        if fraction is not None:
            position = int(max(0.0, min(1.0, fraction)) * (len(self._ticks) - 1))
        if ts is not None:
            position = 0
            for i, t in enumerate(self._ticks):
                if t["timestamp"] <= ts:
                    position = i
                else:
                    break
        if position is None:
            return self.state
        position = max(0, min(int(position), len(self._ticks)))
        self.state.position = position
        self.state.clock = (self._ticks[position]["timestamp"] if position < len(self._ticks)
                            else self._ticks[-1]["timestamp"])
        self.state.finished = position >= len(self._ticks)
        self._tape.clear()
        self._book = _Book()
        self._wall = None
        return self.state

    def restart(self) -> ReplayState:
        """Relance depuis le début — `seek(0)` plus la sortie de l'état TERMINÉ."""
        self.seek(position=0)
        self.state.finished = False
        return self.state

    # -- MarketDataSource --

    async def tick_fast(self, state: RedisState) -> None:
        """Avance l'horloge virtuelle du temps réel écoulé × vitesse, et publie les ticks échus.

        Aucun `sleep` : c'est le moteur qui cadence. En pause, l'horloge n'avance pas — et le
        temps passé en pause n'est PAS rattrapé au redémarrage, sinon reprendre après dix minutes
        déverserait dix minutes de tape d'un coup.
        """
        async with self._lock:                      # `seek` pendant une publication ferait
            self._index()                           # publier des prints des deux côtés du saut
            due = self._advance()
            if not due:
                return
            for tick in due:
                self._seq += 1
                self._tape.append({
                    "ts": tick["timestamp"] + self.state.offset,
                    "price": tick["price"], "size": tick["volume"],
                    "side": tick["side"], "seq": self._seq,
                })
                self._book.update(tick)
            published_ts = self._tape[-1]["ts"]
            await state.write_raw("tape", list(self._tape), SOURCE_NAME, ts=published_ts,
                                  flags=["REPLAY"])
            book = self._book.payload()
            if book is not None:
                # Profondeur connue seulement : un carnet absent vaut mieux qu'un carnet inventé.
                await state.write_raw("order_book", book, SOURCE_NAME, ts=published_ts,
                                      flags=["REPLAY"])

    async def tick_slow(self, state: RedisState) -> None:
        """Un tape ne contient aucune macro. Rien n'est écrit : les blocs lents vieillissent
        visiblement vers STALE puis ABSENT, ce qui est la vérité (§3)."""
        return None

    # -- internes --

    def _advance(self) -> list[Tick]:
        """Ticks échus depuis le dernier appel. L'horloge virtuelle avance du temps RÉEL écoulé
        multiplié par la vitesse — c'est ce qui conserve les rafales et les trous du fichier."""
        maintenant = float(self._clock())
        if self.state.finished or not self.state.playing or not self._ticks:
            self._wall = maintenant
            return []
        if self._wall is None:                      # premier tour, ou reprise après pause
            self._wall = maintenant
            if self.state.clock is None:
                self.state.clock = self.state.first_ts
            self.state.offset = maintenant - float(self.state.clock or maintenant)
            return []
        ecoule = max(0.0, maintenant - self._wall) * self.state.speed
        self._wall = maintenant
        self.state.clock = float(self.state.clock or 0.0) + ecoule
        due: list[Tick] = []
        while self.state.position < len(self._ticks) and \
                self._ticks[self.state.position]["timestamp"] <= self.state.clock:
            due.append(self._ticks[self.state.position])
            self.state.position += 1
        if self.state.position >= len(self._ticks):
            self.state.finished = True
            self.state.playing = False
        return due


def _clamp_speed(value: Any) -> float:
    """Une vitesse absente ou absurde revient à 1×. `0` est refusé : c'est `pause()`."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if speed != speed or speed in (float("inf"), float("-inf")):
        return 1.0
    return min(max(speed, MIN_SPEED), MAX_SPEED)
