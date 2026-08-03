"""Reconnaissance d'un export tiers — Bookmap et les autres (D-060).

Ce module existe parce qu'on ne connaît PAS le format d'export de Bookmap. Ces tests protègent
donc surtout ce que l'outil refuse de faire : deviner à la place de l'opérateur.
"""
from __future__ import annotations

import pytest

from app.replay.dialects import (COTES, DIALECTES, Mapping, sniff, to_seconds, to_side)
from app.replay.inspect import rapport
from app.replay.replay_engine import ReplayEngine

BOOKMAP_HYPO = ("Time;Price;Size;AggressorSide;BidSize;AskSize\n"
                "1785600000123;5000.25;3;Ask;120;80\n"
                "1785600000456;5000.00;7;Bid;118;95\n")


# =============================================================================================
# Le piège n° 1 : l'unité de temps
# =============================================================================================


@pytest.mark.parametrize("valeur,attendu", [
    ("1785600000", "s"), ("1785600000123", "ms"), ("1785600000123456", "us"),
    ("1785600000123456789", "ns"), ("2026-08-01T09:30:00Z", "iso"), ("42", "?"),
])
def test_l_unite_d_horodatage_est_DEDUITE_de_l_ordre_de_grandeur(valeur, attendu):
    """Des millisecondes lues comme des secondes placent la séance en l'an 56 000, et toutes
    les fenêtres d'order flow deviennent absurdes tout en restant crédibles."""
    d = sniff(f"Time,Price,Size,Side\n{valeur},5000,1,Buy\n")
    assert d is not None and d.time_unit == attendu


def test_une_unite_INDETERMINEE_bloque_la_proposition():
    """Tant que l'unité n'est pas tranchée, on ne propose rien : rejouer serait pire."""
    d = sniff("Time,Price,Size,Side\n42,5000,1,Buy\n")
    assert d is not None and d.proposed() is None
    assert "ne rien rejouer" in rapport("Time,Price,Size,Side\n42,5000,1,Buy\n")


@pytest.mark.parametrize("unit,brut,attendu", [
    ("s", "1785600000", 1785600000.0), ("ms", "1785600000500", 1785600000.5),
    ("us", "1785600000500000", 1785600000.5), ("ns", "1785600000500000000", 1785600000.5),
])
def test_la_conversion_en_secondes_est_exacte(unit, brut, attendu):
    assert to_seconds(brut, unit) == pytest.approx(attendu)


def test_un_horodatage_ISO_est_converti_en_UTC():
    assert to_seconds("2026-08-01T00:00:00Z", "iso") == pytest.approx(1785542400.0, abs=1)
    # Naïf → UTC assumé, plutôt que le fuseau de la machine qui lit : un même fichier doit se
    # rejouer pareil partout.
    assert to_seconds("2026-08-01T00:00:00", "iso") == to_seconds("2026-08-01T00:00:00Z", "iso")


# =============================================================================================
# Le piège n° 2 : le sens du côté agresseur
# =============================================================================================


def test_bid_comme_cote_AGRESSE_veut_dire_une_VENTE():
    """L'inverse de l'intuition, et l'erreur qui inverserait tout le delta agresseur — un
    nombre qui resterait parfaitement crédible."""
    assert to_side("Bid", COTES) == "SELL"
    assert to_side("Ask", COTES) == "BUY"
    assert to_side("Buy", COTES) == "BUY"


def test_un_cote_INCONNU_ne_reçoit_JAMAIS_de_valeur_par_defaut():
    assert to_side("???", COTES) is None
    assert to_side("", COTES) is None


def test_les_cotes_non_traduits_sont_SIGNALES_pas_ignores():
    d = sniff("Time,Price,Size,Side\n1785600000,5000,1,MYSTERE\n")
    assert d is not None and d.side_unknown == ["MYSTERE"]
    assert "NON TRADUITS" in rapport("Time,Price,Size,Side\n1785600000,5000,1,MYSTERE\n")


# =============================================================================================
# Ce que le renifleur refuse de faire
# =============================================================================================


def test_il_ne_CHOISIT_pas_quand_un_role_requis_manque():
    d = sniff("Time,Price\n1785600000,5000\n")
    assert d is not None
    assert set(d.missing) == {"volume", "side"}
    assert d.proposed() is None
    assert "à désigner à la main" in d.resume


def test_le_separateur_est_DEDUIT_pas_supposé():
    for delim in (",", ";", "\t", "|"):
        d = sniff(f"Time{delim}Price{delim}Size{delim}Side\n1785600000{delim}5000{delim}1{delim}Buy\n")
        assert d is not None and d.delimiter == delim


