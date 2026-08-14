"""Feature — LsrLiveDriver : harnais push-driven du moteur LSR (D-052).

Port Python du `LsrLiveDriver` TypeScript, avec les cinq correctifs de la revue :
1. **injections ESTAMPILLÉES + péremption stricte** — la boucle périodique du driver TS était
   fail-OPEN : elle réévaluait indéfiniment sur un snapshot fossile. Ici, marché ou compte
   périmé → AUCUNE évaluation ; order flow périmé → passé à `None` (les gates B1-B4 sont
   fail-closed sur mesure absente) ; snapshot daté du FUTUR → refusé (leçon D-050) ;
2. **callbacks BORNÉS** — un callback qui lève (ou une coroutine qui rejette) ne tue jamais la
   boucle : capturé, journalisé (une panne se voit), l'évaluation suivante a lieu ;
3. **persistance AVANT avancement** — si l'écriture durable échoue, l'état en mémoire N'AVANCE
   PAS : pas de divergence mémoire/Redis au redémarrage. Le moteur étant déterministe, la
   tentative suivante recalcule le même état et réessaie ;
4. **comparaison d'état structurelle** (`!=`), pas `JSON.stringify` ×2 par tick : exacte,
   insensible à l'ordre des clés, sans allocation ;
5. **APPROVED et ALERT sur DEUX callbacks distincts** — un consommateur ne peut plus exécuter
   sur une simple alerte par étourderie.
Plus : `start()` idempotent (le TS fuyait un timer), horloge INJECTÉE partout.
"""
import asyncio
import logging
import time

import pytest

from app import config
from app.lsr_driver import LsrLiveDriver

MARKET = {"last": 5000.0}
ACCOUNT = {"equity": 50_000.0}
FLOW = {"absorption": True}


def _plan(status="APPROVED"):
    return {"status": status, "instrument": "MES", "direction": "LONG",
            "executionPlan": {"entryType": "LIMIT", "entryPrice": 5000.0,
                              "stopLoss": 4999.25, "takeProfit": 5001.25, "contracts": 1}}


class _Spy:
    """Évaluateur espion — enregistre les payloads reçus et rend un plan programmé."""

    def __init__(self, plan=None, next_state=None, raises=None):
        self.calls = []
        self._plan = plan
        self._next = next_state
        self._raises = raises

    def __call__(self, payload):
        self.calls.append(payload)
        if self._raises is not None:
            raise self._raises
        return self._plan, (self._next if self._next is not None else payload.state)


def _driver(evaluator, **over):
    kw = dict(initial_state={"v": 1}, clock=lambda: 1_000.0)
    kw.update(over)
    return LsrLiveDriver(evaluator, **kw)


def _feed(d, *, now=1_000.0, market_age=0.0, account_age=0.0, flow_age=None):
    d.update_market(MARKET, ts=now - market_age)
    d.update_account(ACCOUNT, ts=now - account_age)
    if flow_age is not None:
        d.update_order_flow(FLOW, ts=now - flow_age)


# --- 1. Péremption stricte : la boucle n'est plus fail-OPEN ----------------------------------

def test_evaluation_nominale_payload_complet():
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    _feed(d, flow_age=0.0)
    asyncio.run(d.evaluate(1_000.0))
    assert len(spy.calls) == 1
    p = spy.calls[0]
    assert p.now == 1_000.0 and p.market is MARKET and p.account is ACCOUNT
    assert p.order_flow is FLOW and p.state == {"v": 1}


def test_sans_marche_ou_sans_compte_aucune_evaluation():
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    asyncio.run(d.evaluate(1_000.0))                        # rien injecté
    d.update_market(MARKET, ts=1_000.0)
    asyncio.run(d.evaluate(1_000.0))                        # compte manquant
    assert spy.calls == []


def test_marche_PERIME_aucune_evaluation():
    """LE correctif central : le driver TS réévaluait toutes les 250 ms sur un snapshot fossile."""
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    _feed(d, market_age=config.LSR_DRIVER_MAX_AGE_S + 0.1)
    asyncio.run(d.evaluate(1_000.0))
    assert spy.calls == []                                  # feed mort → on ne trade pas à l'aveugle


def test_compte_PERIME_aucune_evaluation():
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    _feed(d, account_age=config.ACCOUNT_MAX_AGE_S + 1)      # doctrine compte D-047
    asyncio.run(d.evaluate(1_000.0))
    assert spy.calls == []


