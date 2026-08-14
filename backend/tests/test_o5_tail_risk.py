"""Feature — portage Python de la balise O5 (tail risk caché), D-076.

Port de `reference/v2/fast-engine/o5TailRisk.ts` (v2), sous verrou de parité (D-072).

O5 est la seule balise **autonome** : elle ne lit jamais le contexte options, seulement les
barres ES. Un fournisseur d'options mort ne doit pas l'entraîner dans sa chute.

Le v2 du TS est une rupture assumée sur le v1 : il accepte des **barres** (horodatage + clôture)
et non des rendements bruts, ce qui seul permet de calculer des log-returns, de rejeter les
barres dupliquées ou hors-ordre après une reconnexion Rithmic, et de détecter les trous
temporels. Ces trois protections sont testées ici — ce sont elles qui empêchent un mouvement
extrême d'être compté deux fois en silence.
"""
import inspect
import math

import pytest

from app import o5_tail_risk as o5


def _bars(n, *, start=1_000_000, step=60_000, close=6000.0):
    return [{"timestamp": start + i * step, "close": close} for i in range(n)]


def _varied(n, **kw):
    """Série non dégénérée (variance non nulle) mais sans queue extrême."""
    bars = _bars(n, **kw)
    for i, b in enumerate(bars):
        b["close"] = 6000.0 + (i % 7) * 0.25
    return bars


# ---------------------------------------------------------------------------
# Mode G2 : structurellement incapable de bloquer
# ---------------------------------------------------------------------------

def test_evaluate_o5_ne_leve_JAMAIS_meme_sur_entree_absurde():
    for mauvais in (None, 42, "des barres", [{"timestamp": "x", "close": None}], [{}]):
        r = o5.evaluate_o5(mauvais)
        assert r["status"] in o5.STATUSES, f"entrée {mauvais!r} a produit {r['status']}"


def test_evaluate_o5_ne_retourne_pas_de_booleen():
    src = inspect.getsource(o5.evaluate_o5)
    assert "return True" not in src and "return False" not in src


# ---------------------------------------------------------------------------
# push_bar — la protection contre le replay de reconnexion
# ---------------------------------------------------------------------------

def test_push_bar_ajoute_et_borne_le_tampon():
    buf = ()
    for i in range(10):
        buf, accepted, _ = o5.push_bar(buf, {"timestamp": 1_000 + i, "close": 6000.0}, 5)
        assert accepted
    assert len(buf) == 5
    assert buf[-1]["timestamp"] == 1_009, "on garde les plus RÉCENTES"


def test_push_bar_REJETTE_un_doublon():
    """Un replay de reconnexion Rithmic renvoyant une barre déjà vue donnerait un double poids
    silencieux à un mouvement potentiellement extrême — exactement ce que O5 mesure."""
    bar = {"timestamp": 1_000, "close": 6000.0}
    buf, _, _ = o5.push_bar((), bar, 10)
    buf2, accepted, reason = o5.push_bar(buf, bar, 10)
    assert accepted is False and reason == "duplicate"
    assert buf2 == buf, "le tampon n'est pas modifié"


def test_push_bar_REJETTE_une_barre_hors_ordre():
    buf, _, _ = o5.push_bar((), {"timestamp": 2_000, "close": 6000.0}, 10)
    _, accepted, reason = o5.push_bar(buf, {"timestamp": 1_000, "close": 6000.0}, 10)
    assert accepted is False and reason == "out_of_order"


def test_push_bar_est_PURE_le_tampon_d_entree_n_est_jamais_muté():
    origine = ({"timestamp": 1_000, "close": 6000.0},)
    o5.push_bar(origine, {"timestamp": 2_000, "close": 6001.0}, 10)
    assert len(origine) == 1


# ---------------------------------------------------------------------------
# Garde-fous, dans l'ORDRE spécifié
# ---------------------------------------------------------------------------

def test_echantillon_trop_petit():
    cfg = o5.O5_CONFIG_PLACEHOLDER
    r = o5.evaluate_o5(_varied(cfg["min_samples"]))     # il faut min_samples + 1 BARRES
    assert r["status"] == "O5_SAMPLE_TOO_SMALL"
    assert r["excess_kurtosis"] is None, "aucune valeur inventée sous le seuil d'échantillon"


def test_trou_temporel_dans_la_fenetre():
    bars = _varied(60)
    bars[30]["timestamp"] += o5.O5_CONFIG_PLACEHOLDER["max_bar_gap_ms"] + 1
    for b in bars[31:]:
        b["timestamp"] += o5.O5_CONFIG_PLACEHOLDER["max_bar_gap_ms"] + 1
    assert o5.evaluate_o5(bars)["status"] == "O5_DATA_GAP"


def test_le_trou_est_verifie_AVANT_le_calcul_des_moments():
    """L'ordre compte : calculer un kurtosis sur une fenêtre trouée produirait un nombre
    d'apparence valide sur une série qui n'existe pas."""
    src = inspect.getsource(o5.evaluate_o5)
    assert src.index("O5_DATA_GAP") < src.index("_compute_moments")


def test_prix_non_positif_ou_non_fini_rend_l_echantillon_invalide():
    bars = _varied(60)
    bars[10]["close"] = 0.0
    assert o5.evaluate_o5(bars)["status"] == "O5_SAMPLE_TOO_SMALL"
    bars = _varied(60)
    bars[10]["close"] = float("nan")
    assert o5.evaluate_o5(bars)["status"] == "O5_SAMPLE_TOO_SMALL"


