"""Feature — couche microstructure LSR : évaluation fail-closed + émission SSE (D-046).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- `LsrInputs` : entrées STATELESS, microstructure SEULE (sweep, tape, order flow, carnet, VPOC) —
  aucune donnée macro/options/news (isolation D-046 ; ces couches vivent ailleurs) ;
- `build_lsr_inputs(schema, now)` : n'extrait que du FRESH — donnée périmée = donnée absente (§3) ;
- `evaluate_lsr(inputs)` : PURE et déterministe ; tout critère manquant/hors seuil → `None`
  SILENCIEUX, sans état résiduel ; approbation → plan au contrat D-045
  (`manifest_from_lsr_plan` le revérifie intégralement) ;
- pipeline engine : `_maybe_emit_lsr` sur la cadence sweep (hors hot path §2.8), UNE émission
  max par alerte distincte, publiée `trade_manifest` sur le canal fast SANS cache de replay
  (un manifeste est un ÉVÉNEMENT éphémère, pas un état de bloc — un abonné neuf ne doit pas
  recevoir un ticket d'avant sa connexion).
"""
import asyncio
import math
import time

from app import config
from app.lsr_tuning import MES_TUNING as MES
from app.datasource.mock import MockDataSource
from app.engine import Engine
from app.lsr_engine import LsrInputs, build_lsr_inputs, evaluate_lsr
from app.meta import Freshness, MetaField
from app.account_provider import MockAccountProvider
from app.redis_state import RedisState
from app.risk_sizer import APEX_EOD_50K, apex_eod_account
from app.sse import broadcaster
from app.trade_manifest import manifest_from_lsr_plan

T = config.PRICE_TICK


def _fresh(value, now):
    return MetaField(value=value, last_update_ts=now, source="test", freshness=Freshness.FRESH)


