"""Détecteur de vide de liquidité (D-111)."""
from __future__ import annotations

from app.mbo.vacuum import VacuumDetector, book_depth


def _book(size: float, levels: int = 10):
    return {"bids": [[5000 - i * 0.25, size] for i in range(levels)],
            "asks": [[5000 + i * 0.25, size] for i in range(levels)]}


def _chauffe(d: VacuumDetector, size: float, n: int):
    r = None
    for _ in range(n):
        r = d.observe(_book(size))
    return r


# ---------------------------------------------------------------- fail-closed

def test_au_DEMARRAGE_le_verdict_est_None_pas_carnet_sain():
    """Un détecteur qui répond « tout va bien » parce qu'il vient de démarrer serait pire que pas
    de détecteur."""
    r = VacuumDetector().observe(_book(50))
    assert r["vacuum"] is None
    assert "non mesurable" in r["detail"] and "pas « carnet sain »" in r["detail"]


def test_un_carnet_ILLISIBLE_rend_None():
    d = VacuumDetector(min_observations=3)
    _chauffe(d, 50, 5)
    for mauvais in (None, {}, {"bids": []}, {"bids": [[1, 2]]}, "carnet", 42):
        assert d.observe(mauvais)["vacuum"] is None, mauvais


def test_une_profondeur_ILLISIBLE_n_entre_PAS_dans_la_reference():
    """L'y mettre à zéro ferait chuter la médiane et déclencherait un faux vide au tick suivant."""
    d = VacuumDetector(min_observations=3)
    _chauffe(d, 50, 5)
    ref_avant = d.reference()
    for _ in range(5):
        d.observe(None)
    assert d.reference() == ref_avant


def test_un_seul_cote_ne_suffit_PAS():
    """Une profondeur calculée sur un côté sous-estimerait de moitié et se lirait comme un vide."""
    assert book_depth({"bids": [[5000, 10]]}) is None
    assert book_depth({"asks": [[5000, 10]]}) is None


# ---------------------------------------------------------------- détection

def test_un_effondrement_de_profondeur_est_signale():
    d = VacuumDetector(min_observations=5)
    _chauffe(d, 50, 6)
    r = d.observe(_book(5))
    assert r["vacuum"] is True and r["drop_ratio"] == 0.9
    assert "SLIPPAGE ACCRU" in r["detail"]


def test_un_carnet_STABLE_ne_declenche_pas():
    d = VacuumDetector(min_observations=5)
    r = _chauffe(d, 50, 10)
    assert r["vacuum"] is False and r["drop_ratio"] == 0.0


def test_une_baisse_SOUS_le_seuil_ne_declenche_pas():
    d = VacuumDetector(min_observations=5, drop_ratio=0.7)
    _chauffe(d, 100, 10)
    r = d.observe(_book(50))            # −50 %, sous le seuil de 70 %
    assert r["vacuum"] is False and r["drop_ratio"] == 0.5


def test_la_reference_est_une_MEDIANE_pas_une_moyenne():
    """Un seul mur énorme tirerait la moyenne, et le vide semblerait permanent après son retrait."""
    d = VacuumDetector(min_observations=3)
    normale = 10 * 10 * 2               # 10 niveaux × taille 10 × deux côtés
    _chauffe(d, 10, 4)
    d.observe(_book(10_000))            # mur exceptionnel
    ref = d.reference()
    assert ref == normale, f"la médiane doit ignorer l'aberrant, obtenu {ref}"
    # Une moyenne aurait donné (4×200 + 200000)/5 = 40160, et tout carnet normal aurait ensuite
    # semblé vide à 99,5 %.
    assert d.observe(_book(10))["vacuum"] is False


# ---------------------------------------------------------------- traçabilité

def test_le_verdict_porte_ses_SEUILS_et_dit_qu_ils_ne_sont_pas_calibres():
    r = VacuumDetector(min_observations=2).observe(_book(50))
    assert r["drop_ratio_threshold"] == 0.70
    assert r["calibrated"] is False
    assert r["levels"] == 10
