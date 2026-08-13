"""Feature — L4 `gates.eval` : O1-O5 à l'armement (D-080, phase P3 item 3).

Point d'appel unique et **événementiel**, déclenché par l'émission d'un manifeste. Une
évaluation périodique réévaluerait le PASSÉ (piège de cadence D-052) — c'est pourquoi
`gates.eval` est `EVENT_DRIVEN` depuis D-073.

**Ce que ces tests verrouillent avant tout : la frontière entre ce qui est mesurable à
l'armement et ce qui ne l'est pas.** Le slippage d'entrée se lit dans le carnet ; le PnL, non —
le trade n'a pas eu lieu. Fabriquer un PnL à l'armement reviendrait à supposer le résultat qu'on
cherche à mesurer. L'entrée porte donc `pnl_source: "PENDING"`, jamais un zéro.
"""
import json

from app.execution_sim import Book, BookLevel
from app.gates_journal import evaluate_at_arming
from app.options_context import ContextHealth, OptionsContextSnapshot

TICK = 0.25


def _manifest(**over):
    data = {
        "id": "m-1", "instrument": "MES", "direction": "LONG",
        "entry": {"price": 5000.00, "entryType": "LIMIT"},
        "risk": {"stopLoss": 4997.50, "takeProfit": 5001.25, "positionSize": 2},
    }
    data.update(over)
    return data


def _snapshot(health=ContextHealth.OK):
    raw = {
        "status": "OK",
        "gexLocalByStrike": {"5000": 200.0},
        "gammaZeroEs": 5010.0, "putWallEs": 4990.0, "callWallEs": 5020.0,
        "netDriftCrossover": {"direction": "up", "ts": 1_000, "sourceConfirmed": False},
        "conversionFactorUsed": 1.003, "computedAt": 1_000, "sourceVendor": "mock",
    }
    return OptionsContextSnapshot(health=health, raw=raw, age_s=1.0)


def _book(queue=40.0):
    return Book(bids=(BookLevel(5000.00, queue), BookLevel(4999.75, 20.0)),
                asks=(BookLevel(5000.25, 30.0),))


def _bars(n=40):
    return [{"timestamp": 1_000_000 + i * 60_000, "close": 6000.0 + (i % 5)} for i in range(n)]


# ---------------------------------------------------------------------------
# L'entrée de journal
# ---------------------------------------------------------------------------

def test_l_armement_produit_une_entree_portant_les_cinq_balises():
    entry = evaluate_at_arming(_manifest(), options_snapshot=_snapshot(), es_bars=_bars(),
                               book=_book(), now_ms=1_000, tick_size=TICK)
    assert entry["setup_id"] == "m-1" and entry["instrument"] == "MES"
    for gate in ("o1", "o2", "o3", "o4", "o5"):
        assert f"{gate}_status" in entry
    assert entry["o1_status"] == "PASS"                  # GEX +200 au niveau visé
    assert entry["context_health"] == "OK"


def test_le_slippage_d_ENTREE_est_mesure_depuis_le_carnet():
    entry = evaluate_at_arming(_manifest(), options_snapshot=_snapshot(), es_bars=_bars(),
                               book=_book(queue=40.0), now_ms=1_000, tick_size=TICK)
    assert entry["entry_queue_ahead"] == 40.0, "les 40 lots au repos sont devant nous"
    assert entry["entry_feasible"] is True


def test_le_PnL_n_est_PAS_fabrique_a_l_armement():
    """Le trade n'a pas eu lieu. Un `0` se lirait comme un résultat nul ; `PENDING` dit la
    vérité — l'outcome viendra comme event ultérieur référençant ce setup (CLAUDE §2.5)."""
    entry = evaluate_at_arming(_manifest(), options_snapshot=_snapshot(), es_bars=_bars(),
                               book=_book(), now_ms=1_000, tick_size=TICK)
    assert entry["pnl_source"] == "PENDING"
    assert entry["realized_pnl"] is None
    assert entry["realized_slip_ticks"] is None


def test_sans_CARNET_la_file_n_est_pas_supposee_NULLE():
    """Une file supposée nulle ferait passer notre ordre pour premier servi — le biais même que
    P3 supprime. On rapporte l'absence."""
    entry = evaluate_at_arming(_manifest(), options_snapshot=_snapshot(), es_bars=_bars(),
                               book=None, now_ms=1_000, tick_size=TICK)
    assert entry["entry_queue_ahead"] is None
    assert entry["entry_feasible"] is None
    assert entry["entry_reject_reason"] == "NO_BOOK"


