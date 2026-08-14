"""Comportement de la liquidité par niveau — icebergs et churn (D-106).

Ce qui est vérifié : que le module n'affirme JAMAIS plus que ce que le carnet montre.
"""
from __future__ import annotations

from app.mbo.book import MboBook
from app.mbo.events import MboAction, MboEvent, MboSide
from app.mbo.liquidity_behaviour import (
    CHURN_CANCEL_RATIO,
    ICEBERG_TRADED_MULTIPLE,
    MIN_ADDED_VOLUME,
    analyse_book,
    analyse_level,
    summarise,
)


def _ev(action, side, price, size, oid, seq):
    return MboEvent(ts_event=seq * 1000, ts_recv=seq * 1000, action=action, side=side,
                    price=price, size=size, order_id=oid, sequence=seq, symbol="MES")


def _book_iceberg() -> MboBook:
    """Un niveau qui rejoue plusieurs fois sa taille visible : 10 affichés, 60 échangés."""
    b = MboBook(tick_size=0.25)
    seq = 0
    for k in range(6):
        seq += 1
        b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.0, 10.0, 100 + k, seq))
        seq += 1
        b.apply(_ev(MboAction.TRADE, MboSide.ASK, 5000.0, 10.0, 100 + k, seq))
    return b


def _book_churn() -> MboBook:
    """Beaucoup d'ajouts, tout annulé, RIEN d'exécuté."""
    b = MboBook(tick_size=0.25)
    seq = 0
    for k in range(6):
        seq += 1
        b.apply(_ev(MboAction.ADD, MboSide.ASK, 5001.0, 20.0, 200 + k, seq))
        seq += 1
        b.apply(_ev(MboAction.CANCEL, MboSide.ASK, 5001.0, 20.0, 200 + k, seq))
    return b


# ---------------------------------------------------------------- vocabulaire

def test_le_module_ne_dit_JAMAIS_spoofing():
    """Le spoofing est une INTENTION, et une intention ne s'observe pas dans un carnet.
    L'étiqueter serait présenter une accusation comme une mesure."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "mbo" / "liquidity_behaviour.py").read_text(encoding="utf-8")
    # Le mot n'apparaît que dans l'explication du refus, jamais comme nom de champ ni verdict.
    assert '"spoof' not in src.lower() and "'spoof" not in src.lower()
    assert "spoofing est une intention" in src.lower()


# ---------------------------------------------------------------- iceberg

def test_un_niveau_qui_REJOUE_sa_taille_visible_est_signale():
    rapport = analyse_book(_book_iceberg())
    niveaux = [lv for lv in rapport["bids"] if lv["price"] == 5000.0]
    assert niveaux, "le niveau doit être analysé"
    lv = niveaux[0]
    assert lv["traded"] == 60.0 and lv["peak_size"] == 10.0
    assert lv["refill_multiple"] == 6.0 >= ICEBERG_TRADED_MULTIPLE
    assert lv["iceberg"] is True


def test_le_PIC_sert_de_reference_et_non_la_taille_courante():
    """Après consommation, la taille courante vaut souvent 0 : un rapport sur elle serait infini
    ou indéfini. Le pic est la seule référence stable."""
    lv = analyse_book(_book_iceberg())["bids"][0]
    assert lv["displayed"] == 0.0 and lv["peak_size"] > 0.0
    assert lv["refill_multiple"] is not None


# ---------------------------------------------------------------- churn

def test_du_volume_ANNULE_SANS_EXECUTION_est_signale_comme_churn():
    lv = analyse_book(_book_churn())["asks"][0]
    assert lv["traded"] == 0.0
    assert lv["cancel_ratio"] >= CHURN_CANCEL_RATIO
    assert lv["churn"] is True
    assert lv["iceberg"] is False, "annulé n'est pas masqué"


def test_un_niveau_CONSOMME_n_est_pas_du_churn():
    """La distinction qui fait tout l'intérêt : un mur mangé et un mur retiré se ressemblent à
    l'écran, et ne disent pas la même chose d'un sweep."""
    lv = analyse_book(_book_iceberg())["bids"][0]
    assert lv["churn"] is False


# ---------------------------------------------------------------- fail-closed

def test_sous_le_plancher_d_activite_on_ne_conclut_RIEN():
    """Deux ordres posés puis retirés donnent 100 % d'annulation — qui ne décrit que deux ordres."""
    b = MboBook(tick_size=0.25)
    b.apply(_ev(MboAction.ADD, MboSide.BID, 4999.0, 1.0, 1, 1))
    b.apply(_ev(MboAction.CANCEL, MboSide.BID, 4999.0, 1.0, 1, 2))
    lv = analyse_book(b)["bids"][0]
    assert lv["added"] < MIN_ADDED_VOLUME
    assert lv["iceberg"] is None and lv["churn"] is None, "None, pas False"