def _prints(now, *, low=None, high=None, n=9, side="SELL"):
    """Rafale de prints autour de 5000, avec un extrême contrôlé."""
    base = [{"ts": now - 1.5 + 0.15 * k, "price": 5000.0 + (0.25 * (k % 3)),
             "size": 3.0, "side": side, "seq": k} for k in range(n)]
    if low is not None:
        base[n // 2] = {**base[n // 2], "price": low}
    if high is not None:
        base[n // 2] = {**base[n // 2], "price": high}
    return base


def _book(depth_each=70.0):
    """Carnet MES nominal : meilleur bid et meilleur ask à 1 TICK l'un de l'autre — c'est ce que
    cote MES la quasi-totalité de la séance, et c'est le maximum que tolère F4 (D-069)."""
    return {"bids": [[4999.75, depth_each], [4999.5, depth_each], [4999.25, depth_each]],
            "asks": [[5000.0, depth_each], [5000.25, depth_each], [5000.5, depth_each]]}


def _inputs(now=None, **over) -> LsrInputs:
    """Entrées nominales : BID_SWEEP réintégré, extrême 4998.0, gates au vert → LONG."""
    now = now if now is not None else time.time()
    base = dict(
        now=now,
        sweep_ts=now - 5.0, sweep_direction="BID_SWEEP",
        prints=_prints(now, low=4998.0),
        absorption=True, aggressor_ratio=0.70,
        book=_book(),
        vpoc=5000.0,
    )
    base.update(over)
    return LsrInputs(**base)


# --- Évaluation : chemin nominal -----------------------------------------------------------

def test_long_apres_bid_sweep_geometrie_complete():
    plan = evaluate_lsr(_inputs())
    assert plan is not None and plan["status"] == "APPROVED"
    assert plan["instrument"] == config.LSR_INSTRUMENT and plan["direction"] == "LONG"
    ex = plan["executionPlan"]
    assert ex["entryType"] == "LIMIT" and ex["contracts"] == config.LSR_CONTRACTS
    # A1 : entrée = extrême + offset ; A3 : stop = extrême − buffer ; A2 : TP borné vers VPOC
    assert ex["entryPrice"] == 4998.0 + MES.entry_offset_ticks * T
    assert ex["stopLoss"] == 4998.0 - MES.sl_noise_buffer_max_ticks * T
    assert ex["takeProfit"] == min(ex["entryPrice"] + MES.tp_max_ticks * T,
                                   5000.0 - MES.tp_vpoc_margin_ticks * T)
    assert ex["stopLoss"] < ex["entryPrice"] < ex["takeProfit"]
    # aligné au tick
    for k in ("entryPrice", "stopLoss", "takeProfit"):
        assert abs(ex[k] / T - round(ex[k] / T)) < 1e-9
    assert "LSR" in plan["reason"]


def test_short_apres_ask_sweep_geometrie_miroir():
    plan = evaluate_lsr(_inputs(
        sweep_direction="ASK_SWEEP", prints=_prints(time.time(), high=5002.0, side="BUY"),
        aggressor_ratio=0.25, vpoc=5000.0))
    assert plan is not None and plan["direction"] == "SHORT"
    ex = plan["executionPlan"]
    assert ex["entryPrice"] == 5002.0 - MES.entry_offset_ticks * T
    assert ex["stopLoss"] == 5002.0 + MES.sl_noise_buffer_max_ticks * T
    assert ex["takeProfit"] < ex["entryPrice"] < ex["stopLoss"]


def test_plan_approuve_traverse_la_garde_d045():
    plan = evaluate_lsr(_inputs())
    m = manifest_from_lsr_plan(plan, now_ms=1_753_500_000_000)
    assert m is not None and m.direction == "BUY" and m.instrument == config.LSR_INSTRUMENT


def test_purete_deterministe_et_entrees_non_mutees():
    i = _inputs(now=1_000_000.0)
    a, b = evaluate_lsr(i), evaluate_lsr(i)
    assert a == b                               # même entrée → même plan, aucun état résiduel
    assert i.prints[0]["ts"] == 1_000_000.0 - 1.5   # entrées jamais mutées


# --- Évaluation : chaque gate rejette en SILENCE (None, jamais d'exception) ----------------

def test_sans_sweep_silence():
    assert evaluate_lsr(_inputs(sweep_ts=None, sweep_direction=None)) is None


def test_sweep_sans_direction_inorientable():
    assert evaluate_lsr(_inputs(sweep_direction=None)) is None


def test_sweep_trop_vieux_silence():
    now = time.time()
    assert evaluate_lsr(_inputs(now=now, sweep_ts=now - config.LSR_SWEEP_MAX_AGE_S - 1)) is None


def test_b1_absorption_absente_ou_fausse_silence():
    assert evaluate_lsr(_inputs(absorption=False)) is None
    assert evaluate_lsr(_inputs(absorption=None)) is None


def test_b2_pas_de_bascule_des_agressifs_silence():
    assert evaluate_lsr(_inputs(aggressor_ratio=0.50)) is None            # LONG exige ≥ flip
    assert evaluate_lsr(_inputs(sweep_direction="ASK_SWEEP",
                                prints=_prints(time.time(), high=5002.0),
                                aggressor_ratio=0.50)) is None            # SHORT exige ≤ 1−flip


def test_f4_spread_trop_large_silence():
    book = {"bids": [[4999.0, 70.0], [4998.75, 70.0], [4998.5, 70.0]],
            "asks": [[5001.0, 70.0], [5001.25, 70.0], [5001.5, 70.0]]}   # 8 ticks
    assert evaluate_lsr(_inputs(book=book)) is None


def test_f4_profondeur_insuffisante_silence():
    assert evaluate_lsr(_inputs(book=_book(depth_each=20.0))) is None    # top-3 = 60 < min


def test_a2_vpoc_du_mauvais_cote_ou_sans_place_silence():
    assert evaluate_lsr(_inputs(vpoc=4997.0)) is None                    # LONG : VPOC sous l'entrée
    # VPOC si proche que TP < entrée + tpMin → pas de place → rejet
    close = 4998.0 + MES.entry_offset_ticks * T + (MES.tp_min_ticks - 1) * T \
        + MES.tp_vpoc_margin_ticks * T
    assert evaluate_lsr(_inputs(vpoc=close)) is None


def test_sans_prints_pas_d_extreme_silence():
    assert evaluate_lsr(_inputs(prints=[])) is None


def test_valeurs_non_finies_silence():
    now = time.time()
    assert evaluate_lsr(_inputs(aggressor_ratio=math.nan)) is None
    assert evaluate_lsr(_inputs(vpoc=math.inf)) is None
    bad_prints = _prints(now, low=4998.0)
    bad_prints[2] = {**bad_prints[2], "price": math.nan}
    plan = evaluate_lsr(_inputs(now=now, prints=bad_prints))             # print sale ignoré, pas un crash
    assert plan is None or plan["status"] == "APPROVED"


# --- build_lsr_inputs : FRESH only (§3) ----------------------------------------------------

def test_build_inputs_ignore_le_perime():
    now = time.time()
    eng = Engine(MockDataSource(), RedisState())
    eng.schema.s1_state.tape = MetaField(value=_prints(now, low=4998.0),
                                         last_update_ts=now - 300, source="test",
                                         freshness=Freshness.STALE)
    i = build_lsr_inputs(eng.schema, now)
    assert i.prints == []                       # périmé = absent, jamais un extrême fantôme


# --- Pipeline engine : émission SSE dédupliquée, sans replay -------------------------------



def _acct() -> MockAccountProvider:
    """Compte Apex 50K sain, toujours frais (D-047) — sans lui, AUCUNE émission (à l'aveugle)."""
    return MockAccountProvider(state=apex_eod_account(APEX_EOD_50K), always_fresh=True)

def _wire_setup(eng, now):
    """Câble un setup complet : rafale vendeuse (→ BID_SWEEP), gates au vert, VPOC au-dessus.
    Le calendrier T1 imminent est une exigence du DÉTECTEUR (D-028 : anomalie couplée à une
    news T1) — la couche LSR elle-même n'en lit rien (isolation D-046)."""
    eng.schema.econ_calendar.events = _fresh(
        [{"ts": now + 300, "name": "NFP — emplois US", "tier": 1, "region": "US"}], now)
    s1 = eng.schema.s1_state
    s1.tape = _fresh([{"ts": now - 1.0 + 0.1 * k, "price": 4998.0 + 0.25 * (k % 4),
                       "size": 5.0, "side": "SELL", "seq": k} for k in range(10)], now)
    s1.order_book = _fresh(_book(), now)
    s1.order_flow.absorption = _fresh(True, now)
    s1.order_flow.aggressor_ratio = _fresh(0.72, now)
    s1.structure.vpoc = _fresh(5000.0, now)
    # VIX FRAIS obligatoire depuis D-070 : sans lui le sizer est aveugle et rien n'est émis.
    eng.schema.s2_state.cascade.vix = _fresh(12.0, now)      # régime calme → multiplicateur 1.0


def test_pipeline_sweep_vers_manifeste_emis_et_deduplique():
    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=_acct())
        _wire_setup(eng, now)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()                      # purge le replay des blocs d'autres tests
        await eng._assemble_sweep(now)
        assert eng.schema.liquidity_sweep.triggered is True
        assert eng.schema.liquidity_sweep.alert.direction == "BID_SWEEP"
        eng._maybe_emit_lsr(now)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        manifests = [e for e in events if e["event"] == "trade_manifest"]
        assert len(manifests) == 1
        import json
        m = json.loads(manifests[0]["data"])
        assert m["direction"] == "BUY" and m["instrument"] == config.LSR_INSTRUMENT
        assert m["risk"]["stopLoss"] < m["entry"]["price"] < m["risk"]["takeProfit"]
        assert m["timeToLiveMs"] == 3000 and m["id"]

        # dédup : condition PERSISTANTE (rafale re-fraîche → l'alerte est régénérée avec un ts
        # neuf mais le même trigger|direction) → aucune seconde émission
        _wire_setup(eng, now + 2)
        await eng._assemble_sweep(now + 2)
        assert eng.schema.liquidity_sweep.triggered is True
        eng._maybe_emit_lsr(now + 2)
        mid = []
        while not q.empty():
            mid.append(q.get_nowait())                           # republication du bloc sweep, ok
        assert all(e["event"] != "trade_manifest" for e in mid)

        # F7 anti-FOMO : condition levée puis NOUVEAU sweep DANS la fenêtre de cooldown →
        # silence (sous un détecteur qui bascule en continu, la clé seule laisserait spammer)
        eng.schema.s1_state.tape = _fresh([], now + 10)          # plus de rafale
        await eng._assemble_sweep(now + 10)
        assert eng.schema.liquidity_sweep.triggered is False
        eng._maybe_emit_lsr(now + 10)                            # tick sans sweep → reset de la clé
        _wire_setup(eng, now + 20)                               # nouveau sweep, cooldown pas écoulé
        await eng._assemble_sweep(now + 20)
        eng._maybe_emit_lsr(now + 20)
        while not q.empty():
            assert q.get_nowait()["event"] != "trade_manifest"

        # après la fenêtre F7 : événement neuf → NOUVEAU manifeste (miroir D-028)
        t2 = now + config.LSR_REARM_COOLDOWN_S + 20
        eng.schema.s1_state.tape = _fresh([], t2 - 5)
        await eng._assemble_sweep(t2 - 5)                        # levée → reset de la clé
        eng._maybe_emit_lsr(t2 - 5)
        while not q.empty():
            q.get_nowait()
        _wire_setup(eng, t2)
        await eng._assemble_sweep(t2)
        eng._maybe_emit_lsr(t2)
        renewed = []
        while not q.empty():
            renewed.append(q.get_nowait())
        assert sum(1 for e in renewed if e["event"] == "trade_manifest") == 1

        # pas de replay : un abonné NEUF ne reçoit jamais un manifeste d'avant sa connexion
        q2 = broadcaster.subscribe("fast")
        replayed = []
        while not q2.empty():
            replayed.append(q2.get_nowait())
        assert all(e["event"] != "trade_manifest" for e in replayed)
        broadcaster.unsubscribe("fast", q)
        broadcaster.unsubscribe("fast", q2)
    asyncio.run(scenario())


def test_pipeline_gates_rouges_aucune_emission():
    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=_acct())
        _wire_setup(eng, now)
        eng.schema.s1_state.order_flow.absorption = _fresh(False, now)   # B1 rouge
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        eng._maybe_emit_lsr(now)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        assert all(e["event"] != "trade_manifest" for e in events)       # silence total
        broadcaster.unsubscribe("fast", q)
    asyncio.run(scenario())