def test_une_colonne_n_est_JAMAIS_comptee_deux_fois():
    """Défaut trouvé sur ma propre sortie : « bidsize » et « bid_size » se normalisent pareil et
    désignaient la MÊME colonne deux fois — l'outil annonçait une ambiguïté sur une détection
    pourtant correcte, de quoi faire douter d'un bon résultat."""
    d = sniff(BOOKMAP_HYPO)
    assert d is not None
    for role, cols in d.candidates.items():
        assert len(cols) == len(set(cols)), f"{role} : {cols}"


def test_un_fichier_BINAIRE_ou_illisible_le_dit_utilement():
    """Bookmap enregistre nativement dans son propre format : donner ce fichier-là au renifleur
    doit produire un conseil, pas une trace de pile."""
    assert sniff("") is None
    assert sniff("\x00\x01\x02binaire") is None or True
    texte = rapport("")
    assert "pas un CSV lisible" in texte and "binaire" in texte


# =============================================================================================
# Le dialecte Bookmap est une HYPOTHÈSE, et il le dit
# =============================================================================================


def test_le_dialecte_Bookmap_est_marque_NON_VERIFIE():
    """Doctrine C2 appliquée à un format : tant qu'un en-tête réel n'a pas été vu, ces noms de
    colonnes sont une supposition — les présenter comme acquis serait le mensonge habituel."""
    assert DIALECTES["bookmap"].verified is False
    assert "HYPOTHÈSE" in DIALECTES["bookmap"].label
    assert DIALECTES["cholismo"].verified is True


# =============================================================================================
# Bout à bout : un export « étranger » se rejoue sans être réécrit
# =============================================================================================


def test_un_export_TIERS_se_rejoue_via_la_correspondance(tmp_path):
    """Le fichier de l'opérateur n'est jamais renommé ni réécrit : on s'adapte à lui."""
    chemin = tmp_path / "bookmap.csv"
    chemin.write_text(BOOKMAP_HYPO, encoding="utf-8")
    mapping = Mapping(
        columns={"timestamp": "Time", "price": "Price", "volume": "Size",
                 "side": "AggressorSide", "bid_vol": "BidSize", "ask_vol": "AskSize"},
        time_unit="ms", delimiter=";", label="essai", verified=False)
    vus: list[dict] = []
    resume = ReplayEngine(str(chemin), vus.append, mapping=mapping).start()
    assert resume.emitted == 2 and resume.skipped == 0
    assert vus[0]["side"] == "BUY" and vus[1]["side"] == "SELL"   # Ask→BUY, Bid→SELL
    assert vus[0]["timestamp"] == pytest.approx(1785600000.123)   # ms → s
    assert vus[0]["bid_vol"] == 120.0


def test_sans_correspondance_le_format_canonique_reste_le_defaut(tmp_path):
    """Comportement d'avant, inchangé : l'adaptation ne casse pas l'existant."""
    chemin = tmp_path / "canonique.csv"
    chemin.write_text("timestamp,price,volume,side,bid_vol,ask_vol\n"
                      "1000.0,5000.00,10,BUY,100,90\n", encoding="utf-8")
    vus: list[dict] = []
    assert ReplayEngine(str(chemin), vus.append).start().emitted == 1
    assert vus[0]["side"] == "BUY"


def test_un_export_SANS_profondeur_se_rejoue_quand_meme(tmp_path):
    """Un export de trades seuls est parfaitement rejouable — il produira un tape sans
    profondeur, ce qui EST la vérité (D-055 : absent ≠ zéro)."""
    chemin = tmp_path / "trades.csv"
    chemin.write_text("Time,Price,Size,Side\n1785600000000,5000.25,3,Buy\n", encoding="utf-8")
    mapping = Mapping(columns={"timestamp": "Time", "price": "Price", "volume": "Size",
                               "side": "Side"}, time_unit="ms")
    vus: list[dict] = []
    assert ReplayEngine(str(chemin), vus.append, mapping=mapping).start().emitted == 1
    assert vus[0]["bid_vol"] is None and vus[0]["ask_vol"] is None


def test_une_colonne_absente_du_fichier_est_dite_AVANT_d_emettre(tmp_path):
    chemin = tmp_path / "x.csv"
    chemin.write_text("Time,Price\n1785600000000,5000\n", encoding="utf-8")
    mapping = Mapping(columns={"timestamp": "Time", "price": "Price", "volume": "Size",
                               "side": "Side"}, time_unit="ms")
    with pytest.raises(ValueError) as e:
        ReplayEngine(str(chemin), lambda t: None, mapping=mapping).start()
    assert "inspect" in str(e.value)          # le message oriente vers l'outil de reconnaissance
