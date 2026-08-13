"""Câblage des boucles réellement branchées (D-075).

`registry.py` DÉCLARE les cinq boucles ; ce module en câble **deux** — `options.sync` (L2) et
`ui.broadcast` (L5). Les trois autres restent `NOT_IMPLEMENTED`, donc visibles comme telles
dans la projection de santé : une capacité annoncée et absente n'est pas un état neutre.

**Pourquoi le tick de L2 publie même quand il échoue.** Le rafraîchissement lève sur panne (afin
que la boucle compte l'échec, cf. `options_context`), mais la publication est dans un `finally` :
sans elle, une source qui tombe laisserait l'UI sur le dernier contexte reçu, **figé et d'allure
fraîche**. C'est exactement l'inverse du but. La projection est calculée depuis l'âge du cache,
donc elle bascule d'elle-même en `STALE` puis le dit. L'échec, lui, remonte quand même.

**Pourquoi la santé des boucles n'est pas publiée à chaque tick.** À 0,25 s, ce serait 4
messages/s dont le contenu ne change quasiment jamais. On publie sur **changement d'état**
(RUNTIME_LOOPS Loop B, *dirty flag*), plus un rappel périodique pour que l'âge affiché ne se
fige pas entre deux changements.

**Limite connue et assumée** : c'est `ui.broadcast` qui publie la santé. Si elle meurt, la santé
cesse d'être poussée — le client le voit au silence du canal, pas par un message. Un watchdog
externe (Loop G) est le vrai remède ; il n'est pas dans cette tranche.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Optional

from ..es_bars import EsBarAggregator, EsBarsUnavailable, last_trade_price
from ..o5_tail_risk import O5_CONFIG_PLACEHOLDER, evaluate_o5
from .registry import CORE_TICK, GATES_EVAL, O5_KURTOSIS, OPTIONS_SYNC, UI_BROADCAST
from .supervisor import LoopSupervisor

#: Rappel périodique de la santé même sans changement d'état, pour que l'âge affiché côté client
#: ne se fige pas. PLACEHOLDER — compromis lisibilité/bruit, pas une valeur mesurée.
HEALTH_REPUBLISH_SECONDS = 2.0


def _fingerprint(snapshot: dict[str, Any]) -> str:
    """Ce qui constitue un CHANGEMENT d'état. Volontairement sans les âges ni les compteurs de
    ticks : ils bougent à chaque tour, et les inclure reviendrait à publier en continu — donc à
    n'avoir aucun *dirty flag* du tout."""
    return json.dumps([[e["name"], e["status"], e["failures"], e["timeouts"], e["drops"] > 0]
                       for e in snapshot["loops"]], sort_keys=True)


def build_o5_tick(read_tape: Callable[[], Any], aggregator: EsBarAggregator, broadcaster: Any, *,
                  clock: Optional[Callable[[], float]] = None,
                  evaluate: Callable[..., dict] = evaluate_o5,
                  o5_config: Optional[dict] = None) -> Callable[[], Any]:
    """Le tick de L3 (D-077) : échantillonner, et ne recalculer QU'À la clôture d'une barre.

    **Le calcul est DÉPORTÉ (`asyncio.to_thread`)** — c'est la raison d'être de cette boucle. Le
    kurtosis est du CPU synchrone : exécuté sur le fil de la boucle d'événements, il la gèle
    avant tout point d'attente, et gèle donc `core.tick` avec elle (piège Python nommé en tête de
    `RUNTIME_LOOPS.md`). Le plafond de durée du contrat borne l'attente ; il ne rend pas le
    calcul non bloquant — seul le déport le fait.

    Recalculer à chaque échantillon serait douze fois le travail pour la même réponse : entre
    deux clôtures, la fenêtre n'a pas changé.

    Lève `EsBarsUnavailable` si le tape ne donne aucun prix exploitable, pour que la boucle
    COMPTE l'échec plutôt que de battre dans le vide (doctrine D-075).
    """
    now = clock or time.time
    cfg = o5_config if o5_config is not None else O5_CONFIG_PLACEHOLDER

    async def tick() -> None:
        price = last_trade_price(read_tape())
        if price is None:
            raise EsBarsUnavailable("tape_not_fresh")
        if not aggregator.observe(price, now()):
            return                                    # barre en formation : rien à recalculer
        bars = list(aggregator.bars)
        result = await asyncio.to_thread(evaluate, bars, cfg, now() * 1000.0)
        broadcaster.publish("options", "o5_tail_risk", result)

    return tick