def test_order_flow_PERIME_degrade_en_None_sans_bloquer():
    """Une mesure d'order flow périmée est ABSENTE (les gates B1-B4 sont fail-closed dessus) —
    mais elle ne doit pas empêcher l'évaluation : c'est au moteur de refuser."""
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    _feed(d, flow_age=config.LSR_DRIVER_MAX_AGE_S + 0.1)
    asyncio.run(d.evaluate(1_000.0))
    assert len(spy.calls) == 1 and spy.calls[0].order_flow is None


def test_snapshot_date_du_FUTUR_refuse():
    """Désync d'horloge source : un `ts` postérieur à `now` resterait « frais » indéfiniment
    (leçon D-050/D-048)."""
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    _feed(d, market_age=-3600.0)                            # marché daté dans une heure
    asyncio.run(d.evaluate(1_000.0))
    assert spy.calls == []


def test_horloge_non_finie_aucune_evaluation():
    spy = _Spy(plan=_plan())
    d = _driver(spy)
    _feed(d)
    for bad in (float("nan"), float("inf"), None):
        asyncio.run(d.evaluate(bad))
    assert spy.calls == []


# --- 5. APPROVED et ALERT séparés ------------------------------------------------------------

def test_approved_et_alert_sur_des_callbacks_DISTINCTS():
    approved, alerts = [], []
    for status, n_appr, n_alert in [("APPROVED", 1, 0), ("ALERT", 0, 1), ("REJECTED", 0, 0)]:
        approved.clear()
        alerts.clear()
        spy = _Spy(plan=_plan(status))
        d = _driver(spy, on_plan_approved=approved.append, on_alert=alerts.append)
        _feed(d)
        asyncio.run(d.evaluate(1_000.0))
        assert (len(approved), len(alerts)) == (n_appr, n_alert), status


def test_plan_absent_ou_malforme_aucun_callback():
    approved, alerts = [], []
    for plan in (None, {}, "APPROVED", 42):
        spy = _Spy(plan=plan)
        d = _driver(spy, on_plan_approved=approved.append, on_alert=alerts.append)
        _feed(d)
        asyncio.run(d.evaluate(1_000.0))
    assert approved == [] and alerts == []


# --- 3./4. État : persistance AVANT avancement, comparaison structurelle ---------------------

def test_etat_avance_apres_persistance_reussie():
    persisted, notified = [], []
    spy = _Spy(plan=_plan(), next_state={"v": 2})
    d = _driver(spy, persist_state=persisted.append, on_state_updated=notified.append)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))
    assert persisted == [{"v": 2}] and notified == [{"v": 2}]
    assert d.state == {"v": 2}


def test_persistance_ECHOUEE_l_etat_n_avance_PAS():
    """Correctif de divergence : le driver TS avançait la mémoire avant la persistance — une
    écriture ratée laissait Redis en retard, et le redémarrage repartait d'un état faux."""
    notified = []

    def failing(_state):
        raise ConnectionError("Redis mort")
    spy = _Spy(plan=_plan(), next_state={"v": 2})
    d = _driver(spy, persist_state=failing, on_state_updated=notified.append)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))                        # ne lève pas
    assert d.state == {"v": 1}                              # état PAS avancé
    assert notified == []                                   # ni notifié


def test_retente_et_converge_quand_la_persistance_revient():
    calls = {"n": 0}

    def flaky(_state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("Redis mort")
    spy = _Spy(plan=_plan(), next_state={"v": 2})
    d = _driver(spy, persist_state=flaky)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))
    assert d.state == {"v": 1}
    asyncio.run(d.evaluate(1_000.0))                        # le moteur est déterministe → même état
    assert d.state == {"v": 2} and calls["n"] == 2


def test_etat_inchange_aucune_persistance_ni_notification():
    persisted, notified = [], []
    spy = _Spy(plan=_plan())                                # next_state = state (inchangé)
    d = _driver(spy, persist_state=persisted.append, on_state_updated=notified.append)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))
    assert persisted == [] and notified == []


def test_comparaison_INSENSIBLE_a_l_ordre_des_cles():
    """`JSON.stringify` ×2 (driver TS) déclencherait une FAUSSE mutation sur un simple
    changement d'ordre d'insertion. L'égalité structurelle non."""
    persisted = []
    spy = _Spy(plan=_plan(), next_state={"b": 2, "a": 1})
    d = _driver(spy, initial_state={"a": 1, "b": 2}, clock=lambda: 1_000.0,
                persist_state=persisted.append)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))
    assert persisted == []                                  # même contenu → aucune écriture


