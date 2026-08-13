"""Simulateur d'exécution FIFO (D-078, phase P3).

Port Python d'`execution_sim.js` (artefact v1.7), **durci**. Il existe pour supprimer un biais
que l'artefact nomme lui-même comme le plus coûteux d'un backtest de scalping :

> Un ordre limite n'est **pas rempli au simple touché** : il entre en fin de file FIFO et n'est
> exécuté que quand le volume devant lui est consommé.

Sur un TP à 5 ticks, supposer le fill au touché transforme des trades jamais remplis en
gagnants. C'est la raison pour laquelle P3 passe avant P2 : sans ce module, les 60+ setups
journalisés seraient corrélés à des résultats **faux**, pas seulement absents.

**AUCUN ORDRE RÉEL (§2.1).** Ce module simule un appariement ; il ne parle à aucun courtier et
n'a aucune dépendance réseau. Un test de garde le vérifie — la frontière est facile à franchir
sans y penser une fois qu'un simulateur produit des `Fill` crédibles.

---

**Quatre défauts de l'artefact, corrigés ici :**

1. **Drapeau inversé.** `if (vol > 0 && !this.requireTrade === false)` — en JS,
   `(!requireTrade) === false` signifie « requireTrade est vrai ». Mettre le drapeau à `false`
   (« ne pas exiger d'échange ») **empêchait** tout remplissage au lieu de l'assouplir. Le
   comportement n'est plus derrière un drapeau ambigu : un échange AU prix consomme la file,
   un échange QUI TRAVERSE remplit.
2. **Latence non rejouable.** `_lat()` tire `Math.random()`. L'invariant n°1 de l'artefact exige
   des fonctions pures à état injecté, « ce qui rend le backtest rejouable à l'identique » — une
   latence non semée le rend précisément **non** rejouable. Le générateur est semé et injecté.
3. **File d'attente optimiste par défaut.** `queueAhead` valait 0 sauf mention contraire : le
   cas par défaut était « premier de la file », l'hypothèse la plus favorable qui soit. Ici la
   file se **déduit du carnet** au moment de l'envoi, et sans carnet l'ordre est **refusé**
   (fail-closed §3) — se placer premier faute de données recréerait le biais combattu.
4. **Carnet épuisé maquillé.** L'artefact complétait au prix du dernier niveau ± 2 ticks, sans
   le signaler : le remplissage devenait fictif et le résultat n'en disait rien. Ici la part non
   servie est **rapportée** (`unfilled_qty`, `book_exhausted`), jamais inventée.

Un cinquième écart, moins visible : `market_order` de l'artefact ne consommait pas le carnet,
si bien que deux ordres au même instant obtenaient tous deux le meilleur niveau — de la
liquidité fabriquée. `market_order_consuming` rend le carnet résiduel.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

#: Motifs d'annulation PROTECTEURS : jamais comptés par le gouverneur, jamais bloqués.
#: Invariant n°4 de l'artefact — « on freine les envois, jamais les sorties ». Un arrêt de
#: risque ne doit pas pouvoir déclencher le gel qui l'empêcherait de se répéter.
PROTECTIVE_CANCELS = ("RISK_HALT", "NEWS_BLACKOUT", "SESSION_END", "OPERATOR")

#: En dessous, un ratio ordre/transaction ne mesure rien — mieux vaut `None` qu'un chiffre qui
#: a l'air d'une mesure (§3). PLACEHOLDER.
OTR_MIN_MESSAGES = 20
#: Annulation « rapide » (ms) et seuil de gel. PLACEHOLDER, repris de l'artefact.
FAST_CANCEL_MS = 1_000
FAST_CANCEL_LIMIT = 10


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class OrderStatus(str, Enum):
    WORKING = "WORKING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class Book:
    """Carnet agrégé. `bids` décroissants, `asks` croissants — l'ordre porte le sens du marché,
    l'inverser retournerait tout le slippage en silence."""
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()