def build_gates_tick(read_snapshot: Callable[[], Any], read_bars: Callable[[], Any],
                     read_book: Callable[[], Any], broadcaster: Any, *,
                     append: Optional[Callable[[dict], Any]] = None,
                     clock: Optional[Callable[[], float]] = None,
                     tick_size: float = 0.25) -> Callable[[Any], Any]:
    """Le tick de L4 (D-080) : **événementiel**, déclenché par l'armement d'un manifeste.

    Aucune cadence propre — une L4 périodique réévaluerait le PASSÉ (piège D-052). Aucun pouvoir
    de blocage non plus : elle est appelée APRÈS que le manifeste existe, donc après que les
    contrôles déterministes ont statué (mode G2).
    """
    from ..gates_journal import evaluate_at_arming

    now = clock or time.time

    async def tick(manifest: Any) -> None:
        entry = evaluate_at_arming(manifest, options_snapshot=read_snapshot(),
                                   es_bars=read_bars(), book=read_book(),
                                   now_ms=now() * 1000.0, tick_size=tick_size)
        if entry is None:
            return                                    # manifeste illisible : rien de mesuré
        if append is not None:
            append(entry)
        # `replay=False` : une entrée de journal est un ÉVÉNEMENT daté. La rejouer pour hydrater
        # un abonné neuf lui présenterait un setup d'avant sa connexion comme s'il venait
        # d'être armé (même doctrine que `trade_manifest`, D-046).
        broadcaster.publish("options", "options_gates", entry, replay=False)

    return tick


def build_supervisor(reader: Any, broadcaster: Any, *,
                     read_tape: Optional[Callable[[], Any]] = None,
                     read_book: Optional[Callable[[], Any]] = None,
                     journal_append: Optional[Callable[[dict], Any]] = None,
                     clock: Optional[Callable[[], float]] = None) -> LoopSupervisor:
    """Monte le superviseur. `reader` est un `OptionsContextReader` ; `read_tape` rend le champ
    `tape` du ContextSchema (L3 reste câblée seulement si une source de prints est fournie —
    sans elle, `o5.kurtosis` demeure honnêtement `NOT_IMPLEMENTED`) ; `read_book` rend le carnet
    agrégé courant pour l'estimation de file d'attente de L4."""
    now = clock or time.time
    sup = LoopSupervisor(clock=now)
    state: dict[str, Any] = {"fingerprint": None, "last_publish": 0.0}

    async def options_tick() -> None:
        try:
            await reader.refresh()
        finally:
            # TOUJOURS publier l'état honnête du contexte — y compris (surtout) quand il vient
            # de se dégrader. Sans ce `finally`, une source morte laisserait le dernier contexte
            # affiché comme s'il était frais.
            broadcaster.publish("options", "options_context", reader.to_event(now()))

    async def broadcast_tick() -> None:
        snapshot = sup.health(now())
        fingerprint = _fingerprint(snapshot)
        elapsed = now() - state["last_publish"]
        if fingerprint == state["fingerprint"] and elapsed < HEALTH_REPUBLISH_SECONDS:
            return
        state["fingerprint"] = fingerprint
        state["last_publish"] = now()
        # `replay=False` : la santé est DATÉE. La rejouer pour hydrater un abonné neuf lui
        # servirait un âge d'avant sa connexion — un état, ça se rejoue ; une mesure, non.
        broadcaster.publish("options", "loops_health", snapshot, replay=False)

    o5_tick = (build_o5_tick(read_tape, EsBarAggregator(), broadcaster, clock=now)
               if read_tape is not None else None)

    o5_agg = EsBarAggregator()
    o5_tick = (build_o5_tick(read_tape, o5_agg, broadcaster, clock=now)
               if read_tape is not None else None)
    # L4 lit les MÊMES barres que L3 : deux tampons divergeraient, et O5 au journal ne serait
    # plus celui diffusé sur le canal.
    gates_tick = build_gates_tick(
        lambda: reader.snapshot(now()), lambda: list(o5_agg.bars),
        read_book if read_book is not None else (lambda: None),
        broadcaster, append=journal_append, clock=now)

    sup.register(CORE_TICK)                       # déjà assurée par engine.py — migration = refactor
    sup.register(OPTIONS_SYNC, options_tick)
    sup.register(O5_KURTOSIS, o5_tick)
    sup.register(GATES_EVAL, gates_tick)
    sup.register(UI_BROADCAST, broadcast_tick)
    return sup
