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

**Passe /devil (Loop 4) — six failles trouvées et fermées :**

A. **Cycle d'état SÉRIALISÉ.** `evaluate` et `record_trade_outcome` faisaient tous deux un
   read-modify-write de `_state` avec un `await` (persistance) AU MILIEU. Une perte enregistrée
   pendant qu'une évaluation attendait Redis était donc **écrasée** par l'état calculé avant la
   perte : cooldown F6 effacé, on retrade juste après une perte — fail-OPEN sur une règle de
   sécurité. Un verrou unique sérialise le cycle. Une évaluation concurrente est **droppée** (une
   en vol suffit ; deux émettraient deux fois le même ticket — strict drop D-045 T3, sans log car
   c'est un rejet naturel) ; une issue de trade, elle, **attend** son tour : on ne perd jamais un
   cooldown.

B. **Callbacks PLAFONNÉS.** Le fix 2 bornait les callbacks qui *lèvent*, pas ceux qui ne rendent
   jamais la main. Un `await` suspendu (socket Redis sans timeout côté client) pendait la boucle
   pour l'éternité : zéro évaluation, zéro log — **un driver mort ressemble à un driver calme**.
   `LSR_DRIVER_CALLBACK_TIMEOUT_S` transforme la pendaison en échec visible. Corollaire : un
   callback **synchrone** bloquant (`time.sleep`) reste indéfendable — il gèle la boucle avant
   tout point d'attente ; c'est un contrat de consommateur, pas un défaut du driver.

C. **Pas d'état durable → pas d'émission.** Le plan naît de la transition d'état ; le fix 3
   empêchait la mémoire d'avancer sans le durable, mais le plan sortait quand même. Au
   redémarrage, l'état revenait en arrière et le même sweep pouvait ré-émettre → doublon de
   ticket. L'émission est maintenant conditionnée à la cohérence de l'état (doctrine du journal
   D-045 : l'enregistrement précède l'acte).

D. **Comparaison d'état qui LÈVE.** `next_state != self._state` n'est pas toujours booléen — un
   état embarquant un `ndarray` lève « truth value of an array is ambiguous », et l'exception
   remontait à l'appelant en dehors de la boucle (contrat « ne lève jamais » rompu). Capturée :
   état incomparable = état non avancé = aucune émission.

E. **Boucle tuée de l'extérieur.** `if self._task is not None: return` rendait `start()`
   idempotent *et* impuissant : après une annulation externe (arrêt d'un TaskGroup, balayage de
   shutdown) la tâche est `done()` mais non-None, donc le driver restait **mort en silence**. Une
   boucle morte se signale et se relance. Symétriquement `stop()` ne propage plus l'exception
   d'une tâche déjà morte (`await task` la re-lève) : un arrêt gracieux n'explose pas.

F. **Horloge qui RECULE.** Un pas NTP arrière fait paraître tous les snapshots « datés du
   futur » : le driver se tait, ce qui est correct (§3), mais indéfiniment et sans trace. La
   régression ne *bloque* rien (c'est la fraîcheur qui décide) ; elle est **signalée une fois par
   épisode**, avec la reprise — à 4 ticks/s, un log par tick serait un flood (hygiène D-046).

**Ré-entrance :** un callback ne doit pas rappeler le driver. `evaluate_now()` depuis un callback
est droppé sans dommage (verrou déjà tenu) ; `await record_trade_outcome(...)` s'auto-bloquerait —
le plafond B le résout en échec journalisé plutôt qu'en pendaison, mais le contrat reste :
**un callback consomme, il ne pilote pas**.
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


def _death_reason(task: "asyncio.Task") -> str:
    """Pourquoi la boucle est morte — lu SANS lever : `task.exception()` explose sur une tâche
    annulée. Le lire ici évite aussi le « exception was never retrieved » à la collecte."""
    if task.cancelled():
        return "cancelled"
    exc = task.exception()
    return repr(exc) if exc is not None else "returned"


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
                 callback_timeout_s: float = None,  # type: ignore[assignment]
                 clock: Optional[Callable[[], float]] = None):
        self._evaluator = evaluator
        self._state = initial_state
        self._on_approved = on_plan_approved
        self._on_alert = on_alert
        self._on_state_updated = on_state_updated
        self._persist = persist_state
        self._record_outcome = record_outcome
        poll = poll_seconds if poll_seconds is not None else config.LSR_DRIVER_POLL_SECONDS
        # Cadence bornée UNE fois ici : `_poll_s` est ensuite une valeur sûre partout (une valeur
        # absurde en config ne doit pas se transformer en busy-wait).
        self._poll_s = max(0.01, poll) if _finite(poll) else config.LSR_DRIVER_POLL_SECONDS
        self._max_age_s = max_age_s if max_age_s is not None else config.LSR_DRIVER_MAX_AGE_S
        self._account_max_age_s = (account_max_age_s if account_max_age_s is not None
                                   else config.ACCOUNT_MAX_AGE_S)
        # Plafond callback : jamais désactivable (une valeur absurde retombe sur le défaut, un 0
        # ou un `inf` rouvrirait précisément la faille B).
        cb = (callback_timeout_s if callback_timeout_s is not None
              else config.LSR_DRIVER_CALLBACK_TIMEOUT_S)
        self._cb_timeout_s = (max(0.01, cb) if _finite(cb)
                              else config.LSR_DRIVER_CALLBACK_TIMEOUT_S)
        if clock is None:
            import time as _time
            clock = _time.time
        self._clock = clock
        self._market: Optional[_Stamped] = None
        self._account: Optional[_Stamped] = None
        self._order_flow: Optional[_Stamped] = None
        self._task: Optional[asyncio.Task] = None
        # Verrou du cycle d'état (faille A) : un seul read-modify-write de `_state` à la fois.
        self._gate = asyncio.Lock()
        self._now_high_water: Optional[float] = None
        self._clock_regressed = False

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
        """Idempotent tant que la boucle est VIVANTE : un second appel ne crée pas de boucle
        supplémentaire (l'original TS écrasait son timer et fuyait le premier). Mais une tâche
        morte — annulation externe, arrêt d'un TaskGroup — est `done()` sans être `None` : la
        garde naïve laissait alors le driver mort en silence. On la relance, et ça se voit."""
        task = self._task
        if task is not None and not task.done():
            return
        if task is not None:
            log.warning("LSR driver loop was dead (%s) — restarting", _death_reason(task))
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Idempotent et non propageant : `await task` re-lève l'exception d'une tâche déjà morte,
        ce qui faisait exploser l'arrêt gracieux au pire moment (RUNTIME_LOOPS §arrêt)."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        if task is asyncio.current_task():
            # `stop()` appelé DEPUIS la boucle (un callback qui demande l'arrêt) : s'attendre
            # soi-même lève « Task cannot await on itself ». L'annulation prendra effet au
            # prochain point d'attente ; il n'y a rien à attendre ici.
            return
        try:
            await task
        except asyncio.CancelledError:
            # Distinguer « la boucle s'est bien arrêtée » de « c'est MOI qu'on annule » : pendant un
            # shutdown, `await driver.stop()` peut lui-même être annulé, et l'avaler ferait croire
            # à l'appelant que son arrêt s'est déroulé normalement (Loop H).
            current = asyncio.current_task()
            if current is not None and current.cancelling() > 0:
                raise
        except Exception:
            log.exception("LSR driver loop had already died before stop()")

    async def _poll_loop(self) -> None:
        """Cadence à ÉCHÉANCE, pas « travail puis sieste fixe » : sinon la période réelle vaut
        `poll + durée du travail` et la cadence annoncée (250 ms) est un mensonge silencieux. On
        se recale sur l'horloge MONOTONE de la boucle (pas sur l'horloge injectée, qui est murale
        et peut faire un pas NTP).

        Aucun rattrapage : après un tick long, on se réancre à maintenant au lieu d'enchaîner les
        évaluations en retard — une rafale de rattrapage évaluerait le PASSÉ (doctrine D-045 T3)."""
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            try:
                await self.evaluate_now()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Filet de dernier recours : `evaluate` capture déjà tout, mais la boucle ne
                # doit JAMAIS mourir sur un imprévu (RUNTIME_LOOPS).
                log.exception("LSR driver loop tick failed (fail-closed: no emission)")
            next_at += self._poll_s
            delay = next_at - loop.time()
            if delay <= 0.0:
                next_at = loop.time()                       # en retard → on se réancre, pas de rafale
                delay = 0.001                               # mais on rend TOUJOURS la main (§busy-wait)
            await asyncio.sleep(delay)

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

    def _check_clock(self, now: float) -> None:
        """Visibilité d'une horloge qui RECULE (faille F). Ne bloque rien — c'est la fraîcheur qui
        décide, et un snapshot antérieur au recul paraît « daté du futur » donc refusé. Signale
        une fois par ÉPISODE (front descendant puis reprise) : à 4 ticks/s, un log par tick serait
        un flood, et un rejet naturel ne se journalise pas (hygiène D-046)."""
        high = self._now_high_water
        if high is not None and now < high:
            if not self._clock_regressed:
                self._clock_regressed = True
                log.warning("LSR driver clock went BACKWARDS (%.3f < %.3f) — evaluations stay "
                            "fail-closed until it catches up", now, high)
            return
        self._now_high_water = now
        if self._clock_regressed:
            self._clock_regressed = False
            log.info("LSR driver clock recovered (%.3f) — evaluations resume", now)

    async def evaluate(self, now: Any) -> None:
        """Un cycle d'évaluation. Ne lève JAMAIS (hors annulation, qui doit remonter) : toute
        défaillance — évaluateur, callback, persistance, comparaison d'état — est capturée, la
        boucle survit et rien n'est émis (fail-closed §3).

        Le cycle est SÉRIALISÉ (faille A) et une évaluation concurrente est DROPPÉE : une en vol
        suffit, deux émettraient deux fois le même ticket. Aucun log — c'est du backpressure
        normal, pas une panne."""
        if self._gate.locked():
            return
        async with self._gate:
            await self._evaluate_serialized(now)

    async def _evaluate_serialized(self, now: Any) -> None:
        if not _finite(now):
            return                                          # horloge douteuse → on n'évalue pas
        self._check_clock(now)
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

        # Pas d'état durable → pas d'émission (faille C) : le plan naît de la transition d'état ;
        # l'émettre sans que la transition tienne, c'est risquer un doublon de ticket au
        # redémarrage (l'état revenu en arrière laisserait le même sweep ré-émettre).
        if await self._advance_state(next_state):
            await self._dispatch_plan(plan)

    def _state_differs(self, next_state: Any) -> Optional[bool]:
        """`None` = état INCOMPARABLE (faille D) : `!=` n'est pas toujours booléen — un `ndarray`
        dans l'état lève « truth value of an array is ambiguous ». Incomparable → fail-closed."""
        try:
            return bool(next_state != self._state)
        except Exception:
            log.exception("LSR state comparison failed (fail-closed: state untouched, no emission)")
            return None

    async def _advance_state(self, next_state: Any) -> bool:
        """Rend True si l'état est COHÉRENT (inchangé, ou avancé et durable) — seul cas où une
        émission est légitime. Persistance AVANT avancement : une écriture ratée laisse l'état
        INCHANGÉ, donc pas de divergence mémoire/durable. Le moteur est déterministe → la
        tentative suivante recalcule le même état et réessaie."""
        differs = self._state_differs(next_state)
        if differs is None:
            return False
        if not differs:
            return True                                     # comparaison structurelle, O(champs)
        if self._persist is not None and not await self._safe_call(self._persist, "persist_state", next_state):
            return False                                    # durable en échec → on n'avance pas
        self._state = next_state
        # L'état est durable : une notification ratée ne le remet pas en cause (elle est
        # journalisée par `_safe_call`), l'émission reste légitime.
        await self._safe_call(self._on_state_updated, "on_state_updated", next_state)
        return True

    async def _dispatch_plan(self, plan: Any) -> None:
        """APPROVED et ALERT sur deux callbacks DISTINCTS — un consommateur ne peut plus exécuter
        sur une simple alerte par étourderie. Tout autre statut : silence."""
        if not isinstance(plan, dict):
            return
        status = plan.get("status")
        if status == "APPROVED":
            await self._safe_call(self._on_approved, "on_plan_approved", plan)
        elif status == "ALERT":
            await self._safe_call(self._on_alert, "on_alert", plan)

    async def _safe_call(self, fn: Optional[Callable], role: str, *args: Any) -> bool:
        """Appelle un callback sync OU coroutine, toujours awaité, toujours borné — en durée aussi
        (faille B) : un `await` qui ne rend jamais la main pendait la boucle pour l'éternité, en
        silence. Rend False si le callback a échoué : c'est un échec INATTENDU (pas un rejet
        naturel), il se journalise.

        `role` nomme le callback fautif : « la persistance a lâché » et « le ticket n'est pas
        parti » ne demandent pas la même intervention, et un log qui ne dit pas lequel des deux
        oblige à deviner."""
        if fn is None:
            return True
        try:
            result = fn(*args)
            if inspect.isawaitable(result):
                # `asyncio.timeout` et NON `asyncio.wait_for` : en 3.11, `wait_for` AVALE une
                # annulation venue de l'extérieur quand sa future interne vient de se terminer
                # (`except CancelledError: if fut.done(): return fut.result()`). La boucle
                # survivait alors à son propre `cancel()` et `stop()` attendait POUR TOUJOURS —
                # l'arrêt gracieux du terminal restait pendu (mesuré : ~1 arrêt sur 2).
                # `asyncio.timeout` distingue sa propre échéance d'une annulation externe.
                async with asyncio.timeout(self._cb_timeout_s):
                    await result
            return True
        except asyncio.TimeoutError:
            log.error("LSR driver callback %s TIMED OUT after %.2fs — treated as a failure "
                      "(fail-closed: state not advanced, nothing emitted)", role, self._cb_timeout_s)
            return False
        except Exception:
            log.exception("LSR driver callback %s failed (bounded: loop survives)", role)
            return False

    # -- issue de trade (F6) : horodatage EXPLICITE exigé --

    async def record_trade_outcome(self, *, won: bool, ts: float) -> None:
        """Enregistre l'issue d'un trade terminé (cooldown F6). `ts` est OBLIGATOIRE : le défaut
        `Date.now()` de l'original rendait les tests non déterministes et cassait la discipline
        d'horloge injectée du moteur.

        Contrairement à une évaluation, une issue de trade n'est JAMAIS droppée : elle ATTEND le
        verrou. Un cooldown perdu, c'est un trade de revanche autorisé (faille A)."""
        if self._record_outcome is None or not _finite(ts):
            return
        async with self._gate:
            try:
                next_state = self._record_outcome(self._state, won, ts)
            except Exception:
                log.exception("LSR record_outcome raised (fail-closed: state untouched)")
                return
            await self._advance_state(next_state)
