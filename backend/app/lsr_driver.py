"""LsrLiveDriver — harnais PUSH-DRIVEN du moteur LSR (D-052).

Port Python du `LsrLiveDriver` TypeScript (moteur LSR v1.2, externe), **durci** par la revue de
son original. Il n'exécute rien et n'émet rien de lui-même : il cadence une fonction
d'évaluation INJECTÉE (`evaluator`) sur des snapshots poussés, et remet le résultat à des
callbacks. Aucun ordre (§2.1) — la responsabilité courtier reste hors de ce module, comme dans
l'original.

**Positionnement dans Cholismo (important).** Le chemin d'émission LIVE reste
`Engine._maybe_emit_lsr` (D-046) : il TIRE la microstructure du ContextSchema sur la cadence
sweep. Ce driver est l'autre modèle — on POUSSE des snapshots depuis un flux temps réel
(Rithmic/NT8) — et il est fourni comme harnais pour ce jour-là. **Les deux ne doivent jamais
tourner ensemble** : deux chemins d'émission concurrents casseraient la source unique de vérité.
Il n'est donc PAS câblé dans `main.py`.

**Les cinq correctifs par rapport à l'original TypeScript :**

1. **Injections ESTAMPILLÉES + péremption STRICTE.** La boucle `setInterval` de l'original était
   présentée comme un « fail-safe » : elle était en réalité **fail-OPEN**. Les snapshots y sont
   gardés indéfiniment, donc un feed mort laissait le driver réévaluer toutes les 250 ms sur des
   données fossiles — avec un `now` frais, le moteur ne pouvait pas voir la différence. Ici,
   chaque `update_*` porte un `ts` et :
   - marché ou compte PÉRIMÉ (ou daté du FUTUR, leçon D-050) → **aucune évaluation** ;
   - order flow périmé → passé à `None`, car une mesure absente est fail-closed côté gates
     B1-B4 : c'est au moteur de refuser, pas au driver de mentir en la relayant ;
   - seuils : `LSR_DRIVER_MAX_AGE_S` (marché/order flow) et `ACCOUNT_MAX_AGE_S` (compte — la
     doctrine déjà établie en D-047/048, réutilisée telle quelle).

2. **Callbacks BORNÉS.** L'original appelait `this.options.onStateUpdated?.(...)` sans `await`
   ni `.catch` alors que le type autorise `Promise<void>` : un rejet devenait une *unhandled
   rejection*, fatale sous Node ≥ 15 (un Redis qui hoquette tuait le driver). Ici tout callback
   — sync ou coroutine — est awaité sous `try/except` : la boucle survit, et l'échec est
   JOURNALISÉ (une panne se voit ; c'est un échec inattendu, pas un rejet naturel — hygiène
   D-046).

3. **Persistance AVANT avancement de l'état.** L'original faisait `this.runtimeState = nextState`
   puis lançait la persistance : une écriture ratée laissait la mémoire en avance sur le durable,
   et le redémarrage repartait d'un état faux. Ici, si `persist_state` échoue, **l'état
   n'avance pas** — le moteur étant déterministe, l'évaluation suivante recalcule le même
   `next_state` et réessaie l'écriture (convergence naturelle, sans file de retry).

4. **Comparaison d'état STRUCTURELLE.** L'original faisait `JSON.stringify(a) !== JSON.stringify(b)`
   à chaque évaluation : deux sérialisations complètes (allocation pure sur un chemin appelé des
   centaines de fois par seconde) **et** sensible à l'ordre des clés — un même contenu construit
   dans un autre ordre déclenchait une fausse mutation. `!=` compare les champs : exact,
   insensible à l'ordre, sans allocation.

5. **APPROVED et ALERT sur DEUX callbacks distincts.** L'original les faisait sortir par le même
   `onPlanGenerated`, en laissant au consommateur le soin de relire `plan.status` — un
   `onPlanGenerated: p => broker.submit(...)` exécutait donc sur une simple alerte. Deux
   callbacks rendent l'erreur IMPOSSIBLE plutôt que seulement documentée.

**Aussi :** `start()` est idempotent (l'original écrasait `this.timer`, fuyant le premier) ;
l'évaluation n'est plus déclenchée par chaque injection mais par la CADENCE (backpressure : une
évaluation par tick est inutile — le détecteur de sweep lui-même tourne à la seconde — et
non bornée) ; l'horloge est INJECTABLE (le driver est le seul propriétaire d'horloge du système,
et même là elle se contrôle en test) ; `record_trade_outcome` EXIGE un horodatage explicite,
là où le défaut `Date.now()` de l'original rendait les tests non déterministes.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import config

log = logging.getLogger("cholismo.lsr_driver")


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class LsrDriverPayload:
    """Ce que le driver remet à l'évaluateur — l'équivalent de `LsrInputPayload`. `now` est
    INJECTÉ (jamais lu par l'évaluateur), `order_flow` peut être `None` (mesure absente ou
    périmée → les gates la traitent en fail-closed)."""
    now: float
    market: Any
    account: Any
    order_flow: Optional[Any]
    state: Any


@dataclass(frozen=True)
class _Stamped:
    value: Any
    ts: float


class LsrLiveDriver:
    """Cadence une évaluation LSR sur des snapshots poussés (voir docstring du module)."""

    def __init__(self, evaluator: Callable[[LsrDriverPayload], tuple[Any, Any]],
                 initial_state: Any,
                 *,
                 on_plan_approved: Optional[Callable[[dict], Any]] = None,
                 on_alert: Optional[Callable[[dict], Any]] = None,
                 on_state_updated: Optional[Callable[[Any], Any]] = None,
                 persist_state: Optional[Callable[[Any], Any]] = None,
                 record_outcome: Optional[Callable[[Any, bool, float], Any]] = None,
                 poll_seconds: float = None,        # type: ignore[assignment]
                 max_age_s: float = None,           # type: ignore[assignment]
                 account_max_age_s: float = None,   # type: ignore[assignment]
                 clock: Optional[Callable[[], float]] = None):
        self._evaluator = evaluator
        self._state = initial_state
        self._on_approved = on_plan_approved
        self._on_alert = on_alert
        self._on_state_updated = on_state_updated
        self._persist = persist_state
        self._record_outcome = record_outcome
        self._poll_s = poll_seconds if poll_seconds is not None else config.LSR_DRIVER_POLL_SECONDS
        self._max_age_s = max_age_s if max_age_s is not None else config.LSR_DRIVER_MAX_AGE_S
        self._account_max_age_s = (account_max_age_s if account_max_age_s is not None
                                   else config.ACCOUNT_MAX_AGE_S)
        if clock is None:
            import time as _time
            clock = _time.time
        self._clock = clock
        self._market: Optional[_Stamped] = None
        self._account: Optional[_Stamped] = None
        self._order_flow: Optional[_Stamped] = None
        self._task: Optional[asyncio.Task] = None

    @property
    def state(self) -> Any:
        return self._state

    # -- injections : STOCKENT seulement (l'évaluation est cadencée, cf. backpressure) --

    def update_market(self, market: Any, ts: float) -> None:
        self._market = _Stamped(market, ts)

    def update_account(self, account: Any, ts: float) -> None:
        self._account = _Stamped(account, ts)

    def update_order_flow(self, order_flow: Any, ts: float) -> None:
        self._order_flow = _Stamped(order_flow, ts)

    # -- boucle de cadence --

    async def start(self) -> None:
        """Idempotent : un second appel ne crée PAS de boucle supplémentaire (l'original TS
        écrasait son timer et fuyait le premier)."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.evaluate_now()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Filet de dernier recours : `evaluate` capture déjà tout, mais la boucle ne
                # doit JAMAIS mourir sur un imprévu (RUNTIME_LOOPS).
                log.exception("LSR driver loop tick failed (fail-closed: no emission)")
            await asyncio.sleep(max(0.01, self._poll_s))

    async def evaluate_now(self) -> None:
        """Évalue à l'instant de l'horloge injectée."""
        await self.evaluate(self._clock())

    # -- cœur : fraîcheur, évaluation, état, callbacks --

    def _fresh(self, snap: Optional[_Stamped], now: float, max_age: float) -> bool:
        """Frais = présent, horodatage fini, ni dans le FUTUR (désync d'horloge source, leçon
        D-050/D-048), ni au-delà du seuil d'âge."""
        if snap is None or not _finite(snap.ts):
            return False
        return not (snap.ts > now or now - snap.ts > max_age)

    async def evaluate(self, now: Any) -> None:
        """Un cycle d'évaluation. Ne lève JAMAIS : toute défaillance (évaluateur, callback,
        persistance) est capturée — la boucle survit et rien n'est émis (fail-closed §3)."""
        if not _finite(now):
            return                                          # horloge douteuse → on n'évalue pas
        if not self._fresh(self._market, now, self._max_age_s):
            return                                          # feed marché mort/fossile → silence
        if not self._fresh(self._account, now, self._account_max_age_s):
            return                                          # compte fossile → à l'aveugle → non
        # Order flow périmé = mesure ABSENTE : on la retire plutôt que de relayer un fossile ;
        # les gates B1-B4 sont fail-closed sur mesure absente (c'est au moteur de refuser).
        flow = (self._order_flow.value
                if self._fresh(self._order_flow, now, self._max_age_s) else None)

        payload = LsrDriverPayload(now=now, market=self._market.value,   # type: ignore[union-attr]
                                  account=self._account.value,          # type: ignore[union-attr]
                                  order_flow=flow, state=self._state)
        try:
            plan, next_state = self._evaluator(payload)
        except Exception:
            log.exception("LSR evaluator raised (fail-closed: no plan, state untouched)")
            return

        await self._advance_state(next_state)
        await self._dispatch_plan(plan)

    async def _advance_state(self, next_state: Any) -> None:
        """Persistance AVANT avancement : une écriture ratée laisse l'état INCHANGÉ, donc pas de
        divergence mémoire/durable. Le moteur est déterministe → la tentative suivante recalcule
        le même état et réessaie."""
        if next_state == self._state:
            return                                          # comparaison structurelle, O(champs)
        if self._persist is not None and not await self._safe_call(self._persist, next_state):
            return                                          # durable en échec → on n'avance pas
        self._state = next_state
        await self._safe_call(self._on_state_updated, next_state)

    async def _dispatch_plan(self, plan: Any) -> None:
        """APPROVED et ALERT sur deux callbacks DISTINCTS — un consommateur ne peut plus exécuter
        sur une simple alerte par étourderie. Tout autre statut : silence."""
        if not isinstance(plan, dict):
            return
        status = plan.get("status")
        if status == "APPROVED":
            await self._safe_call(self._on_approved, plan)
        elif status == "ALERT":
            await self._safe_call(self._on_alert, plan)

    async def _safe_call(self, fn: Optional[Callable], *args: Any) -> bool:
        """Appelle un callback sync OU coroutine, toujours awaité, toujours borné. Rend False si
        le callback a échoué — c'est un échec INATTENDU (pas un rejet naturel) : il se journalise."""
        if fn is None:
            return True
        try:
            result = fn(*args)
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            log.exception("LSR driver callback failed (bounded: loop survives)")
            return False

    # -- issue de trade (F6) : horodatage EXPLICITE exigé --

    async def record_trade_outcome(self, *, won: bool, ts: float) -> None:
        """Enregistre l'issue d'un trade terminé (cooldown F6). `ts` est OBLIGATOIRE : le défaut
        `Date.now()` de l'original rendait les tests non déterministes et cassait la discipline
        d'horloge injectée du moteur."""
        if self._record_outcome is None or not _finite(ts):
            return
        try:
            next_state = self._record_outcome(self._state, won, ts)
        except Exception:
            log.exception("LSR record_outcome raised (fail-closed: state untouched)")
            return
        await self._advance_state(next_state)
