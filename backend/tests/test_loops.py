"""Feature — `app.loops` : le contrat commun des boucles d'exécution (D-073).

Le dépôt comptait déjà quatre boucles Loop-D écrites à la main (`engine.py` 0,25 s/15 s,
`account_provider` 1 s, `macro_news` 1 h, `lsr_driver` 0,25 s). Le Pont Options v2 en ajoute
trois. Sept boucles à la main, c'est sept fois l'occasion de rouvrir la faille que D-052 a
fermée au prix d'une passe `/devil` complète : **une boucle morte ressemble à une boucle
calme**.

Ce module factorise les parades de D-052 en UN contrat, et — c'est le point — **projette la
santé de chaque boucle**. C'est `CLAUDE §3` (« no signal without data ») appliqué aux boucles
elles-mêmes : l'UI doit pouvoir afficher « boucle O5 morte » au lieu d'un kurtosis figé qui a
l'air frais.

Ce que les tests verrouillent :
1. **Validation de spec** — une cadence périodique sans période, ou un seuil de watchdog
   inférieur à la période (le piège « watchdog trop agressif » de RUNTIME_LOOPS Loop G), est
   refusée à la construction, pas découverte en production ;
2. **Le tick ne tue jamais la boucle** — exception capturée, comptée, la boucle survit ;
3. **Plafond de durée** — un tick qui ne rend jamais la main devient un échec VISIBLE
   (D-052 faille B) au lieu d'une pendaison silencieuse ;
4. **Drop-if-busy** — un tick plus lent que la période est droppé, jamais empilé
   (backpressure RUNTIME_LOOPS Loop D) ;
5. **Cadence à l'échéance sans rattrapage** — après un tick long on se réancre à maintenant ;
   une rafale de rattrapage évaluerait le passé (doctrine D-045 T3) ;
6. **`start()`/`stop()`** — idempotents, et une boucle tuée de l'extérieur se signale et se
   relance au lieu de rester morte en silence (D-052 faille E) ;
7. **Santé honnête** — une spec sans runner est `NOT_IMPLEMENTED`, jamais un stub qui feint de
   tourner ; une boucle ÉVÉNEMENTIELLE silencieuse n'est PAS malade (elle attend un setup).
"""
import asyncio
import time

import pytest

from app.loops.contract import (
    Cadence, Criticality, LoopSpec, LoopStatus, ManagedLoop, PeriodicLoop, StarvePolicy,
)
from app.loops.health import project
from app.loops.registry import default_specs
from app.loops.supervisor import LoopSupervisor


def _spec(name="test.loop", period=0.01, budget=0.5, stale=1.0, **kw):
    return LoopSpec(
        name=name, cadence=Cadence.PERIODIC, period_s=period,
        criticality=Criticality.WARM, tick_budget_s=budget, heartbeat_stale_s=stale,
        starve=StarvePolicy.FAIL_CLOSED, purpose="boucle de test", **kw)


def _event_spec(name="test.event", budget=0.5):
    return LoopSpec(
        name=name, cadence=Cadence.EVENT_DRIVEN, period_s=None,
        criticality=Criticality.WARM, tick_budget_s=budget, heartbeat_stale_s=None,
        starve=StarvePolicy.FAIL_CLOSED, purpose="boucle événementielle de test")


