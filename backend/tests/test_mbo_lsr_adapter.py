"""Feature — détecteur LSR branché sur le flux MBO (D-083, phase P2).

Le pont entre le carnet reconstruit (D-079) et la chaîne de décision existante. Ce que ces tests
protègent, dans l'ordre d'importance :

1. **Un seul moteur de décision.** L'adaptateur PROJETTE l'état MBO dans un `ContextSchema` et
   réutilise `build_sweep_inputs` / `evaluate_lsr` tels quels. Réimplémenter la détection pour le
   MBO créerait un second moteur, à faire diverger du premier.
2. **Rien n'est fabriqué pour combler le silence du fichier.** Un export MBO ne porte ni VIX, ni
   calendrier, ni ATR de session. Ces entrées restent absentes, les gates refusent, et le
   diagnostic dit lesquelles manquent.
3. **Le côté d'un print est l'AGRESSEUR.** Le carnet résout le passif ; le tape attend
   l'agresseur. L'inversion est explicite — l'omettre retournerait B2 et B3 en silence.
"""
from app.mbo.book import MboBook
from app.mbo.events import MboAction, MboEvent, MboSide
from app.mbo.lsr_adapter import MISSING_FROM_MBO, MboLsrDetector

TICK = 0.25
BASE_NS = 1_700_000_000_000_000_000


def _ev(action, side, price, size, order_id=0, ms=0):
    return MboEvent(ts_event=BASE_NS + ms * 1_000_000, ts_recv=BASE_NS + ms * 1_000_000,
                    action=action, side=side, price=price, size=size,
                    order_id=order_id, sequence=ms, symbol="MESZ4")


def _seeded_book():
    book = MboBook(tick_size=TICK)
    for i in range(5):
        book.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00 - i * TICK, 40, order_id=100 + i))
        book.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25 + i * TICK, 40, order_id=200 + i))
    return book


# ---------------------------------------------------------------------------
# La projection
# ---------------------------------------------------------------------------

def test_le_carnet_MBO_devient_un_order_book_FRESH_du_schema():
    detector = MboLsrDetector(tick_size=TICK)
    schema = detector.build_schema(_seeded_book(), now=1_000.0)
    field = schema.s1_state.order_book
    assert field.freshness.value == "FRESH" and field.source == "mbo_replay"
    assert field.value["bids"][0] == [5000.00, 40.0]
    assert field.value["asks"][0] == [5000.25, 40.0]


def test_un_carnet_UNILATERAL_ne_produit_aucun_order_book():
    """Un carnet sans les deux côtés n'a pas de spread : le publier comme FRESH ferait calculer
    un spread sur une moitié de marché."""
    book = MboBook(tick_size=TICK)
    book.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=1))
    schema = MboLsrDetector(tick_size=TICK).build_schema(book, now=1_000.0)
    assert schema.s1_state.order_book.freshness.value == "ABSENT"


def test_le_reste_du_schema_demeure_ABSENT_rien_n_est_fabrique():
    """Le silence du fichier est conservé : c'est lui qui fait refuser les gates dépendant de
    données que le MBO ne porte pas."""
    schema = MboLsrDetector(tick_size=TICK).build_schema(_seeded_book(), now=1_000.0)
    assert schema.s1_state.structure.vpoc.freshness.value == "ABSENT"
    assert schema.s1_state.chop.freshness.value == "ABSENT"
    assert schema.s2_state.cascade.vix.freshness.value == "ABSENT"


# ---------------------------------------------------------------------------
# L'inversion passif → agresseur
# ---------------------------------------------------------------------------

def test_un_trade_sur_l_ASK_produit_un_print_ACHETEUR():
    """Le carnet dit « l'ask a été consommé » ; le tape doit dire « un acheteur a agressé »."""
    detector = MboLsrDetector(tick_size=TICK)
    book = _seeded_book()
    detector(book, _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 10, order_id=0, ms=10))
    schema = detector.build_schema(book, now=1_000.0)
    assert schema.s1_state.tape.value[0]["side"] == "BUY"


def test_un_trade_sur_le_BID_produit_un_print_VENDEUR():
    detector = MboLsrDetector(tick_size=TICK)
    book = _seeded_book()
    detector(book, _ev(MboAction.TRADE, MboSide.BID, 5000.00, 10, order_id=0, ms=10))
    schema = detector.build_schema(book, now=1_000.0)
    assert schema.s1_state.tape.value[0]["side"] == "SELL"


