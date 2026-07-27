"""Feature — Source de Compte & Câblage RiskSizer → émission LSR (D-047, tranche 2).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- `AccountDataProvider` (port) : `current(now) -> AccountState | None` — l'horloge est INJECTÉE
  (règle commune D-045/046/047), le provider décide de la fraîcheur ;
- `MockAccountProvider` STRICT : simule le flux NinjaTrader/broker — photo (state, ts) poussée
  par `push`, déconnexion simulable, et **périmé = absent** (§3) : au-delà de
  `ACCOUNT_MAX_AGE_S`, `current()` rend None, jamais une équité fossile ;
- `size_plan(plan, account)` : dimensionne un plan LSR APPROVED via la règle du 1/5e — stop en
  ticks dérivé de la GÉOMÉTRIE du plan (|entrée − stop| / tick_size), contrats remplacés ;
  rejet du sizer (F8/corruption) → None ; instrument inconnu → None ; jamais de mutation ;
- câblage `_maybe_emit_lsr` : **on ne trade jamais à l'aveugle** — pas de provider, provider
  None (déconnecté/périmé) ou sizing rejeté → AUCUNE émission, silence.
"""
import asyncio
import json
import time

from app import config
from app.account_provider import MockAccountProvider
from app.datasource.mock import MockDataSource
from app.engine import Engine
from app.meta import Freshness, MetaField
from app.redis_state import RedisState
from app.risk_sizer import APEX_EOD_50K, apex_eod_account, size_plan
from app.sse import broadcaster


def _fresh(value, now):
    return MetaField(value=value, last_update_ts=now, source="test", freshness=Freshness.FRESH)


def _plan(**over) -> dict:
    """Plan tel que produit par evaluate_lsr : LONG MES, stop à 3 ticks (entrée 5448.25,
    stop 5447.50), TP 5449.50."""
    base = {"status": "APPROVED", "instrument": "MES", "direction": "LONG",
            "reason": "LSR — essai", "executionPlan": {
                "entryType": "LIMIT", "entryPrice": 5448.25, "stopLoss": 5447.5,
                "takeProfit": 5449.5, "contracts": 1}}
    base.update(over)
    return base


# --- Provider : fraîcheur honnête -----------------------------------------------------------

def test_provider_rend_l_etat_frais():
    now = time.time()
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), ts=now)
    acc = p.current(now + 1)
    assert acc is not None and acc.current_equity == 50_000.0


def test_provider_perime_rend_none_jamais_une_equite_fossile():
    now = time.time()
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), ts=now)
    assert p.current(now + config.ACCOUNT_MAX_AGE_S + 0.1) is None
    assert p.current(now + 1) is not None                   # re-frais si l'horloge le permet


def test_provider_deconnecte_rend_none():
    now = time.time()
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), ts=now)
    p.disconnect()
    assert p.current(now) is None


def test_provider_push_met_a_jour_l_equite():
    now = time.time()
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), ts=now)
    p.push(apex_eod_account(APEX_EOD_50K, current_equity=49_500.0,
                            day_start_equity=50_000.0), ts=now + 5)
    acc = p.current(now + 6)
    assert acc is not None and acc.current_equity == 49_500.0


def test_provider_sans_etat_initial_rend_none():
    assert MockAccountProvider().current(time.time()) is None


def test_provider_always_fresh_pour_le_stack_demo():
    """Mode `always_fresh` : couture du stack MOCK uniquement (un broker simulé qui répond
    toujours) — un provider réel remplace ce mode par de vraies photos datées."""
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), always_fresh=True)
    assert p.current(time.time() + 9_999_999) is not None


# --- size_plan : la géométrie du plan dimensionnée par le compte ----------------------------

def test_size_plan_remplace_les_contrats_par_la_regle_du_cinquieme():
    # stop 3 ticks MES (0.75 pt) → 3 × 1.25 = 3.75 $/contrat ; buffer 1000 → 200/3.75 → 53
    sized = size_plan(_plan(), apex_eod_account(APEX_EOD_50K))
    assert sized is not None and sized["executionPlan"]["contracts"] == 53
    assert sized["executionPlan"]["entryPrice"] == 5448.25  # géométrie intacte


def test_size_plan_ne_mute_jamais_le_plan_d_entree():
    plan = _plan()
    size_plan(plan, apex_eod_account(APEX_EOD_50K))
    assert plan["executionPlan"]["contracts"] == 1          # l'original n'a pas bougé