# --- /devil D-046 : pathologies de microstructure --------------------------------------------

def test_devil_carnet_croise_ou_verrouille_silence():
    """Un marché croisé (bid ≥ ask) n'a pas de spread tradable — la géométrie ne doit JAMAIS
    se construire dessus, même si le détecteur amont a signalé la dislocation (CROSSED_BOOK)."""
    crossed = {"bids": [[5001.0, 70.0], [5000.75, 70.0], [5000.5, 70.0]],
               "asks": [[5000.0, 70.0], [5000.25, 70.0], [5000.5, 70.0]]}   # bid > ask
    assert evaluate_lsr(_inputs(book=crossed)) is None
    locked = {"bids": [[5000.0, 70.0], [4999.75, 70.0], [4999.5, 70.0]],
              "asks": [[5000.0, 70.0], [5000.25, 70.0], [5000.5, 70.0]]}    # bid == ask
    assert evaluate_lsr(_inputs(book=locked)) is None


def test_devil_ratio_agressivite_hors_bornes_corruption_de_flux():
    """Une part acheteuse est une FRACTION : hors [0,1] = erreur de flux source. Un 1.7 corrompu
    passerait la gate LONG (≥ 0.60) comme un flip ultra-fort — il doit être rejeté."""
    for bad in (1.7, 1.0000001, -0.2, 2.0):
        assert evaluate_lsr(_inputs(aggressor_ratio=bad)) is None, bad
    # bornes exactes : 1.0 et 0.0 sont des valeurs LÉGITIMES (100 % / 0 % acheteurs)
    assert evaluate_lsr(_inputs(aggressor_ratio=1.0)) is not None
    assert evaluate_lsr(_inputs(sweep_direction="ASK_SWEEP",
                                prints=_prints(time.time(), high=5002.0),
                                aggressor_ratio=0.0)) is not None