# --- 2. Callbacks bornés : rien ne tue la boucle ---------------------------------------------

def test_callback_qui_LEVE_ne_tue_pas_le_driver(caplog):
    def boom(_x):
        raise RuntimeError("consommateur cassé")
    spy = _Spy(plan=_plan(), next_state={"v": 2})
    d = _driver(spy, on_plan_approved=boom, on_state_updated=boom)
    _feed(d)
    with caplog.at_level(logging.ERROR):
        asyncio.run(d.evaluate(1_000.0))                     # ne lève pas
    assert [r for r in caplog.records if r.name.startswith("cholismo")]   # une panne SE VOIT
    asyncio.run(d.evaluate(1_000.0))                         # et la boucle survit
    assert len(spy.calls) == 2


def test_callback_ASYNC_qui_rejette_ne_tue_pas_le_driver():
    """En Node, une promesse rejetée non gérée tue le process. Ici : capturée, awaitée."""
    async def boom(_x):
        raise RuntimeError("persistance async cassée")
    spy = _Spy(plan=_plan())
    d = _driver(spy, on_plan_approved=boom)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))                         # ne lève pas
    assert len(spy.calls) == 1


def test_callback_async_nominal_est_AWAITE():
    seen = []

    async def collect(x):
        await asyncio.sleep(0)
        seen.append(x)
    spy = _Spy(plan=_plan())
    d = _driver(spy, on_plan_approved=collect)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))
    assert len(seen) == 1                                    # awaité, pas « fire and forget »


def test_evaluateur_qui_LEVE_est_capture(caplog):
    spy = _Spy(raises=ValueError("moteur cassé"))
    d = _driver(spy)
    _feed(d)
    with caplog.at_level(logging.ERROR):
        asyncio.run(d.evaluate(1_000.0))                      # ne lève pas
    assert d.state == {"v": 1}                                # état intact
    assert [r for r in caplog.records if r.name.startswith("cholismo")]


# --- start()/stop() : idempotents, sortie propre ---------------------------------------------

def test_start_idempotent_et_stop_propre():
    async def scenario():
        spy = _Spy(plan=_plan())
        d = LsrLiveDriver(spy, initial_state={"v": 1}, poll_seconds=0.02)
        _feed(d, now=time.time())
        await d.start()
        first = d._task
        await d.start()                                      # 2e appel : AUCUN timer supplémentaire
        assert d._task is first
        await asyncio.sleep(0.09)
        await d.stop()
        await d.stop()                                       # idempotent
        assert d._task is None
        return len(spy.calls)
    n = asyncio.run(scenario())
    assert n >= 2                                            # la boucle a bien tourné


def test_boucle_survit_a_un_evaluateur_cassé():
    async def scenario():
        spy = _Spy(raises=RuntimeError("boom"))
        d = LsrLiveDriver(spy, initial_state={"v": 1}, poll_seconds=0.02)
        _feed(d, now=time.time())
        await d.start()
        await asyncio.sleep(0.09)
        await d.stop()
        return len(spy.calls)
    assert asyncio.run(scenario()) >= 2                      # relancée malgré les exceptions


def test_horloge_injectee_zero_lecture_systeme():
    """Discipline commune D-045/046/047/050 : le driver est le SEUL propriétaire d'horloge, et
    même là elle est injectable — les tests sont déterministes."""
    spy = _Spy(plan=_plan())
    ticks = iter([2_000.0, 2_000.0])
    d = _driver(spy, clock=lambda: next(ticks))
    _feed(d, now=2_000.0)
    asyncio.run(d.evaluate_now())                            # utilise l'horloge injectée
    assert spy.calls[0].now == 2_000.0


def test_outcome_de_trade_horloge_explicite_requise():
    """`handleTradeOutcome(won, ts = Date.now())` (TS) rendait les tests non déterministes :
    ici l'horodatage est OBLIGATOIRE."""
    recorded = []
    spy = _Spy(plan=_plan())
    d = _driver(spy, record_outcome=lambda state, won, ts: (recorded.append((won, ts)),
                                                           {"v": 9})[1])
    asyncio.run(d.record_trade_outcome(won=True, ts=1_234.0))
    assert recorded == [(True, 1_234.0)] and d.state == {"v": 9}
    with pytest.raises(TypeError):
        asyncio.run(d.record_trade_outcome(won=True))        # ts non fourni → refus