def test_size_plan_buffer_mort_rend_none():
    dead = apex_eod_account(APEX_EOD_50K, current_equity=48_900.0, day_start_equity=50_000.0)
    assert size_plan(_plan(), dead) is None


def test_size_plan_instrument_inconnu_rend_none():
    assert size_plan(_plan(instrument="ZN"), apex_eod_account(APEX_EOD_50K)) is None


def test_size_plan_malforme_rend_none():
    assert size_plan(None, apex_eod_account(APEX_EOD_50K)) is None
    assert size_plan({"status": "APPROVED"}, apex_eod_account(APEX_EOD_50K)) is None
    assert size_plan(_plan(executionPlan=None), apex_eod_account(APEX_EOD_50K)) is None


# --- Câblage engine : on ne trade JAMAIS à l'aveugle ----------------------------------------

def _wire_setup(eng, now):
    eng.schema.econ_calendar.events = _fresh(
        [{"ts": now + 300, "name": "NFP — emplois US", "tier": 1, "region": "US"}], now)
    s1 = eng.schema.s1_state
    s1.tape = _fresh([{"ts": now - 1.0 + 0.1 * k, "price": 4998.0 + 0.25 * (k % 4),
                       "size": 5.0, "side": "SELL", "seq": k} for k in range(10)], now)
    s1.order_book = _fresh({"bids": [[4999.75, 70.0], [4999.5, 70.0], [4999.25, 70.0]],
                            "asks": [[5000.25, 70.0], [5000.5, 70.0], [5000.75, 70.0]]}, now)
    s1.order_flow.absorption = _fresh(True, now)
    s1.order_flow.aggressor_ratio = _fresh(0.72, now)
    s1.structure.vpoc = _fresh(5000.0, now)


def _drain_manifests(q):
    out = []
    while not q.empty():
        e = q.get_nowait()
        if e["event"] == "trade_manifest":
            out.append(json.loads(e["data"]))
    return out


def _run(provider):
    """Monte un engine avec le provider donné, câble un setup valide, rend les manifestes émis."""
    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=provider)
        _wire_setup(eng, now)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        assert eng.schema.liquidity_sweep.triggered is True
        eng._maybe_emit_lsr(now)
        out = _drain_manifests(q)
        broadcaster.unsubscribe("fast", q)
        return out
    return asyncio.run(scenario())


def test_emission_avec_compte_sain_contrats_dimensionnes():
    # extrême 4998 → entrée 4998.25, stop 4997.50 = 3 ticks → 200/3.75 → 53 contrats
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), always_fresh=True)
    manifests = _run(p)
    assert len(manifests) == 1
    assert manifests[0]["risk"]["positionSize"] == 53
    assert manifests[0]["direction"] == "BUY"


def test_sans_provider_aucune_emission():
    assert _run(None) == []                                 # pas de compte → pas de ticket


def test_provider_perime_aucune_emission():
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), ts=time.time() - 3600)
    assert _run(p) == []                                    # équité fossile → à l'aveugle → non


def test_provider_deconnecte_aucune_emission():
    p = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), always_fresh=True)
    p.disconnect()
    assert _run(p) == []


def test_buffer_mort_aucune_emission():
    dead = apex_eod_account(APEX_EOD_50K, current_equity=48_900.0, day_start_equity=50_000.0)
    p = MockAccountProvider(state=dead, always_fresh=True)
    assert _run(p) == []                                    # F8 en bout de chaîne → silence


# --- /devil D-047 T2 : flapping, antidaté, chute en vol -------------------------------------

def test_devil_push_antidate_mort_ne():
    """Un push dont la photo a DÉJÀ plus de ACCOUNT_MAX_AGE_S à l'arrivée : mort-né — None."""
    now = time.time()
    p = MockAccountProvider()
    p.push(apex_eod_account(APEX_EOD_50K), ts=now - config.ACCOUNT_MAX_AGE_S - 1)
    assert p.current(now) is None


def test_devil_ts_du_futur_desync_d_horloge_mort_ne():
    """Désync d'horloge broker : une photo datée du FUTUR resterait « fraîche » indéfiniment
    (now − ts négatif) — son heure réelle est inconnue, elle ne vaut rien (même leçon que les
    prints D-046)."""
    now = time.time()
    p = MockAccountProvider()
    p.push(apex_eod_account(APEX_EOD_50K), ts=now + 3600)
    assert p.current(now) is None