def test_devil_prints_du_futur_n_ancrent_jamais_l_extreme():
    """Désync d'horloge source : un print daté APRÈS now (même leçon que D-028) ne doit pas
    définir la structure — sans lui, plus d'extrême sous 4999 → géométrie différente ou rejet."""
    now = time.time()
    prints = _prints(now)                                   # extrême naturel = 5000.0
    prints.append({"ts": now + 30, "price": 4990.0, "size": 3.0, "side": "SELL", "seq": 99})
    plan = evaluate_lsr(_inputs(now=now, prints=prints))
    if plan is not None:                                    # si la géométrie tient encore…
        assert plan["executionPlan"]["stopLoss"] > 4990.0   # …jamais ancrée sur le print fantôme


def test_devil_prix_non_positifs_jamais_dans_la_geometrie():
    """Un prix ≤ 0 sur ES est de la corruption — il ne doit ni ancrer l'extrême ni produire un
    manifeste à niveaux négatifs (la garde D-045 vérifie l'ordre, pas la positivité)."""
    now = time.time()
    prints = _prints(now)
    prints[3] = {**prints[3], "price": -5000.0}             # print corrompu négatif
    plan = evaluate_lsr(_inputs(now=now, prints=prints))
    if plan is not None:
        assert plan["executionPlan"]["stopLoss"] > 0
    prints_zero = _prints(now)
    prints_zero[3] = {**prints_zero[3], "price": 0.0}
    plan0 = evaluate_lsr(_inputs(now=now, prints=prints_zero))
    if plan0 is not None:
        assert plan0["executionPlan"]["stopLoss"] > 0
    assert evaluate_lsr(_inputs(vpoc=-5000.0)) is None      # VPOC négatif = corruption
    assert evaluate_lsr(_inputs(vpoc=0.0)) is None