def book_from_levels(bids: Any, asks: Any) -> Book:
    """Construit un carnet depuis des paires brutes `[prix, taille]` (forme du `order_book` du
    ContextSchema). Fail-closed : tout niveau illisible est **écarté**, jamais interprété — un
    carnet approximatif produirait un slippage approximatif présenté comme mesuré."""
    def _clean(raw: Any, descending: bool) -> tuple[BookLevel, ...]:
        out = []
        for entry in raw or ():
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            price, size = entry[0], entry[1]
            if not _finite(price) or not _finite(size) or size <= 0:
                continue
            out.append(BookLevel(float(price), float(size)))
        return tuple(sorted(out, key=lambda lvl: lvl.price, reverse=descending))

    return Book(bids=_clean(bids, True), asks=_clean(asks, False))


@dataclass
class Order:
    id: str
    side: str
    price: float
    qty: float
    queue_ahead: float
    placed_ts_ms: float
    status: OrderStatus = OrderStatus.WORKING
    filled_qty: float = 0.0
    cancel_beyond: Optional[float] = None
    cancel_after_ms: Optional[float] = None
    cancel_reason: Optional[str] = None
    cancelled_ts_ms: Optional[float] = None

    @property
    def remaining(self) -> float:
        return self.qty - self.filled_qty


@dataclass(frozen=True)
class Fill:
    side: str
    qty: float
    price: Optional[float]
    slip_ticks: float
    ts_ms: float
    order_id: Optional[str] = None
    levels_consumed: int = 0
    filled_qty: float = 0.0
    unfilled_qty: float = 0.0
    book_exhausted: bool = False


@dataclass
class _Governor:
    placed: int = 0
    cancelled: int = 0
    filled: int = 0
    fast_cancels: int = 0
    frozen: bool = False
    rejects: int = 0
    slips: list[float] = field(default_factory=list)


