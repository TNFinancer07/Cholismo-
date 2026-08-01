"""`python -m app.providers` — découvrabilité du registre (D-057, /polish).

Un registre qui ne se lit qu'en important des modules n'est pas consultable. Ces tests
protègent ce qui rend la vue utilisable : rien de caché, rien de tronqué en silence, jamais un
glyphe seul, et aucun secret imprimé.
"""
from __future__ import annotations

from app.providers import __main__ as cli
from app.providers import catalog as cat

NOW = 1785542400.0                                        # 2026-08-01T00:00:00Z


def test_toutes_les_lignes_du_registre_sont_VISIBLES():
    """Une ligne absente de la vue est une ligne qu'on oubliera de relever."""
    out = cli.render(NOW)
    for spec in cat.CATALOG:
        assert spec.key in out, spec.key


def test_chaque_dimension_porte_son_TYPE_et_son_compte():
    out = cli.render(NOW)
    assert "type A directionnel" in out                    # D1 / D5
    assert "type B modulateur" in out                      # D4
    assert "absorbé par Arb1, poids 0" in out              # D2
    assert "absorbé par Arb2, poids 0" in out              # D3
    assert "collectables" in out


def test_une_ligne_non_collectable_dit_TOUJOURS_pourquoi():
    """§3 transposé au terminal : le statut ne passe jamais par le seul signal visuel. Un
    glyphe `≈` ou `✕` sans motif obligerait l'opérateur à décoder un symbole."""
    rendu = cli.render(NOW)
    bloquees = [s for s in cat.CATALOG if cat.fetch_block_reason(s.key) is not None]
    assert len(bloquees) >= 20
    for spec in bloquees:
        ligne = cli._row(spec)
        assert ligne in rendu, spec.key                    # la ligne testée est bien celle affichée
        reste = ligne.split(spec.key, 1)[1]
        assert any(m in reste for m in ("C2", "C3", "dérivé", "paramètre")), \
            f"{spec.key} : glyphe sans motif — « {ligne} »"


def test_les_trois_familles_ne_sont_pas_CONFONDUES_dans_le_compte():
    """« C3 » ne veut pas dire « donnée manquante », et un paramètre ne manque jamais."""
    out = cli.render(NOW)
    assert "identifiants à relever" in out
    assert "sources bloquées" in out
    assert "paramètres à calibrer" in out


def test_les_incoherences_sont_AFFICHEES_avec_leurs_deux_valeurs():
    out = cli.render(NOW)
    assert "Incohérences ouvertes" in out
    for conflict in cat.KNOWN_CONFLICTS:
        assert conflict["topic"] in out
    assert "0.4" in out and "0.0" in out
    assert "OUVERT" in out


def test_l_ecart_de_tenor_du_bundei_est_dans_la_vue():
    out = cli.render(NOW)
    assert "DE0001030575" in out and "BASCULE_REQUISE" in out


def test_aucune_ligne_ne_deborde_la_largeur():
    for ligne in cli.render(NOW).splitlines():
        assert len(ligne) <= cli.WIDTH, ligne


def test_la_troncature_est_VISIBLE():
    """Une ligne coupée en silence se lit comme une ligne complète."""
    assert "…" in cli.render(NOW)


def test_la_cle_API_n_est_JAMAIS_imprimee(monkeypatch):
    monkeypatch.setattr("app.config.FRED_API_KEY", "SECRET-NE-DOIT-PAS-FUIR")
    out = cli.render(NOW)
    assert "SECRET" not in out


def test_vue_par_ARBITRAGE_groupe_les_six_et_montre_leur_formule():
    out = cli.render(NOW, view="arbitrages")
    for arb in cat.ARBITRAGES:
        assert f"Arb {arb.arb_id} · {arb.name}" in out
        assert arb.threshold_label in out
    assert "taylor_diff" in out                            # la formule est là, pas juste le nom


def test_main_choisit_la_vue_et_rend_zero(capsys):
    assert cli.main([]) == 0
    assert "D1 · Cycle économique" in capsys.readouterr().out
    assert cli.main(["arbitrages"]) == 0
    assert "Arb 6 · Risk Reversal" in capsys.readouterr().out


def test_la_vue_est_en_LECTURE_SEULE_et_le_dit():
    out = cli.render(NOW)
    assert "lecture seule" in out and "aucun ordre" in out
