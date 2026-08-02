"""Mode Replay local — ce que le moteur refuse de deviner (Étape 1).

L'API publique demandée est conservée : `ReplayEngine(filepath, cb).start(speed_delay)`. Ces
tests protègent les six gardes qui la séparent d'un lecteur CSV naïf — chacune correspond à un
défaut qui se paie en silence.
"""
from __future__ import annotations

import time

import pytest

from app.replay.mock_data_generator import generer
from app.replay.replay_engine import ReplayEngine

EN_TETE = "timestamp,price,volume,side,bid_vol,ask_vol\n"


def _fichier(tmp_path, lignes: str, entete: str = EN_TETE):
    chemin = tmp_path / "tape.csv"
    chemin.write_text(entete + lignes, encoding="utf-8")
    return str(chemin)


def _rejouer(chemin, **kw):
    vus: list[dict] = []
    resume = ReplayEngine(chemin, vus.append).start(**kw)
    return vus, resume


# =============================================================================================
# 1. Une ligne pourrie n'emporte pas le replay
# =============================================================================================


def test_une_ligne_illisible_est_ECARTEE_pas_le_replay_entier(tmp_path):
    """`float(row['price'])` levait au milieu du flux, APRÈS avoir déjà émis des ticks : le
    consommateur se retrouvait avec un tape tronqué qu'il croyait complet."""
    chemin = _fichier(tmp_path,
                      "1000.0,5000.00,10,BUY,100,100\n"
                      "1001.0,,10,BUY,100,100\n"          # prix vide
                      "1002.0,5000.50,10,SELL,100,100\n")
    vus, resume = _rejouer(chemin)
    assert len(vus) == 2 and resume.emitted == 2
    assert resume.skipped == 1
    assert "prix" in resume.resume


def test_chaque_rejet_est_COMPTE_et_MOTIVE(tmp_path):
    chemin = _fichier(tmp_path,
                      "1000.0,5000.00,10,BUY,100,100\n"
                      "1001.0,n/a,10,BUY,100,100\n"
                      "1002.0,5000.00,3.5,BUY,100,100\n"    # volume fractionnaire
                      "1003.0,5000.00,10,UNKNOWN,100,100\n"
                      "abc,5000.00,10,BUY,100,100\n")
    _, resume = _rejouer(chemin)
    assert resume.emitted == 1 and resume.skipped == 4
    assert sum(resume.reasons.values()) == 4
    assert len(resume.reasons) == 4                        # quatre motifs DISTINCTS


# =============================================================================================
# 2. Absent n'est pas zéro — la leçon D-055
# =============================================================================================


def test_une_profondeur_ABSENTE_rend_None_jamais_zero(tmp_path):
    """« Hors profondeur ≠ taille nulle » (D-055). Zéro volume est un FAIT (personne n'est là) ;
    absent est un INCONNU. `row.get('bid_vol', 0)` fabriquait une liquidité qui n'a jamais
    existé — ou son contraire."""
    chemin = _fichier(tmp_path,
                      "1000.0,5000.00,10,BUY,,100\n"       # bid_vol vide
                      "1001.0,5000.00,10,BUY,0,100\n")     # bid_vol RÉELLEMENT nul
    vus, _ = _rejouer(chemin)
    assert vus[0]["bid_vol"] is None                       # inconnu
    assert vus[1]["bid_vol"] == 0.0                        # fait observé
    assert vus[0]["bid_vol"] != vus[1]["bid_vol"]          # jamais confondus


def test_une_colonne_de_profondeur_ABSENTE_du_fichier_rend_None(tmp_path):
    chemin = _fichier(tmp_path, "1000.0,5000.00,10,BUY\n",
                      entete="timestamp,price,volume,side\n")
    vus, _ = _rejouer(chemin)
    assert vus[0]["bid_vol"] is None and vus[0]["ask_vol"] is None


# =============================================================================================
# 3. Le tape ne remonte pas le temps
# =============================================================================================


def test_un_horodatage_qui_RECULE_est_refuse(tmp_path):
    """Tout le Niveau 2 order flow calcule sur des fenêtres temporelles : un tape non monotone
    y produit des mesures absurdes mais parfaitement crédibles."""
    chemin = _fichier(tmp_path,
                      "1000.0,5000.00,10,BUY,100,100\n"
                      "0990.0,5000.00,10,BUY,100,100\n"    # 10 s en arrière
                      "1001.0,5000.00,10,BUY,100,100\n")
    vus, resume = _rejouer(chemin)
    assert [t["timestamp"] for t in vus] == [1000.0, 1001.0]
    assert any("MONOTONE" in m for m in resume.reasons)


def test_un_horodatage_en_MILLISECONDES_est_reconnu(tmp_path):
    """Un tape exporté en ms lu comme des secondes placerait la séance en l'an 56 000 — et
    toutes les fenêtres deviendraient gigantesques sans que rien ne le signale."""
    chemin = _fichier(tmp_path, "1785600000000,5000.00,10,BUY,100,100\n")
    vus, _ = _rejouer(chemin)
    assert 1.7e9 < vus[0]["timestamp"] < 1.8e9


# =============================================================================================
# 4. Cadence : un tape uniforme n'est pas un marché
# =============================================================================================