class ExecutionSimulator:
    """Appariement FIFO sur événements de marché. État injecté, générateur semé : deux exécutions
    de la même séance produisent le même journal, à la milliseconde près."""

    def __init__(self, *, tick_size: float = 0.25, latency_ms: float = 35.0,
                 latency_jitter_ms: float = 15.0, rng_seed: int = 0,
                 fast_cancel_limit: int = FAST_CANCEL_LIMIT,
                 fast_cancel_ms: float = FAST_CANCEL_MS):
        self.tick = float(tick_size)
        self._latency = float(latency_ms)
        self._jitter = float(latency_jitter_ms)
        self._rng = random.Random(rng_seed)
        self._fast_limit = int(fast_cancel_limit)
        self._fast_ms = float(fast_cancel_ms)
        self._orders: list[Order] = []
        self._fills: list[Fill] = []
        self._gov = _Governor()

    # -- envoi --

    def place_limit(self, side: str, price: float, qty: float, now_ms: float, *,
                    book: Optional[Book] = None, queue_ahead: Optional[float] = None,
                    cancel_beyond: Optional[float] = None,
                    cancel_after_ms: Optional[float] = None) -> Optional[Order]:
        """Place une limite. Rend `None` si l'envoi est refusé — gouverneur gelé, quantité
        aberrante, ou **file d'attente indéterminable**.

        Ce dernier cas est le durcissement principal : sans carnet ni file explicite, l'artefact
        supposait « premier de la file ». Refuser est la seule réponse honnête (§3)."""
        if self._gov.frozen or not _finite(qty) or qty <= 0 or not _finite(price):
            self._gov.rejects += 1
            return None
        ahead = self._resolve_queue(side, price, book, queue_ahead)
        if ahead is None:
            self._gov.rejects += 1
            return None

        self._gov.placed += 1
        order = Order(id=f"o{self._gov.placed}", side=side, price=float(price), qty=float(qty),
                      queue_ahead=ahead, placed_ts_ms=now_ms + self._latency_sample(),
                      cancel_beyond=cancel_beyond, cancel_after_ms=cancel_after_ms)
        self._orders.append(order)
        return order

    def _resolve_queue(self, side: str, price: float, book: Optional[Book],
                       explicit: Optional[float]) -> Optional[float]:
        """La file explicite prime : en rejeu MBO on connaît la vraie position, elle vaut mieux
        que toute déduction. Sinon on somme la liquidité AU prix — on arrive derrière elle."""
        if side not in ("BUY", "SELL"):
            # Un `else: asks` implicite ferait d'un côté mal orthographié — ou d'un `LONG` non
            # traduit — une file lue du MAUVAIS côté, donc presque toujours nulle : exactement
            # le « premier de la file » que ce module existe pour interdire (trouvé en D-080).
            return None
        if explicit is not None:
            return float(explicit) if _finite(explicit) and explicit >= 0 else None
        if book is None:
            return None
        levels = book.bids if side == "BUY" else book.asks
        for lvl in levels:
            if abs(lvl.price - price) < self.tick / 2:
                return lvl.size
        # Prix hors du carnet visible : aucun repos observé à ce niveau, la file est vide.
        # C'est une déduction du carnet, pas un défaut optimiste.
        return 0.0

    def _latency_sample(self) -> float:
        if self._jitter <= 0:
            return self._latency
        return self._latency + (self._rng.random() * 2 - 1) * self._jitter

    # -- annulation : jamais entravée --

    def cancel(self, order_id: str, reason: str, now_ms: float) -> Optional[Order]:
        """Annule un ordre vivant. **Jamais bloquée par le gouverneur** (invariant n°4) : on
        freine les envois, jamais les sorties."""
        order = next((o for o in self._orders
                      if o.id == order_id
                      and o.status in (OrderStatus.WORKING, OrderStatus.PARTIAL)), None)
        if order is None:
            return None
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = reason
        order.cancelled_ts_ms = now_ms
        self._gov.cancelled += 1
        resting = now_ms - order.placed_ts_ms
        if resting < self._fast_ms and reason not in PROTECTIVE_CANCELS:
            self._gov.fast_cancels += 1
            if self._gov.fast_cancels >= self._fast_limit:
                self._gov.frozen = True
        return order

    # -- événements de marché --

    def on_trade(self, ts_ms: float, price: Any, size: Any) -> list[Fill]:
        """Traite un échange observé. Ne lève jamais : les événements viennent d'un fichier de
        rejeu, et un fichier livre parfois n'importe quoi (fail-closed §3)."""
        fills: list[Fill] = []
        tradable = _finite(price) and _finite(size) and size > 0 and _finite(ts_ms)
        for order in self._orders:
            if order.status not in (OrderStatus.WORKING, OrderStatus.PARTIAL):
                continue
            if _finite(ts_ms) and ts_ms < order.placed_ts_ms:
                continue                                # latence : pas encore au marché
            if self._expired(order, ts_ms):
                continue
            if tradable and self._invalidated(order, float(price), ts_ms):
                continue
            if not tradable:
                continue
            fill = self._match(order, float(price), float(size), ts_ms)
            if fill is not None:
                fills.append(fill)
        return fills

    def _expired(self, order: Order, ts_ms: float) -> bool:
        if order.cancel_after_ms is None or not _finite(ts_ms):
            return False
        if ts_ms - order.placed_ts_ms > order.cancel_after_ms:
            self.cancel(order.id, "TIME_EXPIRY", ts_ms)
            return True
        return False

    def _invalidated(self, order: Order, price: float, ts_ms: float) -> bool:
        if order.cancel_beyond is None:
            return False
        beyond = (price < order.cancel_beyond if order.side == "BUY"
                  else price > order.cancel_beyond)
        if beyond:
            self.cancel(order.id, "PRICE_INVALIDATION", ts_ms)
            return True
        return False

    def _match(self, order: Order, price: float, size: float, ts_ms: float) -> Optional[Fill]:
        """Le cœur FIFO. Deux cas seulement, et le premier est celui qui coûte cher à ignorer :

        - **AU prix** : le volume échangé consomme d'abord la file devant nous. Ce qui reste,
          et seulement lui, nous remplit ;
        - **QUI TRAVERSE** : si ça s'échange au-delà de notre limite, tout ce qui était devant a
          nécessairement été servi — on est rempli au prix limite.
        """
        through = (price < order.price - 1e-9 if order.side == "BUY"
                   else price > order.price + 1e-9)
        if through:
            return self._fill(order, order.remaining, order.price, ts_ms, 0.0)

        if abs(price - order.price) >= self.tick / 2:
            return None                                 # échange ailleurs : rien pour nous

        volume = size
        if order.queue_ahead > 0:
            consumed = min(order.queue_ahead, volume)
            order.queue_ahead -= consumed
            volume -= consumed
        if volume <= 0:
            return None                                 # la file a tout absorbé
        return self._fill(order, min(volume, order.remaining), order.price, ts_ms, 0.0)

    def _fill(self, order: Order, qty: float, price: float, ts_ms: float,
              slip_ticks: float) -> Optional[Fill]:
        if qty <= 0:
            return None
        order.filled_qty += qty
        order.status = (OrderStatus.FILLED if order.filled_qty >= order.qty - 1e-9
                        else OrderStatus.PARTIAL)
        fill = Fill(side=order.side, qty=qty, price=price, slip_ticks=slip_ticks, ts_ms=ts_ms,
                    order_id=order.id, filled_qty=qty)
        self._fills.append(fill)
        self._gov.filled += 1
        self._gov.slips.append(slip_ticks)
        return fill

    # -- ordres au marché : le slippage est une CONSOMMATION de liquidité --

    def market_order(self, side: str, qty: float, book: Book, now_ms: float) -> Fill:
        fill, _ = self.market_order_consuming(side, qty, book, now_ms)
        return fill

    def market_order_consuming(self, side: str, qty: float, book: Book,
                               now_ms: float) -> tuple[Fill, Book]:
        """Marche à travers le carnet et rend AUSSI le carnet résiduel. L'artefact ne consommait
        pas : deux ordres au même instant obtenaient tous deux le meilleur niveau — de la
        liquidité fabriquée à partir de rien."""
        levels = list(book.asks if side == "BUY" else book.bids)
        remaining = float(qty) if _finite(qty) and qty > 0 else 0.0
        cost = 0.0
        taken = 0.0
        consumed_levels = 0
        residual: list[BookLevel] = []

        for lvl in levels:
            if remaining <= 0:
                residual.append(lvl)
                continue
            take = min(remaining, lvl.size)
            cost += take * lvl.price
            taken += take
            remaining -= take
            consumed_levels += 1
            if lvl.size - take > 0:
                residual.append(BookLevel(lvl.price, lvl.size - take))

        avg = cost / taken if taken > 0 else None
        reference = levels[0].price if levels else None
        slip = (abs(avg - reference) / self.tick
                if avg is not None and reference is not None else 0.0)
        fill = Fill(side=side, qty=float(qty), price=avg, slip_ticks=slip, ts_ms=now_ms,
                    levels_consumed=consumed_levels, filled_qty=taken,
                    # La part non servie est RAPPORTÉE, jamais complétée à un prix inventé :
                    # le carnet ne portait pas cette liquidité, et le dire est la seule réponse
                    # honnête (§3).
                    unfilled_qty=remaining, book_exhausted=remaining > 0)
        if taken > 0:
            self._fills.append(fill)
            self._gov.filled += 1
            self._gov.slips.append(slip)
        new_book = (Book(bids=book.bids, asks=tuple(residual)) if side == "BUY"
                    else Book(bids=tuple(residual), asks=book.asks))
        return fill, new_book

    # -- lecture --

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self._fills)

    @property
    def orders(self) -> tuple[Order, ...]:
        return tuple(self._orders)

    def stats(self) -> dict[str, Any]:
        messages = self._gov.placed + self._gov.cancelled
        return {
            "placed": self._gov.placed,
            "filled": self._gov.filled,
            "cancelled": self._gov.cancelled,
            "fast_cancels": self._gov.fast_cancels,
            "frozen": self._gov.frozen,
            "rejects": self._gov.rejects,
            "avg_slip_ticks": (sum(self._gov.slips) / len(self._gov.slips)
                               if self._gov.slips else 0.0),
            # `None` sous l'échantillon minimal : un ratio sur trois messages ne mesure rien.
            "otr_ratio": (None if messages < OTR_MIN_MESSAGES
                          else (messages / self._gov.filled if self._gov.filled else None)),
        }
