"""Harnais de rejeu bout-en-bout : MBO → armement → simulateur → PnL réalisé (D-081, P3).

Ferme la boucle du PnL. Les modules existaient tous ; il manquait le fil qui les relie :

    événements MBO (D-079) → carnet L2/L3 → armement → simulateur FIFO (D-078) → Outcome

**`NO_FILL` est une issue de PREMIÈRE CLASSE, et c'est tout l'intérêt du harnais.** Un setup
parfaitement valide dont l'entrée limite n'est jamais servie n'est ni un gain ni une perte : il
n'a pas eu lieu. C'est exactement ce qu'un backtest « rempli au touché » transforme en gagnant,
et ce que `CLAUDE.md` §5 de l'artefact désigne comme le biais le plus coûteux du scalping. Le
compter comme un trade neutre serait déjà un mensonge — il faut pouvoir dire **combien** de
setups n'auraient jamais été pris.

**L'issue est un event ULTÉRIEUR qui référence l'armement** (`CLAUDE §2.5`, D-045, D-080) :
`Outcome.setup_id` pointe vers l'entrée de journal écrite par L4. Le harnais ne réécrit jamais
la décision, il ajoute son résultat.

**Aucun ordre réel (§2.1)** : tout passe par `ExecutionSimulator`, qui n'a aucune dépendance
réseau.

---

**Mécanique par événement.** Le carnet est incrémenté, puis un échange est présenté au
simulateur — dans cet ordre, parce qu'un ordre placé à cet instant doit voir le carnet AVANT que
l'échange courant ne le consomme, sinon il hériterait d'une file déjà servie.

**Sortie au stop : ordre au MARCHÉ.** Un stop n'est pas une limite — quand le prix le traverse,
on sort en payant le carnet. Le slippage de sortie est donc la consommation réelle des niveaux,
pas zéro. Le TP, lui, est une limite : il repasse par la file FIFO et peut ne jamais être servi.

**Unités.** Les horodatages MBO sont en nanosecondes entières ; le simulateur raisonne en
millisecondes. La conversion ns → ms produit un flottant de l'ordre de 1,7 × 10¹² — très en
dessous de 2⁵³, donc exacte à la microseconde près. L'ordre de rejeu, lui, reste porté par
l'itération sur les événements entiers, jamais par ce flottant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from .execution_sim import ExecutionSimulator, OrderStatus
from .mbo.book import MboBook
from .mbo.events import MboAction, MboEvent

#: Issues possibles. `NO_FILL` et `OPEN_AT_END` ne sont PAS des résultats nuls : ce sont des
#: absences de trade, et les fondre dans un PnL de 0 fausserait toute statistique en aval.
OUTCOME_STATUSES = ("NO_FILL", "WIN", "LOSS", "OPEN_AT_END")


@dataclass(frozen=True)
class Setup:
    """Ce qu'un armement produit. `setup_id` fait le lien avec l'entrée de journal de L4."""
    setup_id: str
    side: str                      # LONG | SHORT
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float = 1.0
    armed_ts_ms: float = 0.0


@dataclass(frozen=True)
class Outcome:
    setup_id: str
    status: str
    entry_fill_price: Optional[float] = None
    entry_fill_ts_ms: Optional[float] = None
    #: File d'attente AU MOMENT DE L'ARMEMENT — instantané immuable. C'est la covariable
    #: utile à la calibration (« à quelle profondeur étions-nous ? ») ; la file du
    #: simulateur, elle, se décrémente au fil des échanges et ne dirait plus rien après coup.
    entry_queue_ahead: Optional[float] = None
    #: Ce qu'il restait devant nous à la fin — dit à quel point on est passé près.
    entry_queue_remaining: Optional[float] = None
    exit_price: Optional[float] = None
    exit_ts_ms: Optional[float] = None
    exit_reason: Optional[str] = None          # TP | SL | SESSION_END
    pnl_ticks: Optional[float] = None
    pnl_usd: Optional[float] = None
    exit_slip_ticks: Optional[float] = None

    def as_event(self) -> dict[str, Any]:
        """Projection pour l'`OutcomeEvent` du journal append-only — il RÉFÉRENCE l'armement,
        il ne le réécrit pas."""
        return {"setup_id": self.setup_id, "status": self.status,
                "entry_fill_price": self.entry_fill_price,
                "entry_fill_ts_ms": self.entry_fill_ts_ms,
                "entry_queue_ahead": self.entry_queue_ahead,
                "entry_queue_remaining": self.entry_queue_remaining,
                "exit_price": self.exit_price, "exit_ts_ms": self.exit_ts_ms,
                "exit_reason": self.exit_reason, "pnl_ticks": self.pnl_ticks,
                "pnl_usd": self.pnl_usd, "exit_slip_ticks": self.exit_slip_ticks}


def _ms(ts_ns: int) -> float:
    return ts_ns / 1_000_000.0


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class _ActiveTrade:
    """État d'un setup en cours. Volontairement une classe et non un tuple : le cycle a des
    transitions (armé → entré → sorti) et les rendre explicites vaut mieux qu'un drapeau."""

    def __init__(self, setup: Setup, entry_order: Any):
        self.setup = setup
        self.entry_order = entry_order
        # Capturé À L'ARMEMENT : `entry_order.queue_ahead` est mutable et sera décrémenté.
        self.queue_at_arming = entry_order.queue_ahead
        self.entry_fill: Optional[Any] = None
        self.tp_order: Optional[Any] = None


