"""Feature — harnais de rejeu bout-en-bout (D-081, phase P3).

MBO → carnet → armement → simulateur FIFO → **PnL réalisé**. Ferme la boucle laissée ouverte
en D-080 : l'issue est un event ultérieur qui référence l'armement (`CLAUDE §2.5`).

**Ce que ces tests protègent en priorité : `NO_FILL` comme issue de première classe.** Un setup
dont l'entrée limite n'est jamais servie n'est ni un gain ni une perte — il n'a pas eu lieu.
C'est très exactement ce qu'un backtest « rempli au touché » compte comme gagnant.
"""
import pytest

from app.mbo.book import MboBook
from app.mbo.events import MboAction, MboEvent, MboSide
from app.replay_harness import ReplayHarness, Setup, summarize

TICK = 0.25
BASE_NS = 1_700_000_000_000_000_000


def _ev(action, side, price, size, order_id=0, ms=0):
    return MboEvent(ts_event=BASE_NS + ms * 1_000_000, ts_recv=BASE_NS + ms * 1_000_000,
                    action=action, side=side, price=price, size=size,
                    order_id=order_id, sequence=ms, symbol="MESZ4")


def _setup(**over):
    base = dict(setup_id="s-1", side="LONG", entry_price=5000.00, stop_loss=4999.00,
                take_profit=5001.25, qty=1.0)
    base.update(over)
    return Setup(**base)


def _arm_once(setup):
    """Arme au premier événement, une seule fois."""
    state = {"done": False}

    def arm(book, event):
        if state["done"]:
            return None
        state["done"] = True
        return setup

    return arm


def _seed_book(ms=0):
    """Deux événements d'amorçage : un bid et un ask au repos."""
    return [_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101, ms=ms),
            _ev(MboAction.ADD, MboSide.ASK, 5000.25, 30, order_id=102, ms=ms + 1)]


# ---------------------------------------------------------------------------
# NO_FILL — l'issue que le harnais existe pour produire
# ---------------------------------------------------------------------------

def test_une_entree_JAMAIS_servie_donne_NO_FILL_pas_un_gain():
    """40 lots dorment devant nous ; seuls 10 s'échangent au prix. L'entrée n'est jamais
    servie — un backtest naïf aurait compté ce setup comme un trade."""
    h = ReplayHarness(tick_size=TICK)
    events = _seed_book() + [
        _ev(MboAction.TRADE, MboSide.BID, 5000.00, 10, order_id=0, ms=10),
        _ev(MboAction.TRADE, MboSide.BID, 5000.00, 10, order_id=0, ms=20),
    ]
    outcomes = h.run(events, _arm_once(_setup()))
    assert len(outcomes) == 1
    assert outcomes[0].status == "NO_FILL"
    assert outcomes[0].pnl_usd is None, "une absence de trade n'est pas un PnL nul"
    assert outcomes[0].entry_queue_ahead == 40.0


def test_NO_FILL_n_est_pas_compte_dans_le_taux_de_reussite():
    """Mélanger « la stratégie gagne-t-elle ? » et « les entrées sont-elles servies ? » rendrait
    les deux illisibles."""
    from app.replay_harness import Outcome
    stats = summarize([Outcome("a", "NO_FILL"), Outcome("b", "WIN", pnl_usd=10.0, pnl_ticks=8),
                       Outcome("c", "LOSS", pnl_usd=-5.0, pnl_ticks=-4)])
    assert stats["setups"] == 3 and stats["settled"] == 2
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["no_fill_rate"] == pytest.approx(1 / 3)


def test_sans_aucun_trade_pris_le_taux_de_reussite_est_None_pas_zero():
    from app.replay_harness import Outcome
    stats = summarize([Outcome("a", "NO_FILL")])
    assert stats["win_rate"] is None and stats["pnl_usd"] is None


def test_carnet_INEXPLOITABLE_a_l_armement_donne_NO_FILL_sans_rien_inventer():
    h = ReplayHarness(tick_size=TICK)
    outcomes = h.run([_ev(MboAction.CLEAR, MboSide.NONE, 0, 0, ms=0)], _arm_once(_setup()))
    assert outcomes[0].status == "NO_FILL"


# ---------------------------------------------------------------------------
# Cycle complet — entrée servie puis sortie
# ---------------------------------------------------------------------------