# =============================================================================================
# /devil (Loop 4) — six façons de casser le driver
# =============================================================================================

def _run(scenario, timeout=2.0):
    """Exécute un scénario async sous plafond DUR. Une faille de sérialisation se manifeste par un
    BLOCAGE : sans plafond, le test ne rougit pas — il pend, et emporte la suite entière."""
    async def guarded():
        return await asyncio.wait_for(scenario(), timeout)
    return asyncio.run(guarded())


async def keep_fresh(d, duration):
    """Démarre le driver si besoin et l'alimente EN CONTINU pendant `duration` (temps réel) : la
    boucle ne s'observe qu'avec un feed vivant, sinon la péremption masque tout le reste."""
    if d._task is None:
        await d.start()
    end = time.monotonic() + duration
    while time.monotonic() < end:
        now = time.time()
        d.update_market(MARKET, ts=now)
        d.update_account(ACCOUNT, ts=now)
        await asyncio.sleep(0.005)

# --- 1. Écriture perdue : un cooldown F6 écrasé par une évaluation EN VOL --------------------

def test_outcome_pendant_une_evaluation_en_vol_n_est_PAS_ECRASE():
    """LA faille la plus grave : `evaluate` et `record_trade_outcome` faisaient tous deux un
    read-modify-write de `_state` avec un `await` (persistance) AU MILIEU. Une perte enregistrée
    pendant qu'une évaluation attendait Redis était écrasée par l'état calculé AVANT la perte →
    cooldown F6 effacé → on retrade juste après une perte. Fail-OPEN sur une règle de sécurité.
    Le cycle état doit donc être SÉRIALISÉ."""
    async def scenario():
        gate = asyncio.Event()

        async def persist(state):
            if state == {"v": 2}:                            # seule l'évaluation attend
                await gate.wait()

        spy = _Spy(plan=_plan(), next_state={"v": 2})
        d = _driver(spy, persist_state=persist,
                    record_outcome=lambda state, won, ts: {**state, "cooldown_until": ts + 90})
        _feed(d)
        evaluation = asyncio.create_task(d.evaluate(1_000.0))
        await asyncio.sleep(0)                               # bloquée dans la persistance
        outcome = asyncio.create_task(d.record_trade_outcome(won=False, ts=1_000.0))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(evaluation, outcome)
        return d.state

    # L'issue de trade est appliquée à l'état AVANCÉ, et survit.
    assert _run(scenario) == {"v": 2, "cooldown_until": 1_090.0}


def test_evaluation_concurrente_est_DROPPEE_pas_empilee():
    """Deux évaluations en vol sur le même état émettraient DEUX fois le même ticket. Une
    évaluation en cours suffit : la seconde est droppée (doctrine strict drop D-045 T3 — en
    microstructure on ne trade pas le passé), sans log (rejet naturel, hygiène D-046)."""
    async def scenario():
        gate = asyncio.Event()
        approved = []

        async def slow_emit(plan):
            approved.append(plan)
            await gate.wait()

        spy = _Spy(plan=_plan())
        d = _driver(spy, on_plan_approved=slow_emit)
        _feed(d)
        first = asyncio.create_task(d.evaluate(1_000.0))
        await asyncio.sleep(0)
        await d.evaluate(1_000.0)                            # concurrente → droppée sur-le-champ
        gate.set()
        await first
        return len(spy.calls), len(approved)

    assert _run(scenario) == (1, 1)                 # un seul cycle, un seul ticket


# --- 2. Callback qui ne rend JAMAIS la main ---------------------------------------------------

def test_callback_qui_NE_REND_JAMAIS_la_main_est_BORNE(caplog):
    """`await` sans plafond : une socket Redis suspendue pendait la boucle pour l'éternité — zéro
    évaluation, zéro log, un driver mort qui ressemble à un driver calme. Le plafond transforme
    la pendaison en ÉCHEC visible (donc l'état n'avance pas et la tentative suivante réécrit)."""
    async def scenario():
        async def hang(_state):
            await asyncio.Event().wait()                     # ne rend jamais la main

        spy = _Spy(plan=_plan(), next_state={"v": 2})
        d = _driver(spy, persist_state=hang, callback_timeout_s=0.05)
        _feed(d)
        await asyncio.wait_for(d.evaluate(1_000.0), timeout=2.0)
        return d.state

    with caplog.at_level(logging.ERROR):
        assert _run(scenario) == {"v": 1}                    # état INCHANGÉ
    assert [r for r in caplog.records if r.name.startswith("cholismo")]


