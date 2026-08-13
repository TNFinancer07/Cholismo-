"""Reconstruction du carnet MBO (D-079, phase P3).

Port de `of/book.ts` (artefact v1.7). Maintient l'état **par ordre** (`order_id`) et l'agrégat
**par niveau de prix**. Le suivi par ordre est ce qui rend B1 (rechargement de mur) mesurable :
avec du L2 agrégé seul, on ne distingue pas « le mur a été consommé puis rechargé » de « le mur
n'a jamais bougé ». C'est aussi lui qui donne au simulateur FIFO (D-078) une **vraie** profondeur
de file au lieu d'une déduction.

---

**L'ambiguïté de côté sur un trade — traitée, pas devinée.**

L'artefact impute le passif d'un trade depuis le drapeau : `side === 'A' ? asks : bids`. Or son
propre `CLAUDE.md` §5 avertit que « `tradeSideMeaning` = **agresseur**, pas le passif consommé —
l'inverser retourne B2 et B3 **en silence** », et Databento documente `side` comme le côté de
l'agresseur. Sous cette convention, l'imputation de l'artefact est inversée ; sous la convention
de sa propre fixture, elle est juste. **Les deux lectures s'opposent et aucune n'est vérifiable
sans données réelles.**

Deviner inverserait deux gates sans qu'aucun test ne tombe. Le côté passif est donc résolu dans
cet ordre :

1. **l'`order_id` au repos** — seule source autoritaire : l'ordre touché porte son propre côté ;
2. **à défaut, le PRIX** comparé aux meilleures limites — dérivé du carnet, donc indépendant de
   la convention (`order_id = 0` est le cas normal des données réelles) ;
3. **sinon, rejet compté** (`unresolved_trades`), jamais une imputation au hasard (§3).

Un test vérifie que le drapeau `side` ne peut PAS inverser le passif.

---

**Deux écarts de plus avec l'artefact :**

- Sa docstring annonce « traitement O(1) par événement, sans allocation dans le chemin chaud ».
  C'est inexact : `recomputeBest` balaie tous les niveaux à chaque retrait et `cumulativeDepth`
  alloue puis trie. On ne reprend pas la promesse ; la correction prime, et les meilleures
  limites sont maintenues de façon incrémentale quand c'est possible.
- `levelOf` crée une entrée à chaque prix touché, y compris pour l'annulation d'un ordre inconnu
  à un prix arbitraire : sur une séance, la table croît sans borne (piège « fuite mémoire » de
  RUNTIME_LOOPS Loop D). Le nombre de niveaux suivis par côté est **borné**, les plus éloignés
  du marché étant évincés en premier.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .events import MboAction, MboEvent, MboSide, finite

#: Niveaux suivis par côté. Largement au-delà de toute profondeur exploitable (F4 en lit 3),
#: mais borné pour qu'une séance ne fasse pas croître la table indéfiniment. PLACEHOLDER.
MAX_LEVELS_PER_SIDE = 512


@dataclass
class LevelState:
    price: float
    size: float = 0.0
    order_count: int = 0
    #: Cumulés sur la session — c'est leur PERSISTANCE après vidage du niveau qui rend B1
    #: mesurable, et la séparation `cancelled`/`traded` qui rend le spoofing distinguable
    #: d'une consommation réelle.
    added_volume: float = 0.0
    cancelled_volume: float = 0.0
    traded_volume: float = 0.0


@dataclass
class _OrderState:
    price: float
    side: str
    size: float


class MboBook:
    """Carnet par ordre + agrégat par niveau. Déterministe : aucune horloge, aucun aléa."""

    def __init__(self, tick_size: float, *, max_levels_per_side: int = MAX_LEVELS_PER_SIDE):
        self.tick = float(tick_size)
        self._max_levels = int(max_levels_per_side)
        self._orders: dict[int, _OrderState] = {}
        self._bids: dict[int, LevelState] = {}
        self._asks: dict[int, LevelState] = {}
        #: Trades dont le passif n'a pas pu être résolu — comptés, jamais imputés au hasard.
        self.unresolved_trades = 0
        #: Côté passif du DERNIER trade appliqué, résolu AVANT que le carnet ne mute (D-086).
        #: Un consommateur qui re-résout après coup regarde un carnet où le niveau consommé a
        #: déjà disparu : pendant un sweep — l'événement qu'on cherche précisément à détecter —
        #: les trades suivants tombent « dans le spread » et sont rejetés à tort.
        self.last_trade_passive_side: Optional[str] = None

    # -- clés et accès --

    def _key(self, price: float) -> int:
        """Clé entière : une clé flottante collisionne (5000.0000000001 ≠ 5000.0)."""
        return round(price / self.tick)

    def _side_map(self, side: str) -> dict[int, LevelState]:
        return self._bids if side == MboSide.BID else self._asks

    def _level_of(self, side: str, price: float) -> LevelState:
        levels = self._side_map(side)
        key = self._key(price)
        level = levels.get(key)
        if level is None:
            level = LevelState(price=price)
            levels[key] = level
            self._evict_if_needed(side)
        return level

    def _evict_if_needed(self, side: str) -> None:
        """Évince les niveaux les plus ÉLOIGNÉS du marché, jamais les plus proches : c'est la
        profondeur utile qu'on doit garder, et l'historique lointain n'alimente aucun gate."""
        levels = self._side_map(side)
        if len(levels) <= self._max_levels:
            return
        best = self._best_key(side)
        if best is None:
            # Aucun niveau vivant : on évince les plus anciens insérés (ordre du dict).
            for key in list(levels)[: len(levels) - self._max_levels]:
                del levels[key]
            return
        # Distance au meilleur, décroissante : on coupe la queue.
        ordered = sorted(levels, key=lambda k: abs(k - best), reverse=True)
        for key in ordered[: len(levels) - self._max_levels]:
            if levels[key].size <= 0:                 # jamais évincer de la liquidité vivante
                del levels[key]

    def _best_key(self, side: str) -> Optional[int]:
        levels = self._side_map(side)
        best: Optional[int] = None
        for key, level in levels.items():
            if level.size <= 0:
                continue
            if best is None or (key > best if side == MboSide.BID else key < best):
                best = key
        return best

    # -- application d'un événement --

    def apply(self, event: MboEvent) -> bool:
        """Applique un événement. Rend `True` si le carnet a changé. Ne lève jamais : les
        événements viennent d'un fichier, et un fichier livre parfois n'importe quoi."""
        action = event.action
        if action == MboAction.CLEAR:
            self.clear()
            return True
        if not finite(event.price) or not finite(event.size) or event.size < 0:
            return False
        if action == MboAction.ADD:
            return self._add(event)
        if action == MboAction.CANCEL:
            return self._remove(event, traded=False)
        if action == MboAction.MODIFY:
            return self._modify(event)
        if action in (MboAction.TRADE, MboAction.FILL):
            return self._trade(event)
        return False

    def _add(self, event: MboEvent) -> bool:
        if event.side not in (MboSide.BID, MboSide.ASK) or event.size <= 0:
            return False
        self._orders[event.order_id] = _OrderState(event.price, event.side, event.size)
        level = self._level_of(event.side, event.price)
        level.size += event.size
        level.order_count += 1
        level.added_volume += event.size
        return True

    def _modify(self, event: MboEvent) -> bool:
        existing = self._orders.get(event.order_id)
        if existing is not None:
            old = self._level_of(existing.side, existing.price)
            old.size = max(0.0, old.size - existing.size)
            old.order_count = max(0, old.order_count - 1)
        return self._add(event)

    def _remove(self, event: MboEvent, *, traded: bool, side: Optional[str] = None,
                price: Optional[float] = None) -> bool:
        existing = self._orders.get(event.order_id) if event.order_id else None
        resolved_side = existing.side if existing else side
        resolved_price = existing.price if existing else price
        if resolved_side is None:
            # Annulation d'un ordre inconnu : le carnet est partiel au démarrage, et ignorer
            # laisserait des niveaux gonflés en permanence. On impute au côté annoncé.
            resolved_side = event.side if event.side in (MboSide.BID, MboSide.ASK) else None
            resolved_price = event.price
        if resolved_side is None or resolved_price is None:
            return False

        level = self._level_of(resolved_side, resolved_price)
        qty = min(event.size, existing.size) if existing else event.size
        level.size = max(0.0, level.size - qty)
        if traded:
            level.traded_volume += qty
        else:
            level.cancelled_volume += qty

        if existing is not None:
            existing.size -= qty
            if existing.size <= 0:
                del self._orders[event.order_id]
                level.order_count = max(0, level.order_count - 1)
        return True

    def _trade(self, event: MboEvent) -> bool:
        """Un trade consomme du PASSIF. Voir la docstring du module pour l'ordre de résolution
        du côté — et pourquoi le drapeau `side` n'en fait pas partie.

        Le côté résolu est MÉMORISÉ (`last_trade_passive_side`) : il l'est ici, sur le carnet
        d'AVANT la consommation. Le re-résoudre après coup regarderait un carnet où le niveau
        vient de disparaître (D-086)."""
        self.last_trade_passive_side = None
        if event.size <= 0:
            return False
        if event.order_id and event.order_id in self._orders:
            self.last_trade_passive_side = self._orders[event.order_id].side
            return self._remove(event, traded=True)     # (1) ordre au repos : autoritaire

        passive = self._passive_side_from_price(event.price)
        if passive is None:                              # (3) inrésolvable → rejet COMPTÉ
            self.unresolved_trades += 1
            return False
        self.last_trade_passive_side = passive
        return self._remove(event, traded=True, side=passive, price=event.price)

    def _passive_side_from_price(self, price: float) -> Optional[str]:
        """(2) Le prix contre les meilleures limites. Un échange au niveau de l'ask (ou
        au-dessus) a consommé de l'ask ; au niveau du bid (ou en dessous), du bid. Entre les
        deux — dans le spread — rien n'est résolvable."""
        best_bid, best_ask = self._best_key(MboSide.BID), self._best_key(MboSide.ASK)
        key = self._key(price)
        if best_ask is not None and key >= best_ask:
            return MboSide.ASK
        if best_bid is not None and key <= best_bid:
            return MboSide.BID
        return None

    def clear(self) -> None:
        self._orders.clear()
        self._bids.clear()
        self._asks.clear()

    # -- lecture --

    def best_bid(self) -> Optional[float]:
        key = self._best_key(MboSide.BID)
        return None if key is None else key * self.tick

    def best_ask(self) -> Optional[float]:
        key = self._best_key(MboSide.ASK)
        return None if key is None else key * self.tick

    def level(self, side: str, price: float) -> Optional[LevelState]:
        return self._side_map(side).get(self._key(price))

    def level_count(self, side: str) -> int:
        return len(self._side_map(side))

    def order_count(self) -> int:
        return len(self._orders)

    def side_of_order(self, order_id: int) -> Optional[str]:
        existing = self._orders.get(order_id)
        return existing.side if existing else None

    def cumulative_depth(self, side: str, levels: int) -> float:
        """Volume passif sur les N meilleurs niveaux VIVANTS (ce que F4 consomme)."""
        alive = [(key, lvl) for key, lvl in self._side_map(side).items() if lvl.size > 0]
        alive.sort(key=lambda item: item[0], reverse=(side == MboSide.BID))
        return sum(lvl.size for _, lvl in alive[:max(0, levels)])

    def to_aggregated_book(self, depth: int = 10) -> Any:
        """Projection vers le carnet agrégé du simulateur FIFO (D-078). **C'est la jonction de
        P3** : la file d'attente cesse d'être une déduction et devient la profondeur réellement
        observée dans le flux MBO."""
        from ..execution_sim import Book, BookLevel

        def side_levels(side: str) -> tuple:
            alive = [(key, lvl) for key, lvl in self._side_map(side).items() if lvl.size > 0]
            alive.sort(key=lambda item: item[0], reverse=(side == MboSide.BID))
            return tuple(BookLevel(key * self.tick, lvl.size) for key, lvl in alive[:depth])

        return Book(bids=side_levels(MboSide.BID), asks=side_levels(MboSide.ASK))