def test_un_trade_au_cote_INRESOLVABLE_ne_produit_AUCUN_print():
    """Plutôt qu'un print au côté deviné, qui fausserait le delta signé sans qu'on le voie."""
    detector = MboLsrDetector(tick_size=TICK)
    book = MboBook(tick_size=TICK)
    book.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=1))
    book.apply(_ev(MboAction.ADD, MboSide.ASK, 5001.00, 40, order_id=2))
    detector(book, _ev(MboAction.TRADE, MboSide.ASK, 5000.50, 10, order_id=0, ms=10))
    assert detector.diagnostics()["prints_accumulated"] == 0


def test_les_prints_sont_ordonnes_du_PLUS_RECENT_au_plus_ancien():
    """Convention du tape (D-026). L'inverser ferait lire les rafales à l'envers."""
    detector = MboLsrDetector(tick_size=TICK)
    book = _seeded_book()
    for i in range(3):
        detector(book, _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 5, order_id=0, ms=10 + i))
    prints = detector.build_schema(book, now=1_000.0).s1_state.tape.value
    assert [p["seq"] for p in prints] == [3, 2, 1]


def test_le_tampon_de_prints_est_BORNE():
    detector = MboLsrDetector(tick_size=TICK, max_prints=50)
    book = _seeded_book()
    for i in range(200):
        detector(book, _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 1, order_id=0, ms=10 + i))
    assert detector.diagnostics()["prints_accumulated"] == 50


# ---------------------------------------------------------------------------
# Un seul moteur de décision
# ---------------------------------------------------------------------------

def test_l_adaptateur_REUTILISE_la_chaine_existante_sans_la_dupliquer():
    """Aucune règle de décision ne doit être réécrite ici : un second moteur divergerait du
    premier, et c'est précisément ce que D-052 a refusé ailleurs."""
    import inspect

    from app.mbo import lsr_adapter
    src = inspect.getsource(lsr_adapter)
    assert "evaluate_lsr" in src and "build_sweep_inputs" in src
    # Aucun seuil de décision recopié : les chiffres appartiennent au moteur et à sa config.
    for interdit in ("CHOP", "0.618", "61.8", "aggressor_ratio >", "if svs"):
        assert interdit not in src


def test_le_detecteur_ne_leve_jamais_sur_un_flux_quelconque():
    detector = MboLsrDetector(tick_size=TICK)
    book = MboBook(tick_size=TICK)
    for i in range(60):
        event = _ev(MboAction.ADD if i % 3 else MboAction.TRADE,
                    MboSide.BID if i % 2 else MboSide.ASK,
                    5000.0 + (i % 7) * TICK, 10, order_id=i, ms=i)
        book.apply(event)
        assert detector(book, event) is None or True


def test_aucun_setup_n_est_arme_sans_les_entrees_que_le_MBO_ne_porte_pas():
    """Le refus est le comportement CORRECT : armer quand même produirait des setups dont les
    filtres n'ont jamais tourné, et la matrice mesurerait l'absence de données."""
    detector = MboLsrDetector(tick_size=TICK)
    book = _seeded_book()
    armed = []
    for i in range(100):
        event = _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 20, order_id=0, ms=10 + i)
        book.apply(event)
        setup = detector(book, event)
        if setup is not None:
            armed.append(setup)
    assert armed == []
    assert detector.diagnostics()["armed"] == 0


# ---------------------------------------------------------------------------
# Le diagnostic — pourquoi la matrice est vide
# ---------------------------------------------------------------------------

def test_le_diagnostic_NOMME_les_entrees_manquantes():
    """Sans ce rapport, une matrice vide se lirait « la stratégie ne se déclenche jamais » alors
    que la cause peut être « le fichier ne porte pas ce que les filtres exigent »."""
    diag = MboLsrDetector(tick_size=TICK).diagnostics()
    assert set(diag["inputs_absent_from_mbo"]) == set(MISSING_FROM_MBO)
    # `svs_score` a été RETIRÉ de cette liste (D-085) : `build_lsr_inputs` ne le lit pas — c'est
    # une entrée de la stratégie SVS de Sony. L'annoncer comme manquant envoyait l'opérateur
    # chercher une donnée dont le moteur LSR ne veut pas.
    assert diag["inputs_absent_from_mbo"] == []
    # Sans contexte fourni, rien n'est joint — et le diagnostic le dit plutôt que de laisser
    # croire que VIX et calendrier sont disponibles.
    assert diag["inputs_joined_from_context"] == []
    assert diag["context"] is None
    assert "atr_session" in diag["inputs_derived_from_flow"]