def test_devil_tailles_de_carnet_negatives_corruption():
    """Une profondeur NÉGATIVE est impossible — un carnet qui en porte est corrompu et ne doit
    pas passer F4 par compensation arithmétique (200 + (−30) ≥ 150…)."""
    book = {"bids": [[4999.75, 200.0], [4999.5, -30.0], [4999.25, 70.0]],
            "asks": [[5000.25, 70.0], [5000.5, 70.0], [5000.75, 70.0]]}
    assert evaluate_lsr(_inputs(book=book)) is None


def test_devil_cooldown_bloque_aussi_le_sweep_inverse():
    """F7 vs inversion de biais : un BID_SWEEP valide (→ LONG émis) suivi à 10 s d'un ASK_SWEEP
    tout aussi valide → la fenêtre F7 bloque AVEUGLÉMENT, par conception. Deux sweeps opposés en
    10 s = régime de chop/whipsaw, le piège exact que LSR refuse de trader ; et une proposition
    vient peut-être d'être ACKée (position possible — invisible d'ici, §2.1) → jamais le ticket
    contraire dans la fenêtre. Après la fenêtre, l'inverse redevient proposable."""
    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=_acct())
        _wire_setup(eng, now)                               # rafale vendeuse → BID_SWEEP → LONG
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_sweep(now)
        eng._maybe_emit_lsr(now)
        first = [e for e in _drain(q) if e["event"] == "trade_manifest"]
        assert len(first) == 1

        def wire_ask(t):                                    # rafale ACHETEUSE → ASK_SWEEP → SHORT
            s1 = eng.schema.s1_state
            s1.tape = _fresh([{"ts": t - 1.0 + 0.1 * k, "price": 5002.0 - 0.25 * (k % 4),
                               "size": 5.0, "side": "BUY", "seq": 100 + k} for k in range(10)], t)
            s1.order_flow.aggressor_ratio = _fresh(0.25, t)
            s1.structure.vpoc = _fresh(4999.0, t)           # sous l'entrée → chemin SHORT valide

        wire_ask(now + 10)                                  # inversion 10 s plus tard
        await eng._assemble_sweep(now + 10)
        assert eng.schema.liquidity_sweep.alert.direction == "ASK_SWEEP"
        eng._maybe_emit_lsr(now + 10)
        assert [e for e in _drain(q) if e["event"] == "trade_manifest"] == []   # F7 : silence

        t2 = now + config.LSR_REARM_COOLDOWN_S + 5          # fenêtre écoulée
        wire_ask(t2)
        await eng._assemble_sweep(t2)
        eng._maybe_emit_lsr(t2)
        import json
        after = [e for e in _drain(q) if e["event"] == "trade_manifest"]
        assert len(after) == 1
        assert json.loads(after[0]["data"])["direction"] == "SELL"
        broadcaster.unsubscribe("fast", q)
    asyncio.run(scenario())


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


# --- /polish D-046 : hygiène des logs ---------------------------------------------------------

def test_polish_rejet_naturel_zero_log_emission_un_seul_info(caplog):
    """Le moteur évalue en continu : un rejet naturel (gate rouge, carnet invalide, corruption)
    ne produit AUCUNE ligne de log ; seule l'émission d'un manifeste écrit — une seule fois,
    au niveau INFO."""
    import logging

    async def scenario():
        now = time.time()
        eng = Engine(MockDataSource(), RedisState(), account_provider=_acct())
        _wire_setup(eng, now)
        eng.schema.s1_state.order_flow.absorption = _fresh(False, now)     # gate B1 rouge
        await eng._assemble_sweep(now)

        with caplog.at_level(logging.DEBUG):
            caplog.clear()
            for k in range(5):                                            # 5 rejets consécutifs
                eng._maybe_emit_lsr(now + k * 0.1)
            assert caplog.records == []                                   # silence TOTAL

            eng.schema.s1_state.order_flow.absorption = _fresh(True, now)  # gates au vert
            eng._maybe_emit_lsr(now + 1)
            lsr = [r for r in caplog.records if "LSR" in r.getMessage()]
            assert len(lsr) == 1 and lsr[0].levelno == logging.INFO       # UNE ligne INFO
            assert caplog.records == lsr                                  # et rien d'autre

            eng._maybe_emit_lsr(now + 2)                                  # dédup → silence aussi
            assert len([r for r in caplog.records if "LSR" in r.getMessage()]) == 1
    asyncio.run(scenario())