def test_None_et_False_ne_se_confondent_pas():
    """`False` se lirait « vérifié, pas d'iceberg » ; `None` dit « non mesurable » (§3)."""
    b = MboBook(tick_size=0.25)
    b.apply(_ev(MboAction.ADD, MboSide.BID, 4999.0, 2.0, 1, 1))
    faible = analyse_book(b)["bids"][0]
    fort = analyse_book(_book_churn())["asks"][0]
    assert faible["iceberg"] is None
    assert fort["iceberg"] is False
    assert faible["iceberg"] is not fort["iceberg"]


def test_un_rapport_sur_RIEN_n_est_pas_zero():
    from app.mbo.liquidity_behaviour import _ratio
    assert _ratio(5.0, 0.0) is None
    assert _ratio(0.0, 5.0) == 0.0


def test_un_carnet_INEXPLOITABLE_ne_leve_pas():
    """Le mode consultatif ne bloque rien : une exception ici remonterait dans l'armement."""
    for mauvais in (None, object(), 42, "carnet"):
        rapport = analyse_book(mauvais)
        assert rapport["bids"] == [] and rapport["asks"] == []


def test_analyse_level_sur_un_objet_INCOMPLET_rend_None():
    assert analyse_level(object(), "B") is None


# ---------------------------------------------------------------- traçabilité

def test_le_rapport_porte_les_SEUILS_qui_l_ont_produit():
    """Une conclusion doit rester rattachable aux nombres qui l'ont produite."""
    t = analyse_book(_book_iceberg())["thresholds"]
    assert t["iceberg_traded_multiple"] == ICEBERG_TRADED_MULTIPLE
    assert t["calibrated"] is False, "aucun seuil n'est calibré"


def test_le_resume_est_LISIBLE_et_rappelle_l_absence_de_calibration():
    txt = summarise(analyse_book(_book_iceberg()))
    assert "réinjection masquée" in txt and "NON calibrés" in txt
    vide = summarise(analyse_book(MboBook(tick_size=0.25)))
    assert "aucun niveau" in vide


# ---------------------------------------------------------------- câblage (D-112)

def test_le_harnais_FIGE_le_comportement_a_l_armement():
    """Un module non appelé vaut zéro (5ᵉ piège de HANDOFF.md). Et le figer à l'armement est la
    même doctrine que le vecteur de features : une minute plus tard, les compteurs ont bougé."""
    from app.replay_harness import ReplayHarness, Setup

    h = ReplayHarness(tick_size=0.25)
    # Un niveau à réinjection masquée avant l'armement.
    seq = 0
    for k in range(6):
        seq += 1
        h.book.apply(_ev(MboAction.ADD, MboSide.BID, 5000.0, 10.0, 300 + k, seq))
        seq += 1
        h.book.apply(_ev(MboAction.TRADE, MboSide.ASK, 5000.0, 10.0, 300 + k, seq))

    h._arm(Setup(setup_id="s1", side="LONG", entry_price=5000.0, stop_loss=4999.0,
                 take_profit=5001.25), ts_ms=1000.0)

    rapport = h.behaviours.get("s1")
    assert rapport is not None, "le comportement doit être capturé à l'armement"
    niveaux = [lv for lv in rapport["bids"] if lv["price"] == 5000.0]
    assert niveaux and niveaux[0]["iceberg"] is True
    assert rapport["thresholds"]["calibrated"] is False