class ReplayHarness:
    """Rejoue un flux MBO et rend une issue par setup armé."""

    def __init__(self, *, tick_size: float = 0.25, point_value: float = 5.0,
                 latency_ms: float = 0.0, latency_jitter_ms: float = 0.0, rng_seed: int = 0,
                 max_levels_per_side: int = 512):
        self.tick = float(tick_size)
        #: Valeur d'un TICK = valeur du point × taille du tick (MES : 5,0 × 0,25 = 1,25 $).
        self.tick_value = float(point_value) * self.tick
        self.book = MboBook(tick_size=self.tick, max_levels_per_side=max_levels_per_side)
        self.sim = ExecutionSimulator(tick_size=self.tick, latency_ms=latency_ms,
                                      latency_jitter_ms=latency_jitter_ms, rng_seed=rng_seed)
        self.outcomes: list[Outcome] = []
        self._active: Optional[_ActiveTrade] = None

    # -- boucle de rejeu --

    def run(self, events: Iterable[MboEvent],
            arm: Callable[[MboBook, MboEvent], Optional[Setup]]) -> list[Outcome]:
        """Rejoue le flux. `arm` est INJECTÉ : le harnais ne décide pas quand un setup se
        déclenche, il mesure ce qui arrive à ceux qu'on lui donne. C'est ce qui permet de le
        tester sans embarquer tout le détecteur de sweep, et de changer de détecteur sans
        toucher au harnais."""
        last_ts_ms = 0.0
        for event in events:
            last_ts_ms = _ms(event.ts_event)
            # ORDRE VOULU : le carnet d'abord, l'échange ensuite. Un ordre placé à cet instant
            # doit voir la liquidité AVANT que l'échange courant ne la consomme — sinon il
            # hériterait d'une file déjà servie, donc d'un avantage qui n'existait pas.
            self.book.apply(event)

            if self._active is None:
                setup = arm(self.book, event)
                if setup is not None:
                    self._arm(setup, last_ts_ms)

            if event.action in (MboAction.TRADE, MboAction.FILL):
                self._on_trade(event, last_ts_ms)

        self._close_open(last_ts_ms)
        return self.outcomes

    # -- transitions --

    def _arm(self, setup: Setup, ts_ms: float) -> None:
        side = "BUY" if setup.side == "LONG" else "SELL"
        order = self.sim.place_limit(side, setup.entry_price, setup.qty, ts_ms,
                                     book=self.book.to_aggregated_book(depth=20))
        if order is None:
            # Carnet inexploitable → le simulateur refuse (D-078). Aucune issue n'est inventée :
            # on ne peut pas dire ce qu'un ordre aurait fait dans un carnet qu'on n'a pas vu.
            self.outcomes.append(Outcome(setup_id=setup.setup_id, status="NO_FILL"))
            return
        self._active = _ActiveTrade(setup, order)

    def _on_trade(self, event: MboEvent, ts_ms: float) -> None:
        fills = self.sim.on_trade(ts_ms, event.price, event.size)
        active = self._active
        if active is None:
            return

        if active.entry_fill is None:
            entry = next((f for f in fills if f.order_id == active.entry_order.id), None)
            if entry is not None:
                active.entry_fill = entry
                self._place_take_profit(active, ts_ms)
            return

        # En position : le stop prime sur le TP. Si le prix traverse le stop, on sort au marché
        # même si le TP aurait pu être servi au même instant — on ne s'accorde pas le meilleur
        # des deux (biais d'optimisme sur les barres ambiguës).
        if self._stop_hit(active.setup, event.price):
            self._exit_at_market(active, ts_ms)
            return
        tp = next((f for f in fills if active.tp_order is not None
                   and f.order_id == active.tp_order.id), None)
        if tp is not None and active.tp_order.status is OrderStatus.FILLED:
            self._settle(active, tp.price, ts_ms, "TP", 0.0)

    def _place_take_profit(self, active: _ActiveTrade, ts_ms: float) -> None:
        """Le TP est une LIMITE : il repasse par la file FIFO et peut ne jamais être servi.
        C'est précisément ce qu'un backtest naïf compte comme gagné d'avance."""
        side = "SELL" if active.setup.side == "LONG" else "BUY"
        active.tp_order = self.sim.place_limit(side, active.setup.take_profit, active.setup.qty,
                                               ts_ms,
                                               book=self.book.to_aggregated_book(depth=20))

    def _stop_hit(self, setup: Setup, price: float) -> bool:
        if not _finite(price):
            return False
        return (price <= setup.stop_loss if setup.side == "LONG"
                else price >= setup.stop_loss)

    def _exit_at_market(self, active: _ActiveTrade, ts_ms: float) -> None:
        """Un stop n'est PAS une limite : on sort en payant le carnet. Le slippage de sortie est
        la consommation réelle des niveaux, jamais zéro."""
        if active.tp_order is not None:
            self.sim.cancel(active.tp_order.id, "RISK_HALT", ts_ms)   # protection : jamais bloquée
        side = "SELL" if active.setup.side == "LONG" else "BUY"
        fill = self.sim.market_order(side, active.setup.qty,
                                     self.book.to_aggregated_book(depth=20), ts_ms)
        if fill.price is None:
            # Carnet vide au moment de sortir : on ne fabrique pas un prix de sortie. La
            # position reste ouverte à la fin du flux, et le dira.
            return
        self._settle(active, fill.price, ts_ms, "SL", fill.slip_ticks)

    def _settle(self, active: _ActiveTrade, exit_price: float, ts_ms: float, reason: str,
                slip: float) -> None:
        setup = active.setup
        entry_price = active.entry_fill.price
        direction = 1.0 if setup.side == "LONG" else -1.0
        pnl_ticks = direction * (exit_price - entry_price) / self.tick
        self.outcomes.append(Outcome(
            setup_id=setup.setup_id,
            status="WIN" if pnl_ticks > 0 else "LOSS",
            entry_fill_price=entry_price, entry_fill_ts_ms=active.entry_fill.ts_ms,
            entry_queue_ahead=active.queue_at_arming,
            entry_queue_remaining=active.entry_order.queue_ahead,
            exit_price=exit_price, exit_ts_ms=ts_ms, exit_reason=reason,
            pnl_ticks=pnl_ticks, pnl_usd=pnl_ticks * self.tick_value * setup.qty,
            exit_slip_ticks=slip))
        self._active = None

    def _close_open(self, ts_ms: float) -> None:
        """Fin du flux. Deux cas, tenus DISTINCTS : jamais entré (`NO_FILL`) et entré sans être
        sorti (`OPEN_AT_END`). Les fondre en un PnL de 0 fausserait toute statistique en aval —
        une absence de trade n'est pas un trade nul."""
        active = self._active
        if active is None:
            return
        if active.entry_fill is None:
            self.outcomes.append(Outcome(
                setup_id=active.setup.setup_id, status="NO_FILL",
                entry_queue_ahead=active.queue_at_arming,
                entry_queue_remaining=active.entry_order.queue_ahead))
        else:
            self.outcomes.append(Outcome(
                setup_id=active.setup.setup_id, status="OPEN_AT_END",
                entry_fill_price=active.entry_fill.price,
                entry_fill_ts_ms=active.entry_fill.ts_ms,
                entry_queue_ahead=active.queue_at_arming,
                entry_queue_remaining=active.entry_order.queue_ahead,
                exit_ts_ms=ts_ms))
        self._active = None