def test_devil_ts_non_fini_mort_ne():
    """ts NaN : `now − nan > max_age` est FAUX → la photo passerait la garde de fraîcheur."""
    import math as _math
    now = time.time()
    p = MockAccountProvider()
    for bad in (_math.nan, _math.inf, None):
        p2 = MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), ts=bad)
        assert p2.current(now) is None, bad
    p.push(apex_eod_account(APEX_EOD_50K), ts=_math.nan)
    assert p.current(now) is None


class _FlappingProvider:
    """Alterne connecté/déconnecté à CHAQUE lecture (flapping ms)."""
    def __init__(self, state):
        self._state, self._n = state, 0

    def current(self, now):
        self._n += 1
        return self._state if self._n % 2 == 0 else None


class _RaisingProvider:
    """Provider réel cassé : lève au milieu de la lecture (socket morte) au lieu de rendre None."""
    def current(self, now):
        raise ConnectionError("socket broker morte en pleine lecture")


def test_devil_flapping_jamais_de_crash_emissions_bornees():
    """Connexion instable : le pipeline ne crashe jamais ; l'émission n'arrive que si la lecture
    UNIQUE du compte tombe sur un instant connecté — sinon silence."""
    async def scenario():
        now = time.time()
        flapping = _FlappingProvider(apex_eod_account(APEX_EOD_50K))
        eng = Engine(MockDataSource(), RedisState(), account_provider=flapping)
        _wire_setup(eng, now)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        for k in range(6):                                  # 1re lecture déconnectée, 2e connectée…
            eng._maybe_emit_lsr(now + k * 0.001)
        manifests = _drain_manifests(q)
        broadcaster.unsubscribe("fast", q)
        assert len(manifests) == 1                          # dédup/F7 bornent à UNE émission
    asyncio.run(scenario())


def test_devil_provider_qui_leve_silence_sans_spam_de_log(caplog):
    """Un provider réel qui LÈVE (au lieu de rendre None) ne doit ni crasher le pipeline ni
    spammer log.exception à chaque tick — coupure = rejet naturel = silence (hygiène D-046)."""
    import logging

    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=_RaisingProvider())
        _wire_setup(eng, now)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        with caplog.at_level(logging.DEBUG):
            caplog.clear()
            for k in range(5):
                eng._maybe_emit_lsr(now + k)                # ne lève JAMAIS
            assert caplog.records == []                     # et ne logge RIEN
        assert _drain_manifests(q) == []
        broadcaster.unsubscribe("fast", q)
    asyncio.run(scenario())


class _CrashOnReadProvider:
    """Chute d'équité EN VOL : au moment précis de la lecture (après evaluate_lsr, avant
    size_plan), le broker annonce le passage sous le DLL."""
    def __init__(self):
        self.reads = 0

    def current(self, now):
        self.reads += 1
        return apex_eod_account(APEX_EOD_50K, current_equity=48_900.0,   # perte 1100 > DLL
                                day_start_equity=50_000.0)


def test_devil_chute_d_equite_en_vol_rejet_in_extremis():
    """La lecture du compte est APRÈS l'approbation d'evaluate_lsr : la photo la plus fraîche
    possible au moment de décider. Une chute sous le DLL survenue pendant l'évaluation est
    attrapée par size_plan (buffer mort) → aucun manifeste, silence."""
    async def scenario():
        now = time.time()
        crash = _CrashOnReadProvider()
        eng = Engine(MockDataSource(), RedisState(), account_provider=crash)
        _wire_setup(eng, now)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        eng._maybe_emit_lsr(now)
        assert crash.reads == 1                             # UNE lecture, après l'évaluation
        assert _drain_manifests(q) == []                    # F8 in extremis → silence
        broadcaster.unsubscribe("fast", q)
    asyncio.run(scenario())


def test_devil_provider_au_mauvais_type_silence():
    """Un provider bâclé qui rend un dict au lieu d'un AccountState : jamais un AttributeError
    dans la boucle sweep — rejet silencieux."""
    class _WrongType:
        def current(self, now):
            return {"current_equity": 50_000.0}
    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=_WrongType())
        _wire_setup(eng, now)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        eng._maybe_emit_lsr(now)                            # ne lève pas
        assert _drain_manifests(q) == []
        broadcaster.unsubscribe("fast", q)
    asyncio.run(scenario())