def test_l_etat_news_par_defaut_n_est_PAS_SAFE():
    """La porte F0 est fail-closed sur l'inconnu. Passer `SAFE` par défaut lèverait une
    protection faute de données (leçon D-050)."""
    assert MboLsrDetector(tick_size=TICK).news_state is None


def test_le_diagnostic_compte_les_refus_APRES_sweep():
    detector = MboLsrDetector(tick_size=TICK)
    diag = detector.diagnostics()
    assert diag["armed"] == 0 and diag["refused_after_sweep"] == 0


# ---------------------------------------------------------------------------
# Branchement sur le harnais
# ---------------------------------------------------------------------------

def test_le_detecteur_se_branche_DIRECTEMENT_sur_le_harnais():
    """C'est l'interface qui compte : `MboLsrDetector` est appelable comme le `arm` attendu."""
    from app.replay_harness import ReplayHarness

    events = [_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101, ms=0),
              _ev(MboAction.ADD, MboSide.ASK, 5000.25, 40, order_id=102, ms=1),
              _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 10, order_id=0, ms=10)]
    outcomes = ReplayHarness(tick_size=TICK).run(events, MboLsrDetector(tick_size=TICK))
    assert outcomes == [], "aucun armement sans les entrées manquantes — et aucune erreur"


def test_la_passe_de_calibration_accepte_le_detecteur():
    """Bout-en-bout : `run_calibration(..., arm=MboLsrDetector())` sur la fixture réelle."""
    import os
    import pathlib
    import tempfile

    import pytest
    pytest.importorskip("pyarrow", reason="lecture Parquet — dépendance optionnelle")

    from app.calibration import run_calibration
    from app.event_store import EventStore
    from app.setup_journal import SetupJournal

    path = pathlib.Path(__file__).resolve().parent / "fixtures" / "mbo_sample.parquet"
    journal = SetupJournal(EventStore(os.path.join(tempfile.mkdtemp(), "cal.db")))
    report = run_calibration(str(path), arm=MboLsrDetector(tick_size=TICK), journal=journal)

    assert report["ingest"]["events_emitted"] == 7
    assert report["replay"]["setups"] == 0
    assert report["replay"]["win_rate"] is None, "aucun trade pris → None, jamais 0 %"
    assert report["calibration"]["result_visible"] is False


def test_le_VPOC_se_DERIVE_du_flux_rejoue():
    """Régression (D-085). `build_lsr_inputs` LIT `vpoc` ; l'adaptateur ne le remplissait pas,
    et le moteur refusait donc pour une donnée pourtant dérivable des transactions rejouées."""
    detector = MboLsrDetector(tick_size=TICK)
    book = _seeded_book()
    # Le gros du volume s'échange à 5000.25 : c'est lui qui doit ressortir en POC.
    for i in range(5):
        detector(book, _ev(MboAction.TRADE, MboSide.ASK, 5000.25, 100, order_id=0, ms=10 + i))
    detector(book, _ev(MboAction.TRADE, MboSide.BID, 5000.00, 1, order_id=0, ms=50))
    schema = detector.build_schema(book, now=1_000.0)
    assert schema.s1_state.structure.vpoc.freshness.value == "FRESH"
    assert schema.s1_state.structure.vpoc.value == 5000.25


def test_le_VPOC_reste_ABSENT_tant_qu_aucun_volume_n_a_ete_echange():
    detector = MboLsrDetector(tick_size=TICK)
    schema = detector.build_schema(_seeded_book(), now=1_000.0)
    assert schema.s1_state.structure.vpoc.freshness.value == "ABSENT"


def test_la_grille_de_volume_est_BORNEE():
    """Sans borne, une séance à prix errant ferait croître la table sans fin."""
    from app import config
    detector = MboLsrDetector(tick_size=TICK)
    book = _seeded_book()
    for i in range(config.VP_MAX_LEVELS + 200):
        detector(book, _ev(MboAction.TRADE, MboSide.ASK, 5000.25 + i * TICK, 1,
                           order_id=0, ms=10 + i))
    assert detector.diagnostics()["vp_levels"] <= config.VP_MAX_LEVELS


def test_le_VPOC_utilise_le_MEME_calcul_que_le_moteur_live():
    """En réécrire un ici ferait deux POC pour un seul marché."""
    import inspect

    from app.mbo import lsr_adapter
    assert "build_volume_profile" in inspect.getsource(lsr_adapter)