# --- 3. Émission sans état durable ------------------------------------------------------------

def test_plan_NON_EMIS_si_l_etat_n_a_pas_pu_etre_PERSISTE():
    """Le plan naît de la transition d'état ; si la transition n'est pas durable, le redémarrage
    revient en arrière et le MÊME sweep peut ré-émettre → doublon de ticket. Pas d'état → pas
    d'émission (même doctrine que le journal D-045)."""
    approved = []

    def failing(_state):
        raise ConnectionError("Redis mort")

    spy = _Spy(plan=_plan(), next_state={"v": 2})
    d = _driver(spy, persist_state=failing, on_plan_approved=approved.append)
    _feed(d)
    asyncio.run(d.evaluate(1_000.0))
    assert d.state == {"v": 1} and approved == []


# --- 4. Comparaison d'état qui LÈVE -----------------------------------------------------------

class _Ambiguous:
    """État dont l'égalité n'est PAS booléenne — signature d'un `ndarray` (« truth value of an
    array is ambiguous »), tout à fait plausible si l'état embarque un snapshot de carnet."""

    def __eq__(self, other):
        raise ValueError("truth value of an array with more than one element is ambiguous")

    __hash__ = None


def test_etat_INCOMPARABLE_ne_leve_pas_et_n_emet_rien(caplog):
    approved = []
    spy = _Spy(plan=_plan(), next_state=_Ambiguous())
    d = _driver(spy, on_plan_approved=approved.append, persist_state=lambda _s: None)
    _feed(d)
    with caplog.at_level(logging.ERROR):
        asyncio.run(d.evaluate(1_000.0))                     # ne lève PAS vers l'appelant
    assert d.state == {"v": 1} and approved == []            # fail-closed complet
    assert [r for r in caplog.records if r.name.startswith("cholismo")]


# --- 5. Boucle tuée de l'extérieur ------------------------------------------------------------

def test_start_RELANCE_une_boucle_morte(caplog):
    """`if self._task is not None: return` : après une annulation EXTERNE (arrêt d'un TaskGroup,
    balayage de shutdown), la tâche est `done()` mais non-None → `start()` ne relançait rien et
    le driver restait mort EN SILENCE. Une boucle morte doit se voir et se relancer."""
    async def scenario():
        spy = _Spy(plan=_plan())
        d = LsrLiveDriver(spy, initial_state={"v": 1}, poll_seconds=0.02)
        _feed(d, now=time.time())
        await d.start()
        d._task.cancel()                                     # annulation venue de l'extérieur
        await asyncio.sleep(0.01)
        assert d._task.done()
        await d.start()                                      # doit repartir
        await asyncio.sleep(0.07)
        n = len(spy.calls)
        await d.stop()
        return n

    with caplog.at_level(logging.WARNING):
        assert _run(scenario) >= 2
    assert [r for r in caplog.records if r.name.startswith("cholismo")]   # la mort SE VOIT


def test_stop_sur_une_tache_MORTE_ne_propage_pas():
    """`await self._task` re-lève l'exception d'une tâche déjà morte : `stop()` explosait au
    moment précis d'un arrêt gracieux (RUNTIME_LOOPS §arrêt)."""
    async def scenario():
        async def dead():
            raise RuntimeError("boucle morte")

        d = _driver(_Spy(plan=_plan()))
        d._task = asyncio.create_task(dead())
        await asyncio.sleep(0)
        await d.stop()                                       # ne propage pas
        return d._task

    assert _run(scenario) is None


# --- 6. Horloge qui RECULE --------------------------------------------------------------------

def test_horloge_qui_RECULE_reste_muette_mais_SIGNALE_une_seule_fois(caplog):
    """Un pas NTP arrière (ou une horloge source qui décroche) rend tous les snapshots « datés du
    futur » : le driver se tait — c'est correct (§3) — mais indéfiniment et sans trace. Une
    régression d'horloge est une ANOMALIE système, pas un rejet naturel : elle se journalise
    UNE fois par épisode (4 logs/s serait un flood, hygiène D-046)."""
    spy = _Spy(plan=_plan())
    ticks = iter([1_000.0, 990.0, 989.5, 989.0, 1_001.0])
    d = _driver(spy, clock=lambda: next(ticks))
    _feed(d, now=1_000.0)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            asyncio.run(d.evaluate_now())
    assert len(spy.calls) == 2                               # la 1re, puis au retour de l'horloge
    records = [r for r in caplog.records if r.name.startswith("cholismo")]
    assert len(records) == 1                                 # un seul signal, pas trois


