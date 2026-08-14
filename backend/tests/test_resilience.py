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


# ---------------------------------------------------------------- biais du survivant (D-103)

from app.resilience import survivor_bias  # noqa: E402

RUINEUX = [-4.0] * 14 + [6.0] * 6          # pertes lourdes → la ruine devient atteignable


def test_sous_echantillon_INSUFFISANT_aucun_nombre_n_est_rendu():
    """Un DD95 sur trois trades décrirait ces trois trades, pas un risque (§3)."""
    res = survivor_bias([1.0, -1.0], sims=100, min_sample=4)
    assert res["status"] == "NOT_ENOUGH_DATA"
    for cle in ("dd95_all", "dd95_survivors", "bias_r"):
        assert res[cle] is None, cle


def test_le_biais_est_MESURE_quand_des_trajectoires_perissent():
    """Le cœur de la tranche : regarder les seules survivantes sous-estime le drawdown."""
    res = survivor_bias(RUINEUX, sims=800)
    assert res["status"] == "OK"
    assert res["dd95_survivors"] < res["dd95_all"], "les survivantes DOIVENT flatter"
    assert res["bias_r"] > 0
    assert 0.0 < res["survival_rate"] < 1.0


def test_les_DEUX_chiffres_sont_toujours_publies_jamais_le_seul_flatteur():
    res = survivor_bias(RUINEUX, sims=400)
    assert res["dd95_all"] is not None and res["dd95_survivors"] is not None


def test_AUCUNE_ruine_observee_n_est_PAS_un_biais_nul():
    """`bias_r: 0.0` se lirait « pas de biais » alors qu'il faut lire « rien n'a été exclu ».
    Même leçon que BELOW_GRID_RESOLUTION (D-102)."""
    res = survivor_bias([0.5, -1, 2, -1, 1.5, -1, -1, 3, 0.8, -1], sims=400)
    assert res["status"] == "NO_RUIN_OBSERVED"
    assert res["bias_r"] is None, "un biais non mesurable n'est pas un biais nul"
    assert res["survival_rate"] == 1.0
    assert "et non" in res["detail"]


def test_le_calcul_est_reproductible_et_la_graine_compte():
    a = survivor_bias(RUINEUX, sims=300, seed=7)
    b = survivor_bias(RUINEUX, sims=300, seed=7)
    c = survivor_bias(RUINEUX, sims=300, seed=8)
    assert a["dd95_all"] == b["dd95_all"]
    assert a["dd95_all"] != c["dd95_all"] or a["survival_rate"] != c["survival_rate"]


def test_un_drawdown_maximal_se_mesure_depuis_le_PIC_pas_depuis_zero():
    from app.resilience import _max_drawdown_r
    # Monte à +5, redescend à +1 → drawdown de 4, même si l'équité reste positive.
    assert _max_drawdown_r([5.0, -4.0]) == 4.0
    assert _max_drawdown_r([1.0, 1.0, 1.0]) == 0.0
    assert _max_drawdown_r([-2.0, -3.0]) == 5.0


def test_un_percentile_sur_liste_VIDE_rend_None_et_non_zero():
    from app.resilience import _percentile
    assert _percentile([], 0.95) is None, "0 se lirait « aucun drawdown »"


# ---------------------------------------------------------------- endpoint (D-104)

def test_l_endpoint_rend_les_DEUX_calculs_et_ne_les_confond_pas():
    """Ils se lisent ensemble mais leur nature diffère : l'un explore des hypothèses et est
    toujours calculable, l'autre part de données réelles et refuse sous échantillon insuffisant."""
    from fastapi.testclient import TestClient
    from app.api import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        res = client.get("/analyses/resilience")
    assert res.status_code == 200
    corps = res.json()

    assert corps["sensitivity"]["kind"] == "sensitivity_map"
    assert "INCONNU" in corps["sensitivity"]["disclaimer"]
    # Sans trades réconciliés, le biais REFUSE — et la carte, elle, reste calculée.
    assert corps["survivor_bias"]["kind"] == "survivor_bias"
    assert corps["survivor_bias"]["status"] in ("NOT_ENOUGH_DATA", "NO_RUIN_OBSERVED", "OK")
    assert len(corps["sensitivity"]["cells"]) == 4


def test_le_slippage_ne_frappe_QUE_la_perte_canon_9():
    """Entrée LIMITE + TP LIMITE : un ordre limite est rempli à son prix ou pas du tout. Seule la
    sortie au stop part au marché. Le retrancher du gain surestimerait le coût des gagnants.

    Contrôle : à 100 % de réussite, aucun stop n'est touché — le slippage ne doit donc RIEN
    changer, quel que soit son niveau."""
    from app.resilience import _ruin_probability
    from app.risk_sizer import APEX_EOD_50K
    import random

    equities = []
    for slip in (0.0, 2.0):
        rng = random.Random(1)
        # win_rate = 1.0 → que des TP limites, aucun stop au marché.
        equities.append(_ruin_probability(win_rate=1.0, slippage_ticks=slip,
                                          preset=APEX_EOD_50K, r_usd=100.0, tick_usd=1.25,
                                          trades=50, sims=200, rng=rng))
    assert equities[0] == equities[1] == 0.0

    m = sensitivity_map(sims=100)["model"]
    assert "LIMITE" in m["description"] and "sans slippage" in m["description"]


# ---------------------------------------------------------------- baseline R:R (D-109)

def test_le_RR_est_EXPLICITE_et_change_materiellement_le_resultat():
    """Il était figé à 1 sans le dire — l'hypothèse existait, elle était invisible. La rendre
    visible n'a de sens que si elle pèse : ce test le vérifie."""
    prudent = sensitivity_map(sims=1500, rr=1.0)["cells"][2][0]["ruin_probability"]
    genereux = sensitivity_map(sims=1500, rr=1.5)["cells"][2][0]["ruin_probability"]
    assert genereux < prudent, "un meilleur R:R doit réduire la ruine"


def test_la_carte_DIT_que_son_RR_est_une_baseline():
    m = sensitivity_map(sims=100)["model"]
    assert m["rr_source"] == "baseline"
    assert "VARIABLE" in m["rr_note"] and "ne décrit pas la dispersion" in m["rr_note"]
    assert sensitivity_map(sims=100, rr=1.4)["model"]["rr_source"] == "override"


def test_le_RR_observe_REFUSE_sous_echantillon_insuffisant():
    from app.resilience import observed_rr
    r = observed_rr([])
    assert r["status"] == "INSUFFICIENT_DATA" and r["mean"] is None
    assert "baseline" in r["detail"]


def test_le_RR_observe_rend_la_DISPERSION_pas_seulement_la_moyenne():
    """Une carte au R:R moyen masquerait les setups les moins favorables — ceux qui tuent."""
    from app.resilience import observed_rr
    entries = [{"feature_vector": {"features": {"rr_ratio": v}}}
               for v in (0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6)]
    r = observed_rr(entries)
    assert r["status"] == "OK" and r["n"] == 10
    assert r["min"] == 0.8 and r["max"] == 2.6
    assert r["min"] < r["mean"] < r["max"]


def test_un_rr_ratio_ABSENT_ou_ABSURDE_est_ecarte_pas_compte_comme_zero():
    from app.resilience import observed_rr
    entries = [{"feature_vector": {"features": {"rr_ratio": None}}},
               {"feature_vector": {"features": {}}},
               {"feature_vector": None}, {}, "pas un dict",
               {"feature_vector": {"features": {"rr_ratio": -1.0}}}]
    assert observed_rr(entries)["n"] == 0