def test_speed_honore_les_INTERVALLES_REELS_du_fichier(tmp_path):
    """Une cadence FIXE ne ressemble à aucun tape : le marché arrive par rafales et par trous,
    et c'est exactement ce que cherche `TAPE_BURST`. Rejouer à intervalle constant rendrait le
    phénomène qu'on veut tester structurellement inobservable."""
    chemin = _fichier(tmp_path,
                      "1000.00,5000.00,10,BUY,100,100\n"
                      "1000.02,5000.00,10,BUY,100,100\n"   # +20 ms
                      "1000.32,5000.00,10,BUY,100,100\n")  # +300 ms
    ecarts: list[float] = []
    dernier = [time.perf_counter()]

    def cb(_tick):
        maintenant = time.perf_counter()
        ecarts.append(maintenant - dernier[0])
        dernier[0] = maintenant

    ReplayEngine(chemin, cb).start(speed=10.0)             # ×10 → 2 ms puis 30 ms
    assert ecarts[2] > ecarts[1] * 3                       # le trou reste un trou


def test_speed_delay_reste_supporte_pour_compatibilite(tmp_path):
    chemin = _fichier(tmp_path, "1000.0,5000.00,10,BUY,100,100\n" * 3)
    debut = time.perf_counter()
    _, resume = _rejouer(chemin, speed_delay=0.01)
    assert resume.emitted == 3 and time.perf_counter() - debut >= 0.02


def test_un_TROU_geant_dans_le_fichier_ne_gele_pas_la_session(tmp_path):
    """Une heure de vide entre deux ticks ne doit pas se traduire par une heure d'attente."""
    chemin = _fichier(tmp_path,
                      "1000.0,5000.00,10,BUY,100,100\n"
                      "4600.0,5000.00,10,BUY,100,100\n")   # +1 h
    debut = time.perf_counter()
    _rejouer(chemin, speed=1.0)
    assert time.perf_counter() - debut < 6.0               # borné, pas 3 600 s


# =============================================================================================
# 5. Arrêt, plafond, et fichier inexploitable
# =============================================================================================


def test_stop_interrompt_proprement_et_le_DIT(tmp_path):
    chemin = _fichier(tmp_path, "".join(
        f"{1000 + i}.0,5000.00,10,BUY,100,100\n" for i in range(50)))
    moteur = ReplayEngine(chemin, lambda t: None)
    vus = []

    def cb(tick):
        vus.append(tick)
        if len(vus) == 5:
            moteur.stop()

    moteur.on_tick_callback = cb
    resume = moteur.start()
    assert resume.emitted == 5 and resume.stopped_early
    assert "ARRÊTÉ AVANT LA FIN" in resume.resume


def test_le_plafond_de_ticks_est_DIT_pas_silencieux(tmp_path):
    chemin = _fichier(tmp_path, "".join(
        f"{1000 + i}.0,5000.00,10,BUY,100,100\n" for i in range(20)))
    _, resume = _rejouer(chemin, max_ticks=5)
    assert resume.emitted == 5 and resume.stopped_early
    assert any("plafond" in m for m in resume.reasons)


def test_un_CSV_sans_colonne_obligatoire_est_refuse_AVANT_d_emettre(tmp_path):
    """Émettre puis échouer serait pire : le consommateur aurait déjà agi sur un tape amputé."""
    chemin = _fichier(tmp_path, "1000.0,10,BUY\n", entete="timestamp,volume,side\n")
    with pytest.raises(ValueError) as e:
        _rejouer(chemin)
    assert "price" in str(e.value)


def test_un_fichier_VIDE_ne_ment_pas(tmp_path):
    _, resume = _rejouer(_fichier(tmp_path, "", entete=""))
    assert resume.emitted == 0 and resume.skipped == 0


def test_une_exception_du_CALLBACK_n_est_PAS_avalee(tmp_path):
    """C'est un défaut du consommateur, pas une ligne pourrie du fichier. L'avaler ferait
    passer un bug applicatif pour une donnée manquante."""
    chemin = _fichier(tmp_path, "1000.0,5000.00,10,BUY,100,100\n")

    def cb(_):
        raise RuntimeError("bug du consommateur")

    with pytest.raises(RuntimeError):
        ReplayEngine(chemin, cb).start()


# =============================================================================================
# 6. Le générateur — un mock trop propre est un piège (CLAUDE §4)
# =============================================================================================


def test_le_generateur_seme_des_PATHOLOGIES_par_defaut(tmp_path):
    bilan = generer(tmp_path / "t.csv", 300)
    assert not bilan["propre"] and sum(bilan["seme"].values()) > 0
    for attendu in ("prix vide", "côté inconnu", "horodatage qui recule", "profondeur absente",
                    "rafale", "trou"):
        assert attendu in bilan["seme"], attendu


def test_le_moteur_ENCAISSE_le_tape_pathologique_sans_s_arreter(tmp_path):
    """Le test qui compte : bout à bout, générateur → moteur, sans exception."""
    chemin = tmp_path / "t.csv"
    bilan = generer(chemin, 300)
    vus, resume = _rejouer(str(chemin))
    assert resume.emitted > 200 and resume.skipped > 0
    assert resume.emitted + resume.skipped == bilan["lignes"]
    assert all(t["side"] in ("BUY", "SELL") for t in vus)
    assert all(t["price"] > 0 and t["volume"] >= 0 for t in vus)
    horodatages = [t["timestamp"] for t in vus]
    assert horodatages == sorted(horodatages)              # monotone par construction


def test_le_generateur_est_DETERMINISTE(tmp_path):
    """Un jeu d'essai qui change à chaque exécution rend tout écart inexplicable."""
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    generer(a, 100, graine=7)
    generer(b, 100, graine=7)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_le_mode_PROPRE_existe_mais_n_est_pas_le_defaut(tmp_path):
    bilan = generer(tmp_path / "c.csv", 200, propre=True)
    assert bilan["propre"] and bilan["seme"] == {}
    _, resume = _rejouer(str(tmp_path / "c.csv"))
    assert resume.skipped == 0