def summarize(outcomes: Iterable[Outcome]) -> dict[str, Any]:
    """Bilan d'un rejeu. Le **taux de non-remplissage** est remonté au même rang que le taux de
    réussite : c'est la mesure que P3 existe pour produire, et celle qu'un backtest naïf
    n'affiche jamais parce qu'il vaut structurellement zéro chez lui.

    Le taux de réussite est calculé sur les trades RÉELLEMENT PRIS — inclure les `NO_FILL` au
    dénominateur mélangerait deux questions distinctes : « la stratégie gagne-t-elle ? » et
    « les entrées sont-elles servies ? »."""
    items = list(outcomes)
    total = len(items)
    by_status = {status: sum(1 for o in items if o.status == status)
                 for status in OUTCOME_STATUSES}
    settled = [o for o in items if o.status in ("WIN", "LOSS")]
    wins = sum(1 for o in settled if o.status == "WIN")
    return {
        "setups": total,
        "by_status": by_status,
        "no_fill_rate": (by_status["NO_FILL"] / total) if total else None,
        "settled": len(settled),
        # `None` plutôt qu'un 0 trompeur quand rien n'a été pris : « 0 % de réussite » et
        # « aucun trade » ne veulent pas dire la même chose (§3).
        "win_rate": (wins / len(settled)) if settled else None,
        "pnl_usd": sum(o.pnl_usd or 0.0 for o in settled) if settled else None,
        "avg_exit_slip_ticks": (sum(o.exit_slip_ticks or 0.0 for o in settled) / len(settled)
                                if settled else None),
    }
