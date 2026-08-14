"""Vecteur de features à l'armement (D-108).

La règle qui décide de la valeur du jeu entier : **absent n'est pas zéro**. Un modèle entraîné sur
des zéros fictifs apprendrait que l'absence de mesure prédit quelque chose.
"""
from __future__ import annotations

from app.features import build_feature_vector

SETUP = {"instrument": "MES", "side": "BUY", "entry_price": 5000.0,
         "stop_loss": 4999.0, "target_price": 5001.25, "position_size": 2}


def _meta(value, freshness="FRESH"):
    return {"value": value, "freshness": freshness}


SCHEMA = {
    "s1_state": {
        "svs_score": _meta(72.5), "cvd": _meta(-1450.0), "chop": _meta(38.0),
        "structure": {"vpoc": _meta(5002.0)},
        "order_flow": {"aggressor_ratio": _meta(0.66), "absorption": _meta(True)},
    },
    "bridge_variables": {"vix": _meta(17.4)},
    "session_identity": {"news_state": "NORMAL", "session_marker": "OVERLAP_NY"},
    "liquidity_sweep": {"alert": {"direction": "BID_SWEEP"}},
}


def _v(**kw):
    return build_feature_vector(setup=SETUP, schema=SCHEMA, now_ms=1_786_714_200_000.0, **kw)


# ---------------------------------------------------------------- géométrie RÉELLE

def test_la_geometrie_enregistree_est_celle_que_le_MOTEUR_a_calculee():
    """Arbitrage D-107 : le TP est dynamique (VPOC, calibration par instrument). On enregistre ce
    qui sort, jamais une valeur théorique — un vecteur décrivant un moteur imaginaire n'entraîne
    rien d'utile. Ici 5001.25 − 5000.00 = 5 ticks, mais parce que c'est CALCULÉ."""
    f = _v()["features"]
    assert f["tp_target_ticks"] == 5.0
    assert f["stop_loss_ticks"] == 4.0
    assert f["rr_ratio"] == 1.25
    assert f["instrument"] == "MES" and f["direction"] == "BUY"


def test_un_TP_non_standard_est_enregistre_TEL_QUEL():
    """Le cas MNQ (tp_max_ticks=8) ou un TP raccourci par le VPOC. Le journal ne normalise pas."""
    setup = {**SETUP, "target_price": 5002.0}      # 8 ticks
    f = build_feature_vector(setup=setup, schema=SCHEMA, now_ms=0.0)["features"]
    assert f["tp_target_ticks"] == 8.0


def test_la_distance_au_VPOC_est_mesuree():
    """La variable qui explique POURQUOI le TP a été raccourci : sans elle, le modèle verrait un
    TP variable sans cause."""
    assert _v()["features"]["distance_to_vpoc_ticks"] == 8.0


# ---------------------------------------------------------------- absent ≠ zéro

def test_un_champ_ABSENT_vaut_None_et_entre_dans_missing():
    v = build_feature_vector(setup=SETUP, schema={}, now_ms=0.0)
    f = v["features"]
    assert f["cvd"] is None and f["vix"] is None
    assert "cvd" in v["missing"] and "vix" in v["missing"]
    assert v["complete"] is False


def test_un_ZERO_REEL_n_est_PAS_declare_manquant():
    """Le pendant indispensable : effacer un vrai zéro serait la même faute dans l'autre sens."""
    schema = {**SCHEMA, "s1_state": {**SCHEMA["s1_state"], "cvd": _meta(0.0)}}
    v = build_feature_vector(setup=SETUP, schema=schema, now_ms=0.0)
    assert v["features"]["cvd"] == 0.0
    assert "cvd" not in v["missing"]


def test_une_valeur_PERIMEE_est_traitee_comme_absente():
    """Pire qu'absente : elle a l'air d'une mesure et décrit un autre instant."""
    schema = {**SCHEMA, "bridge_variables": {"vix": _meta(17.4, "STALE")}}
    v = build_feature_vector(setup=SETUP, schema=schema, now_ms=0.0)
    assert v["features"]["vix"] is None and "vix" in v["missing"]


def test_un_NaN_ne_passe_pas_dans_le_jeu():
    schema = {**SCHEMA, "s1_state": {**SCHEMA["s1_state"], "svs_score": _meta(float("nan"))}}
    v = build_feature_vector(setup=SETUP, schema=schema, now_ms=0.0)
    assert v["features"]["svs_score"] is None and "svs_score" in v["missing"]


def test_absorption_booleenne_n_est_pas_convertie_en_nombre():
    """`True` deviendrait `1.0` par `float()` — et se confondrait avec une mesure continue."""
    assert _v()["features"]["absorption"] is True
    schema = {**SCHEMA, "s1_state": {**SCHEMA["s1_state"],
                                     "order_flow": {"absorption": _meta("peut-être")}}}
    assert build_feature_vector(setup=SETUP, schema=schema,
                                now_ms=0.0)["features"]["absorption"] is None


# ---------------------------------------------------------------- robustesse

def test_un_setup_ILLISIBLE_ne_leve_pas():
    """Mode G2 : une exception ici bloquerait la boucle d'armement."""
    for mauvais in (None, 42, "setup", object()):
        v = build_feature_vector(setup=mauvais, schema=SCHEMA, now_ms=0.0)
        assert v["features"]["entry_price"] is None
        assert v["complete"] is False


def test_un_stop_a_ZERO_tick_ne_produit_pas_une_division():
    setup = {**SETUP, "stop_loss": 5000.0}
    assert build_feature_vector(setup=setup, schema=SCHEMA, now_ms=0.0)["features"]["rr_ratio"] is None


def test_l_heure_est_dans_le_fuseau_de_l_operateur():
    f = _v()["features"]
    assert isinstance(f["hour_local"], int) and 0 <= f["hour_local"] <= 23


def test_le_contexte_de_seance_est_capture():
    f = _v()["features"]
    assert f["news_state"] == "NORMAL" and f["session"] == "OVERLAP_NY"
    assert f["sweep_direction"] == "BID_SWEEP"


def test_le_vecteur_est_SERIALISABLE_tel_quel():
    """Il part dans un journal append-only, en JSON."""
    import json
    json.dumps(_v())