def test_l_entree_est_SERIALISABLE_pour_le_journal_et_le_canal():
    entry = evaluate_at_arming(_manifest(), options_snapshot=_snapshot(), es_bars=_bars(),
                               book=_book(), now_ms=1_000, tick_size=TICK)
    json.loads(json.dumps(entry))


# ---------------------------------------------------------------------------
# Mode G2 — consultatif, point final
# ---------------------------------------------------------------------------

def test_un_contexte_options_MORT_n_empeche_pas_la_journalisation():
    """Le Pont Options est consultatif : un fournisseur muet annote le setup, il ne le supprime
    pas du journal — sinon la calibration perdrait précisément les setups pris sans contexte."""
    absent = OptionsContextSnapshot(health=ContextHealth.UNAVAILABLE, raw=None, age_s=None)
    entry = evaluate_at_arming(_manifest(), options_snapshot=absent, es_bars=_bars(),
                               book=_book(), now_ms=1_000, tick_size=TICK)
    assert entry is not None
    assert entry["o1_status"] == "O1_DATA_UNAVAILABLE"
    assert entry["context_health"] == "UNAVAILABLE"
    assert entry["o5_status"] in ("PASS", "FLAG_HIDDEN_TAIL"), "O5 est autonome"


def test_l_entree_n_a_NI_blocked_NI_allowed():
    entry = evaluate_at_arming(_manifest(), options_snapshot=_snapshot(), es_bars=_bars(),
                               book=_book(), now_ms=1_000, tick_size=TICK)
    assert "blocked" not in entry and "allowed" not in entry


def test_un_manifeste_ILLISIBLE_rend_None_sans_lever():
    for bad in (None, 42, "manifeste", {}, {"entry": {}}, {"risk": {"takeProfit": 1}}):
        assert evaluate_at_arming(bad, options_snapshot=_snapshot(), es_bars=_bars(),
                                  book=_book(), now_ms=1_000) is None


def test_un_manifeste_PYDANTIC_est_accepte_comme_son_dump():
    class _Fake:
        def model_dump(self):
            return _manifest()

    assert evaluate_at_arming(_Fake(), options_snapshot=_snapshot(), es_bars=_bars(),
                              book=_book(), now_ms=1_000)["setup_id"] == "m-1"


def test_le_SHORT_lit_le_put_wall_et_non_le_call_wall():
    entry = evaluate_at_arming(_manifest(direction="SHORT",
                                         risk={"stopLoss": 5002.5, "takeProfit": 4998.75,
                                               "positionSize": 2}),
                               options_snapshot=_snapshot(), es_bars=_bars(),
                               book=_book(), now_ms=1_000, tick_size=TICK)
    assert entry["side"] == "SHORT"
    assert entry["o3_status"] in ("PASS", "FLAG_OBSTACLE", "O3_WALLS_UNKNOWN")


# ---------------------------------------------------------------------------
# La boucle L4 elle-même
# ---------------------------------------------------------------------------

def test_L4_est_cablee_et_journalise_a_l_armement():
    from app.loops.wiring import build_gates_tick
    import asyncio

    published = []

    class _B:
        def publish(self, channel, event, payload, replay=True):
            published.append((channel, event, payload))

    written = []
    tick = build_gates_tick(lambda: _snapshot(), lambda: _bars(), lambda: _book(), _B(),
                            append=written.append, clock=lambda: 1.0)
    asyncio.run(tick(_manifest()))

    assert len(written) == 1 and written[0]["setup_id"] == "m-1"
    assert published and published[0][0] == "options"
    assert published[0][1] == "options_gates"


def test_L4_n_ecrit_RIEN_sur_un_manifeste_illisible():
    from app.loops.wiring import build_gates_tick
    import asyncio

    written = []

    class _B:
        def publish(self, *a, **k): pass

    tick = build_gates_tick(lambda: _snapshot(), lambda: _bars(), lambda: _book(), _B(),
                            append=written.append, clock=lambda: 1.0)
    asyncio.run(tick({"entry": {}}))
    assert written == []


def test_la_spec_L4_reste_EVENEMENTIELLE():
    """Une L4 périodique réévaluerait le passé (D-052). La spec doit l'interdire par
    construction, pas par convention."""
    from app.loops.contract import Cadence
    from app.loops.registry import GATES_EVAL
    assert GATES_EVAL.cadence is Cadence.EVENT_DRIVEN
    assert GATES_EVAL.period_s is None and GATES_EVAL.heartbeat_stale_s is None