# =============================================================================================
# /polish (Loop 5) — cadence honnête, arrêt propre depuis un callback
# =============================================================================================

def test_cadence_a_ECHEANCE_le_travail_ne_s_ajoute_pas_a_la_periode():
    """« Travail puis sieste fixe » donne une période réelle de `poll + travail` : la cadence
    annoncée devient un mensonge silencieux. Ici la boucle vise une ÉCHÉANCE — et ne rattrape
    jamais un retard par une rafale (évaluer le passé n'a aucun sens en microstructure)."""
    async def scenario():
        evals = []

        async def slow_persist(_state):
            await asyncio.sleep(0.02)                        # travail = période nominale

        def evaluator(payload):
            evals.append(payload.now)
            return _plan(), {"v": len(evals)}                # état neuf → persistance à chaque tick

        d = LsrLiveDriver(evaluator, initial_state={"v": 0}, persist_state=slow_persist,
                          poll_seconds=0.02)
        await keep_fresh(d, 0.30)
        await d.stop()
        return len(evals)

    n = _run(scenario, timeout=3.0)
    # « sieste fixe » plafonnerait à 0,30 / (0,02 + 0,02) ≈ 7. Borne haute : jamais plus d'une
    # évaluation par période (+ marge) — donc aucune rafale de rattrapage.
    assert 10 <= n <= 20, n


def test_stop_pendant_un_callback_EN_VOL_ne_PEND_pas():
    """Trouvé par l'essai réel, pas par un test : `asyncio.wait_for` (3.11) AVALE une annulation
    externe si sa future interne vient de se terminer. La boucle survivait donc à son propre
    `cancel()` et `stop()` attendait pour toujours — l'arrêt du terminal restait pendu ~1 fois sur
    2. Course : on répète, avec des instants d'arrêt décalés."""
    async def scenario():
        for k in range(30):
            async def persist(_state):
                return None                                  # future interne terminée AUSSITÔT :
                #                                              c'est la fenêtre exacte de l'avalement

            counter = {"n": 0}

            def evaluator(_payload):
                counter["n"] += 1
                return _plan(), {"v": counter["n"]}          # état neuf → persistance à chaque tick

            d = LsrLiveDriver(evaluator, initial_state={"v": 0}, persist_state=persist,
                              poll_seconds=0.02)
            _feed(d, now=time.time())
            await d.start()
            await asyncio.sleep(0.02 + (k % 5) * 0.004)      # arrêt à des phases différentes
            stopper = asyncio.create_task(d.stop())
            for _ in range(10):
                if stopper.done():
                    break
                await asyncio.sleep(0.01)
            if not stopper.done():
                stopper.cancel()
                return k                                     # blocage à l'itération k
        return None

    assert _run(scenario, timeout=15.0) is None


def test_stop_ne_CONFISQUE_pas_l_annulation_de_l_appelant():
    """`except CancelledError: pass` avalait aussi l'annulation de l'APPELANT : pendant un
    shutdown, `await driver.stop()` rendait la main normalement et la séquence d'arrêt continuait
    comme si rien ne s'était passé (Loop H)."""
    async def scenario():
        async def stubborn():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.Event().wait()                 # ignore l'annulation : stop() attend

        d = _driver(_Spy(plan=_plan()))
        d._task = asyncio.create_task(stubborn())
        caller = asyncio.create_task(d.stop())
        await asyncio.sleep(0)                               # `caller` est à `await task`
        caller.cancel()
        try:
            await caller
            return "avalée"
        except asyncio.CancelledError:
            return "propagée"

    assert _run(scenario) == "propagée"


def test_stop_DEPUIS_un_callback_ne_leve_pas():
    """Un consommateur qui coupe le driver depuis son propre callback (« arrête tout ») :
    s'attendre soi-même lève « Task cannot await on itself » — un arrêt gracieux ne doit pas
    exploser au moment précis où on le demande."""
    async def scenario():
        d = None

        async def emit(_plan):
            await d.stop()                                   # depuis l'intérieur de la boucle

        d = LsrLiveDriver(_Spy(plan=_plan()), initial_state={"v": 1},
                          on_plan_approved=emit, poll_seconds=0.02)
        await d.start()
        await keep_fresh(d, 0.10)
        return d._task

    assert _run(scenario) is None
