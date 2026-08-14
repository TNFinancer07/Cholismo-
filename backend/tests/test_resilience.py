"""Carte de sensibilité à la ruine (D-102).

Ce qui est vérifié : que la carte ne se présente JAMAIS comme une prédiction, qu'elle est
reproductible, et que le modèle qu'elle applique est bien celui qu'elle annonce.
"""
from __future__ import annotations

from app.resilience import (
    SLIPPAGE_TICKS,
    WIN_RATES,
    sensitivity_map,
    slippage_cost_in_win_rate_points,
)


def _carte(**kw):
    return sensitivity_map(sims=300, **kw)


# ---------------------------------------------------------------- honnêteté

def test_la_carte_ne_se_presente_JAMAIS_comme_une_prediction():
    """Le taux de réussite réel est INCONNU. Une matrice qui annoncerait « votre risque de ruine
    est de 12 % » présenterait une hypothèse comme une mesure."""
    c = _carte()
    assert c["kind"] == "sensitivity_map"
    assert "INCONNU" in c["disclaimer"]
    for row in c["cells"]:
        for cell in row:
            assert cell["status"] == "HYPOTHESIS"


def test_le_modele_applique_est_ecrit_dans_la_sortie():
    """Sans cela, on lirait des nombres sans savoir ce qu'ils supposent."""
    m = _carte()["model"]
    for cle in ("description", "r_usd", "tick_usd", "trades", "sims", "seed", "ruin"):
        assert cle in m, cle


def test_les_parametres_de_compte_viennent_du_PRESET_pas_d_une_idee():
    from app.risk_sizer import APEX_EOD_50K
    a = _carte()["account"]
    assert a["max_drawdown"] == APEX_EOD_50K.max_drawdown
    assert a["daily_loss_limit"] == APEX_EOD_50K.daily_loss_limit


# ---------------------------------------------------------------- reproductibilité

def test_deux_lectures_donnent_les_MEMES_nombres():
    """Sinon l'opérateur croirait voir une évolution là où il ne voit que du bruit."""
    assert _carte()["cells"] == _carte()["cells"]


def test_une_graine_DIFFERENTE_donne_des_nombres_differents():
    """Le garde symétrique : si la graine ne changeait rien, le tirage serait factice."""
    a = _carte(seed=1)["cells"]
    b = _carte(seed=2)["cells"]
    assert a != b


# ---------------------------------------------------------------- forme et monotonie

def test_la_grille_est_bien_4x4_sur_les_axes_annonces():
    c = _carte()
    assert len(c["cells"]) == len(SLIPPAGE_TICKS)
    assert all(len(row) == len(WIN_RATES) for row in c["cells"])
    assert c["axes"]["win_rate"] == list(WIN_RATES)


def test_un_meilleur_taux_de_reussite_ne_peut_pas_AUGMENTER_la_ruine():
    """Propriété du modèle, pas une valeur : une monotonie violée signalerait un calcul faux.
    Tolérance = bruit de Monte-Carlo à ce nombre de tirages."""
    for row in sensitivity_map(sims=3000)["cells"]:
        probas = [c["ruin_probability"] for c in row]
        for gauche, droite in zip(probas, probas[1:]):
            assert droite <= gauche + 0.05, probas


def test_un_slippage_NUL_ne_peut_pas_ruiner_plus_qu_un_slippage_FORT():
    c = sensitivity_map(sims=3000)
    sans = c["cells"][0][0]["ruin_probability"]
    fort = c["cells"][-1][0]["ruin_probability"]
    assert fort >= sans - 0.05


# ---------------------------------------------------------------- coût du slippage

def test_un_ecart_NUL_ne_se_lit_pas_comme_un_slippage_GRATUIT():
    """Le point : `0.0` sec ferait lire une absence de coût là où il y a une absence de
    résolution. Le statut doit distinguer les deux."""
    res = slippage_cost_in_win_rate_points(_carte())
    assert res["status"] in ("MEASURED", "BELOW_GRID_RESOLUTION", "NOT_MEASURABLE")
    if res["status"] == "BELOW_GRID_RESOLUTION":
        assert res["points"] is None
        assert "non nul" in res["detail"]
    assert res["grid_step_points"] == 10.0


def test_une_carte_SANS_seuil_sous_50pc_le_dit():
    vide = {"cells": [], "axes": {"win_rate": list(WIN_RATES)}}
    res = slippage_cost_in_win_rate_points(vide)
    assert res["status"] == "NOT_MEASURABLE" and res["points"] is None
