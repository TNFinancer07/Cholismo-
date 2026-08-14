"""Codec et projection Tradovate (D-100).

Ce qui est testé est ce qui est testable hors ligne : le codec et les projections, purs et
déterministes. Le transport n'est pas couvert — il n'existe pas, faute d'accès au service.
"""
from __future__ import annotations

import pathlib

from app.datasource.tradovate import (
    FRAME_ARRAY,
    FRAME_HEARTBEAT,
    FRAME_OPEN,
    book_from_dom,
    decode_frame,
    encode_request,
    fills_from_sync,
    prints_from_quote,
)

TS = "2026-08-14T13:30:00.500Z"
TS_EPOCH = 1786714200.5  # calculé, pas estimé


# ---------------------------------------------------------------- §2.1

def test_AUCUN_endpoint_d_execution_dans_la_source():
    """Le garde structurel. L'API Tradovate SAIT passer des ordres — c'est pourquoi ce module
    doit être borné explicitement, et pas seulement « pas encore écrit » (§2.1)."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "datasource" / "tradovate.py").read_text(encoding="utf-8")
    minuscule = src.lower()
    for interdit in ("placeorder", "order/place", "modifyorder", "cancelorder",
                     "liquidateposition", "order/cancel", "placeoso", "placeoco"):
        assert interdit not in minuscule, f"vocabulaire d'exécution dans la source : {interdit}"


# ---------------------------------------------------------------- codec

def test_les_trames_de_service_sont_reconnues():
    assert decode_frame("o") == (FRAME_OPEN, [])
    assert decode_frame("h") == (FRAME_HEARTBEAT, [])
    assert decode_frame("c") == ("c", [])


def test_une_trame_tableau_rend_ses_messages():
    kind, msgs = decode_frame('a[{"e":"md"},{"e":"props"}]')
    assert kind == FRAME_ARRAY and len(msgs) == 2


def test_une_trame_ILLISIBLE_ne_leve_pas_et_ne_devine_rien():
    """Deviner le contenu fabriquerait de la donnée de marché à partir d'un octet corrompu."""
    for mauvais in ("", None, 42, "a[pas du json", "a{}", "x[]", "a[1,2,3]"):
        kind, msgs = decode_frame(mauvais)
        assert msgs == [], mauvais
        assert kind in ("", FRAME_ARRAY), mauvais


def test_la_requete_respecte_le_cadrage_a_quatre_lignes():
    trame = encode_request("md/subscribequote", 7, {"symbol": "MESU6"})
    assert trame.split("\n") == ["md/subscribequote", "7", "", '{"symbol":"MESU6"}']


def test_un_corps_absent_ne_devient_pas_null():
    """Envoyer `null` là où le service attend du vide fait échouer une session sans message clair."""
    assert encode_request("user/syncrequest", 1).split("\n")[3] == ""


# ---------------------------------------------------------------- quotes → prints

def test_seul_un_TRADE_devient_un_print():
    """Une mise à jour de bid/ask n'est pas une transaction : la compter gonflerait le tape et
    fausserait CVD, ratio d'agression et vitesse."""
    msg = {"e": "md", "d": {"quotes": [
        {"timestamp": TS, "bid": {"price": 4999.75, "size": 10}},          # pas de trade
        {"timestamp": TS, "trade": {"price": 5000.25, "size": 3, "side": "Buy"}},
    ]}}
    prints = prints_from_quote(msg)
    assert len(prints) == 1
    assert prints[0]["price"] == 5000.25 and prints[0]["side"] == "BUY"
    assert abs(prints[0]["ts"] - TS_EPOCH) < 1.0


def test_un_print_INCOMPLET_est_ecarte_et_non_comble():
    msg = {"d": {"quotes": [
        {"timestamp": TS, "trade": {"price": 5000.0}},                     # pas de size
        {"timestamp": TS, "trade": {"size": 2}},                           # pas de prix
        {"trade": {"price": 5000.0, "size": 2}},                           # pas d'horodatage
    ]}}
    assert prints_from_quote(msg) == []