def test_serie_degeneree_variance_nulle_ne_produit_PAS_un_kurtosis():
    """Prix constant → variance nulle → division par zéro. Refus explicite, jamais un `inf`."""
    assert o5.evaluate_o5(_bars(60))["status"] == "O5_SAMPLE_TOO_SMALL"


# ---------------------------------------------------------------------------
# Le calcul lui-même
# ---------------------------------------------------------------------------

def test_serie_normale_donne_PASS_avec_un_excess_kurtosis_modere():
    r = o5.evaluate_o5(_varied(130))
    assert r["status"] == "PASS"
    assert r["excess_kurtosis"] < o5.O5_CONFIG_PLACEHOLDER["kurtosis_threshold"]
    assert r["variance"] > 0 and r["skewness"] is not None


def test_une_queue_CACHEE_est_signalee():
    """Une série calme portant un seul saut violent : c'est précisément le risque que O5 existe
    pour révéler — la volatilité réalisée reste basse, le moment d'ordre 4 explose."""
    bars = _varied(130)
    bars[-1]["close"] = 6060.0                      # un saut isolé de 60 points
    r = o5.evaluate_o5(bars)
    assert r["status"] == "FLAG_HIDDEN_TAIL"
    assert r["excess_kurtosis"] > o5.O5_CONFIG_PLACEHOLDER["kurtosis_threshold"]


def test_l_attribution_designe_la_barre_qui_DOMINE_le_moment_d_ordre_4():
    """Sans elle, un opérateur voit « kurtosis 40 » sans savoir si c'est une distribution large
    ou un seul point aberrant."""
    bars = _varied(130)
    bars[-1]["close"] = 6060.0
    r = o5.evaluate_o5(bars)
    assert 0.0 <= r["dominant_residual_share"] <= 1.0
    assert r["dominant_residual_share"] > 0.5, "un saut unique doit dominer l'attribution"
    calme = o5.evaluate_o5(_varied(130))
    assert calme["dominant_residual_share"] < r["dominant_residual_share"]


def test_excess_kurtosis_suit_la_convention_m4_sur_m2_carre_moins_3():
    """Convention explicite du TS : `excess = m4/m2² − 3`. Une gaussienne tend vers 0."""
    import random
    rng = random.Random(2026)
    bars = _bars(400)
    prix = 6000.0
    for b in bars:
        prix *= math.exp(rng.gauss(0, 0.0004))
        b["close"] = prix
    r = o5.evaluate_o5(bars, o5.config_with(window_size=400, min_samples=100))
    assert abs(r["excess_kurtosis"]) < 1.5, f"excess={r['excess_kurtosis']} loin de 0"


def test_la_fenetre_glissante_ne_regarde_que_les_dernieres_barres():
    cfg = o5.config_with(window_size=50)
    bars = _varied(300)
    bars[0]["close"] = 9999.0                       # aberration TRÈS ancienne, hors fenêtre
    assert o5.evaluate_o5(bars, cfg)["status"] == "PASS"


def test_le_resultat_porte_la_config_UTILISEE_et_son_statut_placeholder():
    """Un seuil non calibré affiché sans son étiquette se lit comme un seuil validé."""
    r = o5.evaluate_o5(_varied(130))
    assert r["config_used"]["is_placeholder"] is True
    assert r["config_used"]["kurtosis_threshold"] == o5.O5_CONFIG_PLACEHOLDER["kurtosis_threshold"]


def test_evaluate_o5_est_PURE_sur_now():
    bars = _varied(130)
    assert o5.evaluate_o5(bars, now_ms=42)["timestamp"] == 42
    assert o5.evaluate_o5(bars, now_ms=7)["timestamp"] == 7


# ---------------------------------------------------------------------------
# Verrou de parité (D-072)
# ---------------------------------------------------------------------------

def _ts():
    from app.options_gates import ts_reference_source
    return ts_reference_source("o5TailRisk.ts")


@pytest.mark.parametrize("ts_key,py_key", [
    ("windowSize", "window_size"),
    ("minSamples", "min_samples"),
    ("kurtosisThreshold", "kurtosis_threshold"),
    ("maxBarGapMs", "max_bar_gap_ms"),
])
def test_parite_de_la_config_O5(ts_key, py_key):
    import re
    m = re.search(rf"{ts_key}:\s*([0-9_.]+)", _ts())
    assert m, f"{ts_key} introuvable dans o5TailRisk.ts"
    assert float(m.group(1).replace("_", "")) == float(o5.O5_CONFIG_PLACEHOLDER[py_key]), \
        f"{ts_key} diverge entre TypeScript et Python"


def test_parite_des_codes_de_statut_O5():
    import re
    m = re.search(r"export type O5Status\s*=\s*([^;]+);", _ts())
    assert m
    assert set(re.findall(r"'([A-Z0-9_]+)'", m.group(1))) == set(o5.STATUSES)


def test_parite_le_TS_reste_marque_PLACEHOLDER():
    """Si quelqu'un retire `isPlaceholder` du TS parce que « c'est calibré maintenant », ce test
    tombe — et la conversation a lieu, au lieu d'un seuil qui change de statut en silence."""
    assert "isPlaceholder: true" in _ts()