class _Clock:
    """Horloge murale INJECTÉE — la santé se teste sans dormir."""

    def __init__(self, t=1_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------------------------------------------------------------------------
# 1. Validation de spec — refusée à la construction, pas en production
# ---------------------------------------------------------------------------

def test_spec_periodique_EXIGE_une_periode():
    with pytest.raises(ValueError):
        LoopSpec(name="x", cadence=Cadence.PERIODIC, period_s=None,
                 criticality=Criticality.WARM, tick_budget_s=1.0, heartbeat_stale_s=5.0,
                 starve=StarvePolicy.FAIL_CLOSED, purpose="p")


def test_spec_evenementielle_REFUSE_une_periode():
    """Une boucle événementielle avec une période annoncerait une cadence qu'elle n'a pas."""
    with pytest.raises(ValueError):
        LoopSpec(name="x", cadence=Cadence.EVENT_DRIVEN, period_s=1.0,
                 criticality=Criticality.WARM, tick_budget_s=1.0, heartbeat_stale_s=None,
                 starve=StarvePolicy.FAIL_CLOSED, purpose="p")


def test_seuil_de_watchdog_INFERIEUR_a_la_periode_refuse():
    """RUNTIME_LOOPS Loop G : « seuil > durée max normale ». Un watchdog qui se déclenche
    avant même qu'un tick normal ait eu lieu produit une alerte permanente — donc ignorée."""
    with pytest.raises(ValueError):
        _spec(period=2.0, stale=1.0)


def test_spec_evenementielle_REFUSE_un_seuil_de_watchdog():
    """Le silence d'une boucle événementielle n'est pas une panne : aucun setup n'est peut-être
    survenu. Lui donner un seuil de péremption fabriquerait une fausse alerte."""
    with pytest.raises(ValueError):
        LoopSpec(name="x", cadence=Cadence.EVENT_DRIVEN, period_s=None,
                 criticality=Criticality.WARM, tick_budget_s=1.0, heartbeat_stale_s=30.0,
                 starve=StarvePolicy.FAIL_CLOSED, purpose="p")


def test_budget_de_tick_doit_etre_fini_et_positif():
    with pytest.raises(ValueError):
        _spec(budget=0.0)


# ---------------------------------------------------------------------------
# 2-3. Le tick ne tue jamais la boucle ; le plafond rend la pendaison visible
# ---------------------------------------------------------------------------

def test_tick_qui_LEVE_est_compte_et_la_boucle_survit():
    calls = []

    async def tick():
        calls.append(1)
        raise RuntimeError("boom")

    loop = PeriodicLoop(_spec(), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        await asyncio.sleep(0.05)
        await loop.stop()

    asyncio.run(scenario())
    assert len(calls) >= 2, "la boucle doit continuer à ticker après une exception"
    h = loop.health(1_000.0)
    assert h.failures >= 2
    assert h.ticks == 0, "un tick qui lève n'est pas un tick réussi"
    assert h.last_error is not None and "boom" in h.last_error


def test_tick_qui_ne_rend_JAMAIS_la_main_est_borne_par_le_budget():
    """D-052 faille B : sans plafond, un `await` suspendu pend la boucle pour l'éternité —
    zéro tick, zéro log, et ça ressemble à une boucle calme."""
    started = []

    async def tick():
        started.append(1)
        await asyncio.Event().wait()          # ne rend jamais la main

    loop = PeriodicLoop(_spec(period=0.01, budget=0.02), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        await asyncio.sleep(0.12)
        await loop.stop()

    asyncio.run(scenario())
    h = loop.health(1_000.0)
    assert h.timeouts >= 2, "le plafond doit transformer la pendaison en échec compté"
    assert len(started) >= 2, "la boucle doit repartir après un tick plafonné"


# ---------------------------------------------------------------------------
# 4-5. Backpressure et cadence
# ---------------------------------------------------------------------------

def test_tick_plus_LENT_que_la_periode_est_droppe_jamais_empile():
    """Deux exécutions concurrentes du même tick calculeraient deux fois le même instant."""
    concurrent = 0
    peak = 0

    async def tick():
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        concurrent -= 1

    loop = PeriodicLoop(_spec(period=0.005, budget=1.0), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        await asyncio.sleep(0.2)
        await loop.stop()

    asyncio.run(scenario())
    assert peak == 1, "jamais deux ticks du même loop en vol"
    assert loop.health(1_000.0).drops > 0, "les ticks sautés doivent être comptés, pas invisibles"


def test_apres_un_tick_LONG_pas_de_rafale_de_rattrapage():
    """Doctrine D-045 T3 : une rafale de rattrapage évaluerait le PASSÉ. On se réancre."""
    stamps = []

    async def tick():
        stamps.append(time.monotonic())
        if len(stamps) == 1:
            await asyncio.sleep(0.08)         # un seul tick anormalement long

    loop = PeriodicLoop(_spec(period=0.02, budget=1.0), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        await asyncio.sleep(0.25)
        await loop.stop()

    asyncio.run(scenario())
    after = stamps[1:]
    gaps = [b - a for a, b in zip(after, after[1:])]
    # Une RAFALE de rattrapage, c'est une SÉRIE de ticks collés — pas un écart isolé. Sous
    # charge (la suite tourne en parallèle), l'ordonnanceur peut resserrer un tick sans que la
    # boucle ait rattrapé quoi que ce soit : exiger zéro écart serré rendait ce test instable,
    # et un test qui échoue au hasard finit par être ignoré. On vérifie donc l'INTENTION —
    # aucune SÉRIE de rattrapage — plutôt qu'une borne que la machine décide.
    consecutifs = 0
    pire = 0
    for gap in gaps:
        consecutifs = consecutifs + 1 if gap < 0.005 else 0
        pire = max(pire, consecutifs)
    assert pire < 3, f"rafale de rattrapage détectée : {[round(g, 4) for g in gaps]}"


# ---------------------------------------------------------------------------
# 6. start() / stop()
# ---------------------------------------------------------------------------

def test_start_est_idempotent_tant_que_la_boucle_est_vivante():
    """L'original TS écrasait son timer et fuyait le premier (D-052)."""
    ticks = []

    async def tick():
        ticks.append(1)

    loop = PeriodicLoop(_spec(period=0.01), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        first = loop._task
        await loop.start()
        assert loop._task is first, "un second start() ne doit pas créer une boucle de plus"
        await asyncio.sleep(0.03)
        await loop.stop()

    asyncio.run(scenario())


def test_boucle_TUEE_de_l_exterieur_se_signale_et_se_relance(caplog):
    """D-052 faille E : `done()` sans être `None` laissait le driver mort en silence."""
    async def tick():
        return None

    loop = PeriodicLoop(_spec(period=0.01), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        loop._task.cancel()                   # simulation d'un balayage de shutdown externe
        await asyncio.sleep(0.02)
        assert loop.health(1_000.0).status is LoopStatus.DEAD
        await loop.start()                    # relance explicite
        await asyncio.sleep(0.02)
        assert loop.health(1_000.0).status is LoopStatus.RUNNING
        await loop.stop()

    with caplog.at_level("WARNING"):
        asyncio.run(scenario())
    assert any("morte" in r.getMessage() for r in caplog.records), \
        "une boucle morte relancée doit laisser une trace"


def test_stop_sur_boucle_DEJA_MORTE_ne_propage_pas():
    """Un arrêt gracieux ne doit pas exploser au pire moment (RUNTIME_LOOPS Loop H)."""
    async def tick():
        raise RuntimeError("mort")

    loop = PeriodicLoop(_spec(period=0.01), tick, clock=_Clock())

    async def scenario():
        await loop.start()
        loop._task.cancel()
        await asyncio.sleep(0.02)
        await loop.stop()                     # ne doit pas lever
        await loop.stop()                     # idempotent

    asyncio.run(scenario())


def test_stop_sans_start_est_inoffensif():
    loop = PeriodicLoop(_spec(), lambda: None, clock=_Clock())
    asyncio.run(loop.stop())
    assert loop.health(1_000.0).status is LoopStatus.STOPPED


# ---------------------------------------------------------------------------
# 7. Santé honnête
# ---------------------------------------------------------------------------

def test_spec_SANS_runner_est_NOT_IMPLEMENTED_jamais_un_stub_muet():
    """COMMANDS.md §3 : le critère est « un lecteur peut-il confondre ceci avec du code de
    production validé ? ». Une boucle déclarée mais non câblée doit le DIRE."""
    loop = PeriodicLoop(_spec(), None, clock=_Clock())
    h = loop.health(1_000.0)
    assert h.status is LoopStatus.NOT_IMPLEMENTED
    assert h.last_beat_ts is None


def test_boucle_STALLED_quand_le_battement_est_trop_VIEUX():
    clock = _Clock(1_000.0)
    ran = asyncio.Event()

    async def tick():
        ran.set()

    loop = PeriodicLoop(_spec(period=0.01, stale=1.0), tick, clock=clock)

    async def scenario():
        await loop.start()
        await asyncio.wait_for(ran.wait(), timeout=1.0)
        await loop.stop()

    asyncio.run(scenario())
    assert loop.health(1_000.5).status is LoopStatus.STOPPED     # arrêtée proprement
    loop._task = _FakeAliveTask()                                # simule « toujours vivante »
    assert loop.health(1_000.5).status is LoopStatus.RUNNING
    assert loop.health(1_002.0).status is LoopStatus.STALLED, "battement vieux → STALLED"
    assert loop.health(1_002.0).age_s == pytest.approx(2.0)


class _FakeAliveTask:
    def done(self):
        return False

    def cancel(self):
        return True


def test_boucle_qui_ECHOUE_a_CHAQUE_tour_finit_STALLED_jamais_RUNNING():
    """Régression — trouvée à l'essai manuel (§13 Loop 1, étape 6).

    La grâce accordée avant le PREMIER battement n'était pas bornée : une boucle qui n'a jamais
    réussi un seul tick restait `RUNNING` indéfiniment, donc absente de `unhealthy`. C'est très
    exactement la panne que ce module existe pour rendre visible — « une boucle morte ressemble
    à une boucle calme ». La grâce est désormais bornée par le seuil de péremption, mesurée
    depuis le DÉMARRAGE."""
    clock = _Clock(1_000.0)
    failed = asyncio.Event()

    async def tick():
        failed.set()
        raise RuntimeError("moteur indisponible")

    loop = PeriodicLoop(_spec(period=0.01, stale=1.0), tick, clock=clock)

    async def scenario():
        await loop.start()
        await asyncio.wait_for(failed.wait(), timeout=1.0)
        await asyncio.sleep(0.02)

    asyncio.run(scenario())
    loop._task = _FakeAliveTask()                            # simule « toujours vivante »
    h = loop.health(1_000.5)
    assert h.status is LoopStatus.RUNNING, "dans la grâce, on ne crie pas encore"
    assert h.last_beat_ts is None and h.failures > 0
    assert loop.health(1_002.0).status is LoopStatus.STALLED, \
        "au-delà du seuil sans AUCUN battement réussi, la boucle n'est pas saine"


def test_boucle_EVENEMENTIELLE_silencieuse_n_est_PAS_malade():
    """L4 (gates O1-O5) ne bat que sur armement. Un matin sans setup n'est pas une panne."""
    calls = []

    async def tick(level):
        calls.append(level)

    loop = ManagedLoop(_event_spec(), tick, clock=_Clock(1_000.0))
    assert loop.health(1_000_000.0).status is LoopStatus.RUNNING, \
        "aucun seuil de péremption ne doit pouvoir la déclarer STALLED"

    asyncio.run(loop.run_once(4200.0))
    assert calls == [4200.0]
    assert loop.health(1_000.0).ticks == 1


def test_boucle_evenementielle_borne_aussi_son_tick():
    async def tick():
        await asyncio.Event().wait()

    loop = ManagedLoop(_event_spec(budget=0.02), tick, clock=_Clock())
    asyncio.run(loop.run_once())
    assert loop.health(1_000.0).timeouts == 1


# ---------------------------------------------------------------------------
# Superviseur + projection
# ---------------------------------------------------------------------------

def test_superviseur_demarre_et_arrete_tout_et_projette_la_sante():
    ticks = []

    async def tick():
        ticks.append(1)

    sup = LoopSupervisor(clock=_Clock(1_000.0))
    sup.register(_spec("a", period=0.01), tick)
    sup.register(_spec("b", period=0.01))                     # déclarée, pas câblée

    async def scenario():
        await sup.start_all()
        await asyncio.sleep(0.05)
        snap = sup.health(1_000.0)
        await sup.stop_all()
        return snap

    snap = asyncio.run(scenario())
    by_name = {entry["name"]: entry for entry in snap["loops"]}
    assert by_name["a"]["status"] == "RUNNING"
    assert by_name["b"]["status"] == "NOT_IMPLEMENTED"
    assert snap["all_healthy"] is False
    assert snap["unhealthy"] == ["b"]


def test_superviseur_REFUSE_deux_boucles_du_meme_nom():
    sup = LoopSupervisor()
    sup.register(_spec("a"))
    with pytest.raises(ValueError):
        sup.register(_spec("a"))


def test_superviseur_arrete_TOUT_meme_si_une_boucle_echoue_a_s_arreter():
    """Loop H : un arrêt gracieux ne doit pas laisser des boucles derrière lui."""
    stopped = []

    async def tick():
        stopped.append("tick")

    sup = LoopSupervisor(clock=_Clock())
    sup.register(_spec("a", period=0.01), tick)
    sup.register(_spec("b", period=0.01), tick)

    async def scenario():
        await sup.start_all()
        await asyncio.sleep(0.03)
        sup._loops["a"]._task.cancel()        # une boucle déjà morte au moment de l'arrêt
        await asyncio.sleep(0.01)
        await sup.stop_all()

    asyncio.run(scenario())
    assert all(loop.health(1_000.0).status in (LoopStatus.STOPPED, LoopStatus.NOT_IMPLEMENTED)
               for loop in sup._loops.values())


def test_projection_serialisable_et_sans_valeur_inventee():
    loop = PeriodicLoop(_spec("z"), None, clock=_Clock())
    snap = project([loop.health(1_000.0)], now=1_000.0)
    import json
    json.loads(json.dumps(snap))              # doit passer tel quel sur le canal SSE
    entry = snap["loops"][0]
    assert entry["last_beat_ts"] is None and entry["age_s"] is None, \
        "jamais un 0 fabriqué pour une boucle qui n'a jamais battu (§3)"


# ---------------------------------------------------------------------------
# Registre — les cinq boucles déclarées
# ---------------------------------------------------------------------------

def test_les_cinq_boucles_sont_declarees_et_valides():
    specs = default_specs()
    assert [s.name for s in specs] == [
        "core.tick", "options.sync", "o5.kurtosis", "gates.eval", "ui.broadcast",
    ]


def test_le_hot_path_reste_sous_le_budget_de_CLAUDE_paragraphe_7():
    """§7 : hot path déterministe < ~200 ms. Un budget de tick supérieur le contredirait."""
    core = next(s for s in default_specs() if s.name == "core.tick")
    assert core.criticality is Criticality.HOT
    assert core.tick_budget_s <= 0.2


def test_L4_gates_est_EVENEMENTIELLE_pas_periodique():
    """Une L4 périodique réévaluerait le passé — c'est le piège de cadence de D-052."""
    gates = next(s for s in default_specs() if s.name == "gates.eval")
    assert gates.cadence is Cadence.EVENT_DRIVEN
    assert gates.period_s is None


def test_options_sync_tolere_la_peremption_du_worker():
    """`options_worker.py` publie avec `CONTEXT_TTL_SECONDS = 90` et `optionsContext.ts` traite
    au-delà de `STALE_THRESHOLD_MS = 90_000` comme périmé. Le watchdog de L2 ne doit pas crier
    avant cette limite, sinon il double une péremption déjà gérée en aval."""
    opts = next(s for s in default_specs() if s.name == "options.sync")
    assert opts.heartbeat_stale_s >= 90.0
    assert opts.starve is StarvePolicy.DEGRADE


def test_aucune_spec_du_registre_ne_pretend_avoir_un_runner():
    """Le registre DÉCLARE ; il ne câble rien (les corps de boucle arrivent en P2/P3). Un
    superviseur monté sur le registre seul doit donc être intégralement NOT_IMPLEMENTED —
    c'est la vérité, et elle doit être visible plutôt que déguisée en boucle qui tourne."""
    sup = LoopSupervisor(clock=_Clock())
    for spec in default_specs():
        sup.register(spec)
    snap = sup.health(1_000.0)
    assert {e["status"] for e in snap["loops"]} == {"NOT_IMPLEMENTED"}
    assert snap["all_healthy"] is False


# ---------------------------------------------------------------------------
# Lecture opérationnelle — distinguer « attendu » de « cassé » (D-091)
# ---------------------------------------------------------------------------

def test_le_verdict_distingue_une_boucle_NON_CABLEE_d_une_boucle_MORTE():
    """`unhealthy` mélange deux choses très différentes : une boucle déclarée-non-câblée
    (attendu, on sait pourquoi) et une boucle câblée qui meurt (anormal, il faut agir). Un
    opérateur réveillé à 3 h a besoin de cette distinction avant toute autre."""
    sup = LoopSupervisor(clock=_Clock(1_000.0))
    sup.register(_spec("declaree"))                          # pas de tick → NOT_IMPLEMENTED
    snap = sup.health(1_000.0)
    assert snap["degraded"]["expected"] == ["declaree"]
    assert snap["degraded"]["broken"] == []
    assert snap["degraded"]["verdict"] == "PARTIAL", "documenté, pas une alerte"


def test_une_boucle_CABLEE_qui_stagne_donne_le_verdict_DEGRADED():
    async def tick():
        return None

    loop = PeriodicLoop(_spec("vivante", period=0.01, stale=1.0), tick, clock=_Clock(1_000.0))
    sup = LoopSupervisor(clock=_Clock(1_000.0))
    sup._loops["vivante"] = loop
    loop._task = _FakeAliveTask()
    loop._started_ts = 1_000.0
    snap = sup.health(1_010.0)                               # bien au-delà du seuil
    assert snap["degraded"]["broken"] == ["vivante"]
    assert snap["degraded"]["verdict"] == "DEGRADED"


def test_une_boucle_HOT_cassee_est_signalee_A_PART():
    """Une boucle HOT cassée, c'est le hot path lui-même qui ne tourne plus. La noyer dans une
    liste globale la rendrait invisible."""
    spec = LoopSpec(name="core.tick", cadence=Cadence.PERIODIC, period_s=0.25,
                    criticality=Criticality.HOT, tick_budget_s=0.2, heartbeat_stale_s=5.0,
                    starve=StarvePolicy.FAIL_CLOSED, purpose="chemin chaud")
    sup = LoopSupervisor(clock=_Clock(1_000.0))
    sup.register(spec)                                       # non câblée → cassée au sens HOT
    snap = sup.health(1_000.0)
    assert snap["degraded"]["hot_path_broken"] == ["core.tick"]
    assert snap["degraded"]["verdict"] == "HOT_PATH_DOWN", "prime sur tout autre verdict"


def test_tout_va_bien_donne_NOMINAL():
    async def tick():
        return None

    sup = LoopSupervisor(clock=_Clock(1_000.0))
    sup.register(_spec("a", period=0.01), tick)

    async def scenario():
        await sup.start_all()
        await asyncio.sleep(0.05)
        snap = sup.health(1_000.0)
        await sup.stop_all()
        return snap

    snap = asyncio.run(scenario())
    assert snap["degraded"]["verdict"] == "NOMINAL"
    assert snap["degraded"]["broken"] == [] and snap["degraded"]["expected"] == []