def test_un_cote_INCONNU_reste_None_et_n_est_pas_devine():
    """Un côté deviné inverse le signe du CVD."""
    msg = {"d": {"quotes": [{"timestamp": TS,
                             "trade": {"price": 5000.0, "size": 1, "side": "Inconnu"}}]}}
    assert prints_from_quote(msg)[0]["side"] is None


def test_les_deux_formes_d_enveloppe_sont_acceptees():
    """Se tromper d'enveloppe rendrait un flux entier silencieux — et le silence est
    indiscernable d'un marché calme."""
    plat = {"quotes": [{"timestamp": TS, "trade": {"price": 5000.0, "size": 1}}]}
    imbrique = {"d": plat}
    assert len(prints_from_quote(plat)) == 1
    assert len(prints_from_quote(imbrique)) == 1


# ---------------------------------------------------------------- DOM → carnet

def test_le_carnet_est_projete_avec_ses_deux_cotes():
    msg = {"d": {"doms": [{"bids": [{"price": 4999.75, "size": 12}],
                           "offers": [{"price": 5000.25, "size": 8}]}]}}
    book = book_from_dom(msg)
    assert book == {"bids": [[4999.75, 12.0]], "asks": [[5000.25, 8.0]]}


def test_un_DOM_vide_rend_None_et_non_un_carnet_a_zero_niveau():
    """Zéro niveau se lirait « plus aucune liquidité » — c'est une mesure, et elle serait fausse."""
    for vide in ({"d": {"doms": []}}, {"d": {"doms": [{"bids": [], "offers": []}]}}, {}):
        assert book_from_dom(vide) is None, vide


def test_un_niveau_ILLISIBLE_est_ecarte_pas_le_carnet_entier():
    msg = {"d": {"doms": [{"bids": [{"price": "x", "size": 1}, {"price": 4999.0, "size": 3}],
                           "offers": []}]}}
    assert book_from_dom(msg) == {"bids": [[4999.0, 3.0]], "asks": []}


# ---------------------------------------------------------------- fills → réconciliation

def test_un_fill_est_projete_pour_reconcile_entry_fill():
    """La forme attendue par D-098 — c'est ce qui supprime l'import CSV manuel."""
    msg = {"d": {"fills": [{"timestamp": TS, "contractName": "MESU6", "action": "Buy",
                            "price": 5000.25, "qty": 2}]}}
    fills = fills_from_sync(msg)
    assert len(fills) == 1
    f = fills[0]
    assert set(f) == {"instrument", "side", "price", "quantity", "ts"}
    assert f["instrument"] == "MESU6" and f["side"] == "BUY" and f["quantity"] == 2.0


def test_un_fill_INCOMPLET_est_ecarte():
    msg = {"d": {"fills": [{"timestamp": TS, "contractName": "MESU6"},          # ni prix ni qty
                           {"contractName": "MESU6", "price": 1.0, "qty": 1}]}}  # pas d'horodatage
    assert fills_from_sync(msg) == []


def test_un_horodatage_ILLISIBLE_ecarte_l_entree_au_lieu_de_la_dater_de_maintenant():
    """Dater un print de « maintenant » parce qu'on n'a pas su lire le sien fabriquerait de la
    fraîcheur — la panne deviendrait invisible."""
    msg = {"d": {"fills": [{"timestamp": "pas une date", "contractName": "MESU6",
                            "price": 1.0, "qty": 1}]}}
    assert fills_from_sync(msg) == []


def test_un_horodatage_EPOCH_est_accepte_dans_les_deux_unites():
    en_s = {"d": {"fills": [{"timestamp": 1786714200, "contractName": "M", "price": 1, "qty": 1}]}}
    en_ms = {"d": {"fills": [{"timestamp": 1786714200000, "contractName": "M",
                              "price": 1, "qty": 1}]}}
    assert fills_from_sync(en_s)[0]["ts"] == 1786714200.0
    assert fills_from_sync(en_ms)[0]["ts"] == 1786714200.0