def test_la_file_CONSOMMEE_puis_le_TP_servi_donne_un_GAIN():
    h = ReplayHarness(tick_size=TICK)
    events = _seed_book() + [
        # 45 lots s'échangent au bid : 40 de file + 5 pour nous → entrée servie.
        _ev(MboAction.TRADE, MboSide.BID, 5000.00, 45, order_id=0, ms=10),
        # Le prix monte et TRAVERSE notre TP à 5001.25 → sortie servie.
        _ev(MboAction.ADD, MboSide.ASK, 5001.50, 20, order_id=103, ms=20),
        _ev(MboAction.TRADE, MboSide.ASK, 5001.50, 5, order_id=0, ms=30),
    ]
    outcomes = h.run(events, _arm_once(_setup()))
    assert len(outcomes) == 1
    o = outcomes[0]
    assert o.status == "WIN" and o.exit_reason == "TP"
    assert o.entry_fill_price == 5000.00 and o.exit_price == 5001.25
    assert o.pnl_ticks == pytest.approx(5.0)
    assert o.pnl_usd == pytest.approx(5.0 * 1.25), "5 ticks × 1,25 $ (MES)"


def test_le_STOP_sort_au_MARCHE_et_paie_le_slippage():
    """Un stop n'est pas une limite : on sort en payant le carnet. Un slippage de sortie nul
    serait une hypothèse gratuite."""
    h = ReplayHarness(tick_size=TICK)
    events = _seed_book() + [
        _ev(MboAction.TRADE, MboSide.BID, 5000.00, 45, order_id=0, ms=10),   # entrée servie
        # Le carnet côté bid s'amincit : sortir au marché traversera plusieurs niveaux.
        _ev(MboAction.ADD, MboSide.BID, 4998.75, 1, order_id=104, ms=15),
        _ev(MboAction.ADD, MboSide.BID, 4998.50, 1, order_id=105, ms=16),
        _ev(MboAction.ADD, MboSide.BID, 4998.25, 50, order_id=106, ms=17),
        _ev(MboAction.TRADE, MboSide.BID, 4998.75, 1, order_id=0, ms=20),    # traverse le stop
    ]
    outcomes = h.run(events, _arm_once(_setup(qty=3.0)))
    o = outcomes[0]
    assert o.status == "LOSS" and o.exit_reason == "SL"
    assert o.exit_slip_ticks > 0, "traverser plusieurs niveaux coûte du slippage"
    assert o.pnl_usd < 0


def test_le_STOP_prime_sur_le_TP_au_meme_instant():
    """On ne s'accorde pas le meilleur des deux : sur un événement ambigu, c'est la perte qui
    compte. L'inverse serait un biais d'optimisme silencieux."""
    h = ReplayHarness(tick_size=TICK)
    events = _seed_book() + [
        _ev(MboAction.TRADE, MboSide.BID, 5000.00, 45, order_id=0, ms=10),
        _ev(MboAction.ADD, MboSide.BID, 4998.00, 50, order_id=104, ms=15),
        _ev(MboAction.TRADE, MboSide.BID, 4998.00, 1, order_id=0, ms=20),
    ]
    o = h.run(events, _arm_once(_setup()))[0]
    assert o.status == "LOSS" and o.exit_reason == "SL"


def test_une_position_encore_OUVERTE_en_fin_de_flux_est_distinguee_de_NO_FILL():
    h = ReplayHarness(tick_size=TICK)
    events = _seed_book() + [
        _ev(MboAction.TRADE, MboSide.BID, 5000.00, 45, order_id=0, ms=10),
    ]
    o = h.run(events, _arm_once(_setup()))[0]
    assert o.status == "OPEN_AT_END"
    assert o.entry_fill_price == 5000.00
    assert o.pnl_usd is None, "un trade non sorti n'a pas de PnL réalisé"


# ---------------------------------------------------------------------------
# Le SHORT, symétrique
# ---------------------------------------------------------------------------

def test_un_SHORT_gagne_quand_le_prix_BAISSE():
    h = ReplayHarness(tick_size=TICK)
    setup = _setup(side="SHORT", entry_price=5000.25, stop_loss=5001.25,
                   take_profit=5999.00 - 5000.00 and 4999.00)
    events = _seed_book() + [
        _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 35, order_id=0, ms=10),   # 30 file + 5
        _ev(MboAction.ADD, MboSide.BID, 4998.75, 20, order_id=104, ms=20),
        _ev(MboAction.TRADE, MboSide.BID, 4998.75, 5, order_id=0, ms=30),    # traverse le TP
    ]
    o = h.run(events, _arm_once(setup))[0]
    assert o.status == "WIN" and o.exit_reason == "TP"
    assert o.pnl_ticks == pytest.approx((5000.25 - 4999.00) / TICK)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def test_l_issue_REFERENCE_l_armement_et_ne_le_reecrit_pas():
    """Doctrine event-sourced (§2.5) : l'`OutcomeEvent` pointe vers le `setup_id` de L4."""
    h = ReplayHarness(tick_size=TICK)
    o = h.run(_seed_book(), _arm_once(_setup(setup_id="m-42")))[0]
    event = o.as_event()
    assert event["setup_id"] == "m-42"
    assert "entry_price" not in event, "l'issue ne recopie pas la décision, elle la référence"


