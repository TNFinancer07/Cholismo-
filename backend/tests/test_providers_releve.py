"""L'outil de relevé des lignes C2 (D-065).

Il ne collecte rien et ne décide rien : il répond à « si je relevais cet identifiant, qu'est-ce
qui s'allumerait ? » et « est-ce que ce candidat tient debout ? ». Ces tests protègent les deux
pièges qui rendraient une séance de catalogue inutile :

1. **juger ligne à ligne** — `nfa` seule n'ouvre rien puisque `tot` reste bloquée ; on
   conclurait à tort que le relevé ne sert à rien ;
2. **envoyer chercher un identifiant qui n'existe pas** — une ligne DÉRIVÉE marquée C2 ne se
   relève pas au catalogue, elle se calcule.
"""
from __future__ import annotations

import pytest

from app.providers.catalog import BY_KEY, Confidence, Kind
from app.providers.releve import debloque, inventaire, lignes_a_relever, valider


def test_seules_les_lignes_OBSERVEES_sont_a_relever():
    """`uip_implied` est C2 mais DÉRIVÉE : aucun catalogue ne contient son identifiant, parce
    qu'elle n'en a pas — elle se calcule depuis `dff` et `ecbdfr`."""
    cles = {s.key for s in lignes_a_relever()}
    assert "uip_implied" not in cles
    assert cles == {"oecd_cli", "nairu_ez", "r_star_us", "bundei_real", "nfa", "tot"}
    assert all(BY_KEY[k].kind is Kind.OBSERVED for k in cles)
    assert all(BY_KEY[k].confidence is Confidence.C2 for k in cles)


def test_le_relevé_se_raisonne_par_LOT_pas_ligne_a_ligne():
    """Le piège principal : prises SÉPARÉMENT, `nfa` et `tot` n'ouvrent rien ; ENSEMBLE elles
    ouvrent `beer_z`. Un outil qui ne saurait juger qu'une ligne à la fois ferait conclure que
    ces deux relevés sont inutiles."""
    assert debloque("nfa")[0] == ()
    assert debloque("tot")[0] == ()
    assert "beer_z" in debloque(["nfa", "tot"])[0]


def test_le_relevé_complet_debloque_EXACTEMENT_deux_champs():
    """État RÉEL du registre. Ce test échouera le jour où un blocage change — c'est voulu :
    l'enjeu d'une séance de catalogue ne doit pas dériver en silence."""
    champs, _ = debloque([s.key for s in lignes_a_relever()])
    assert set(champs) == {"beer_z", "leading_turn"}


@pytest.mark.parametrize("cle", ["bundei_real", "nairu_ez", "r_star_us"])
def test_trois_lignes_n_ouvrent_RIEN_meme_avec_les_autres(cle):
    """Constat inconfortable, dit plutôt qu'enfoui : `d5` et `rr_zscore` passent par des lignes
    DÉRIVÉES (`rdiff`, `ilsw_ez`) dont l'arithmétique n'est écrite nulle part. Relever
    `bundei_real` ne suffit donc pas — il faudra aussi écrire la dérivation."""
    lot = [s.key for s in lignes_a_relever()]
    ensemble, _ = debloque(lot)
    sans, _ = debloque([k for k in lot if k != cle])
    assert set(ensemble) == set(sans), f"{cle} serait devenue indispensable"


def test_la_simulation_ne_MODIFIE_pas_le_registre():
    """« Et si ? » ne doit jamais devenir « voilà ». Le registre sur disque fait foi."""
    avant = BY_KEY["nfa"]
    debloque(["nfa", "tot"], "IDENTIFIANT_INVENTE")
    assert BY_KEY["nfa"] is avant
    assert BY_KEY["nfa"].identifier is None
    assert BY_KEY["nfa"].confidence is Confidence.C2


def test_un_identifiant_MAL_FORME_est_refuse_et_le_DIT(capsys):
    """Le résultat le plus utile d'un relevé : le connecteur refuse la forme, et on l'apprend
    AVANT de la figer au registre. Ce n'est ni une panne, ni un défaut chez nous."""
    assert valider("nfa", "PAS_UNE_CLE_SDMX") == 1
    sortie = capsys.readouterr().out
    assert "IDENTIFIANT REFUSÉ" in sortie
    assert "CRASH" not in sortie


def test_une_cle_qui_n_est_PAS_a_relever_est_ecartee(capsys):
    for cle, attendu in (("dfii10", 2), ("uip_implied", 2), ("nexiste_pas", 2)):
        assert valider(cle, "X") == attendu
    assert "n'est pas au registre" in capsys.readouterr().out


def test_l_inventaire_donne_l_enjeu_et_le_protocole():
    texte = inventaire()
    assert "Relevé COMPLET" in texte and "beer_z" in texte and "leading_turn" in texte
    assert "INDISPENSABLE" in texte                     # le raisonnement par lot est montré
    assert "MANUEL" in texte                            # C2 se conclut à la main, par un humain
    for s in lignes_a_relever():
        assert s.key in texte


def test_l_inventaire_n_ouvre_AUCUNE_connexion():
    import socket

    vrai = socket.socket
    socket.socket = lambda *a, **k: (_ for _ in ()).throw(   # type: ignore[assignment]
        AssertionError("l'inventaire a tenté d'ouvrir une socket"))
    try:
        assert "CHOLISMO" in inventaire()
    finally:
        socket.socket = vrai          # type: ignore[assignment]
