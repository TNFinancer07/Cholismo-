"""La cascade commune aux cinq dimensions — D-057.

`z_i = (x_i − μ_252)/σ_252` · `div_i = z_i(base) − z_i(quote)` · `D = tanh(Σ w_i·div_i) × tf`

Les specs tirent trois conséquences pratiques de cette mécanique, et ce sont elles que ces
tests protègent : il faut de la **profondeur** (252 points avant de produire quoi que ce soit),
la divergence **annule les biais communs mais pas les biais d'un seul côté**, et `tanh`
**écrase les extrêmes** — donc une donnée aberrante doit être vue à la COLLECTE, pas après.
"""
from __future__ import annotations

import math

import pytest

from app.providers import cascade as cs

# =============================================================================================
# Profondeur — « 252 points avant de produire quoi que ce soit »
# =============================================================================================


def test_sans_la_PROFONDEUR_exigee_il_n_y_a_pas_de_z_score():
    r = cs.zscore([1.0, 2.0, 3.0], window=252)
    assert r.value is None
    assert "252" in r.motif and "3" in r.motif


def test_z_score_calcule_sur_la_FENETRE_pas_sur_tout_l_historique():
    """Une série de 10 ans ne se normalise pas sur 10 ans : la fenêtre est la fenêtre."""
    values = [0.0] * 500 + [10.0] * 9 + [20.0]
    r = cs.zscore(values, window=10)
    assert r.n == 10
    assert r.mean == pytest.approx(11.0)


def test_z_score_valeur_exacte_ddof_1():
    r = cs.zscore([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], window=8)
    assert r.mean == pytest.approx(5.0)
    assert r.sigma == pytest.approx(2.13809, abs=1e-4)      # écart-type d'ÉCHANTILLON
    assert r.value == pytest.approx((9.0 - 5.0) / 2.13809, abs=1e-4)


def test_serie_CONSTANTE_n_a_pas_de_z_score_elle_a_une_division_par_zero():
    r = cs.zscore([3.0] * 30, window=30)
    assert r.value is None
    assert "écart-type" in r.motif


def test_sigma_QUASI_nul_est_traite_comme_nul_pas_comme_un_z_score_geant():
    """Sans plancher, une série presque plate fabrique des z-scores de plusieurs milliers qui
    dominent toute la somme pondérée — le piège du z-score signalé pour le σ du BEER."""
    values = [1.0] * 29 + [1.0 + 1e-12]
    assert cs.zscore(values, window=30).value is None


def test_valeur_NON_FINIE_dans_la_fenetre_invalide_le_z_score():
    assert cs.zscore([1.0, 2.0, float("nan")], window=3).value is None
    assert cs.zscore([1.0, 2.0, float("inf")], window=3).value is None


def test_fenetre_absurde_ne_produit_rien():
    for window in (0, -5, 1):
        assert cs.zscore([1.0, 2.0, 3.0], window=window).value is None


def test_z_score_EXTREME_est_SIGNALE_jamais_ecrete_en_douce():
    """`tanh` noiera l'aberration plus loin : si on ne la voit pas ici, personne ne la verra.
    On la signale — on ne la corrige pas à la place de l'opérateur (§2.1)."""
    values = [0.0] * 29 + [1000.0]
    r = cs.zscore(values, window=30)
    assert r.outlier is True
    assert r.value is not None and abs(r.value) > cs.OUTLIER_CAP


# =============================================================================================
# Divergence — on soustrait deux z-scores, pas deux niveaux
# =============================================================================================


def test_divergence_est_une_soustraction_de_z_scores():
    assert cs.divergence(1.5, 0.5) == pytest.approx(1.0)


def test_une_jambe_manquante_ne_produit_pas_une_divergence_a_moitie_vraie():
    assert cs.divergence(1.5, None) is None
    assert cs.divergence(None, 0.5) is None
    assert cs.divergence(1.5, float("nan")) is None


# =============================================================================================
# Agrégation — tanh, poids, timing_factor
# =============================================================================================

W = {"pmi": 0.30, "gap": 0.25, "lei": 0.20, "sahm": 0.15, "ip": 0.10}
FULL = {"pmi": 1.0, "gap": 0.5, "lei": -0.5, "sahm": 0.0, "ip": 2.0}


def test_agregation_tanh_ponderee():
    r = cs.aggregate(FULL, W)
    raw = 0.30 * 1.0 + 0.25 * 0.5 + 0.20 * -0.5 + 0.15 * 0.0 + 0.10 * 2.0
    assert r.raw == pytest.approx(raw)
    assert r.score == pytest.approx(math.tanh(raw))


def test_une_composante_MANQUANTE_ne_se_renormalise_pas_en_silence():
    """Renormaliser sur les composantes présentes changerait le sens de la mesure sans le dire :
    un D1 amputé du PMI (0.30, le plus gros poids) se lirait comme un D1 complet."""
    partial = {k: v for k, v in FULL.items() if k != "pmi"}
    r = cs.aggregate(partial, W)
    assert r.score is None
    assert r.missing == ("pmi",)
    assert "pmi" in r.motif


def test_composante_NON_FINIE_est_traitee_comme_manquante():
    r = cs.aggregate({**FULL, "lei": float("nan")}, W)
    assert r.score is None and "lei" in r.missing


def test_timing_factor_multiplie_APRES_le_tanh():
    r = cs.aggregate(FULL, W, timing_factor=0.70)
    assert r.score == pytest.approx(math.tanh(r.raw) * 0.70)


def test_timing_factor_douteux_ne_produit_pas_un_score_douteux():
    for bad in (float("nan"), float("inf"), -1.0, None):
        assert cs.aggregate(FULL, W, timing_factor=bad).score is None


def test_poids_qui_ne_somment_pas_a_1_sont_REFUSES():
    """La matrice du quadrant somme à 1.00 par construction ; des poids qui n'y somment pas
    signifient qu'on en a perdu un en route."""
    r = cs.aggregate(FULL, {**W, "ip": 0.90})
    assert r.score is None and "somme" in r.motif


def test_score_borne_par_construction():
    r = cs.aggregate({k: 50.0 for k in W}, W)
    assert r.score is not None and -1.0 <= r.score <= 1.0


def test_module_PURE_aucune_lecture_d_horloge():
    import inspect
    src = inspect.getsource(cs)
    for banned in ("time.time", "perf_counter", "monotonic"):
        assert banned not in src, banned
