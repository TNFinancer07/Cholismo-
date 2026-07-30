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