def test_le_rejeu_est_REPRODUCTIBLE():
    def run():
        h = ReplayHarness(tick_size=TICK, latency_ms=35, latency_jitter_ms=15, rng_seed=7)
        events = _seed_book() + [
            _ev(MboAction.TRADE, MboSide.BID, 5000.00, 45, order_id=0, ms=100),
            _ev(MboAction.ADD, MboSide.ASK, 5001.50, 20, order_id=103, ms=200),
            _ev(MboAction.TRADE, MboSide.ASK, 5001.50, 5, order_id=0, ms=300),
        ]
        return [o.as_event() for o in h.run(events, _arm_once(_setup()))]

    assert run() == run()


def test_le_carnet_est_vu_AVANT_que_l_echange_courant_ne_le_consomme():
    """Un ordre placé sur l'événement d'échange doit hériter de la file d'AVANT, sinon il
    profiterait d'une liquidité déjà servie — un avantage qui n'a jamais existé."""
    h = ReplayHarness(tick_size=TICK)
    seen = {}

    def arm(book, event):
        if event.action != MboAction.TRADE or seen:
            return None
        seen["queue"] = book.level(MboSide.BID, 5000.00).size
        return _setup()

    events = _seed_book() + [_ev(MboAction.TRADE, MboSide.BID, 5000.00, 10, order_id=0, ms=10)]
    outcomes = h.run(events, arm)
    assert seen["queue"] == 30.0, "le carnet reflète l'échange courant (40 - 10)"
    assert outcomes[0].entry_queue_ahead == 30.0
    assert outcomes[0].entry_queue_remaining == 30.0, (
        "l'échange qui vient d'avoir lieu ne doit PAS aussi décrémenter notre file : il a déjà "
        "été compté par le carnet, et notre ordre n'était pas encore au marché")


def test_le_harnais_ne_passe_AUCUN_ordre_reel():
    import inspect

    from app import replay_harness
    src = inspect.getsource(replay_harness)
    for interdit in ("requests", "httpx", "socket", "broker", "submit_order", "aiohttp"):
        assert interdit not in src


def test_un_flux_VIDE_ne_produit_aucune_issue():
    assert ReplayHarness(tick_size=TICK).run([], lambda b, e: None) == []


# ---------------------------------------------------------------------------
# Bout-en-bout sur la fixture Parquet réelle
# ---------------------------------------------------------------------------

def test_bout_en_bout_sur_la_fixture_MBO_reelle():
    pytest.importorskip("pyarrow", reason="lecture Parquet — dépendance optionnelle")
    import pathlib

    from app.mbo.ingest import ingest_parquet

    path = pathlib.Path(__file__).resolve().parent / "fixtures" / "mbo_sample.parquet"
    events, stats = ingest_parquet(str(path))
    assert stats.events_emitted == 7

    h = ReplayHarness(tick_size=TICK)
    # On arme sur le premier ADD au bid : 40 lots au repos, dont l'ordre 101.
    def arm(book: MboBook, event):
        if event.action == MboAction.ADD and event.side == MboSide.BID and h._active is None:
            return _setup(entry_price=5000.00)
        return None

    outcomes = h.run(events, arm)
    assert len(outcomes) == 1
    o = outcomes[0]
    # Déroulé réel de la fixture : notre limite est à 5000.00 derrière 40 lots ; l'ordre 101 se
    # DÉPLACE ensuite à 4999.75 (modify), puis 15 lots s'y échangent. Un échange à 4999.75 passe
    # SOUS notre bid : il traverse notre limite, donc tout ce qui était devant a nécessairement
    # été servi et nous sommes remplis. Le flux s'arrête là, sans sortie.
    assert o.status == "OPEN_AT_END"
    assert o.entry_fill_price == 5000.00
    assert o.entry_queue_ahead == 40.0, "la file à l'armement reste l'instantané de l'armement"
    assert o.pnl_usd is None, "entré mais pas sorti : aucun PnL réalisé"

    stats = summarize(outcomes)
    assert stats["win_rate"] is None and stats["pnl_usd"] is None
    assert stats["by_status"]["OPEN_AT_END"] == 1
