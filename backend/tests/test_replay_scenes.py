"""Le tape d'essai produit-il vraiment de la microstructure ? (D-061)

Jusqu'ici le générateur produisait des prints indépendants : un tape statistiquement plausible,
mais sans sweep, sans mur qui se recharge, sans rejet d'extrême. **B1, B3 et B4 n'étaient donc
exercés que sur des scènes construites à la main dans leurs propres tests** — rejouer mille
ticks de bruit ne les faisait pas réagir, et ne prouvait rien.

Ces tests vérifient deux choses distinctes :

1. que le générateur écrit bien les phénomènes qu'il annonce, avec leur vérité terrain ;
2. que les portes du calculateur RÉAGISSENT là où la vérité dit qu'elles devraient.

**Ce que ça prouve, et ce que ça ne prouve pas.** Une scène scriptée peut INFIRMER : un mur
qu'on a explicitement fait recharger et qui ne produit aucun B1 est un défaut. Elle ne peut pas
VALIDER : elle dit que le calculateur réagit à ce qu'on a écrit, pas qu'il mesure le marché.
Seul un vrai tape le dira.

**Pourquoi les seuils sont larges.** Réencoder ici la valeur exacte que rend le calculateur
ferait un test qui se vérifie lui-même : il passerait encore après avoir cassé la formule, du
moment qu'on aurait recopié le nouveau résultat. Les attentes portent donc sur le SIGNE et
l'ORDRE DE GRANDEUR.

Le carnet est reconstruit avec le `TapeBook` de `ReplayDataSource` — celui que le terminal utilise
réellement. Une deuxième reconstruction écrite pour le test prouverait quelque chose sur le
test, pas sur le chemin de production.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Optional

import pytest

from app.datasource.replay import TapeBook
from app.orderflow import compute_snapshot
from app.replay.mock_data_generator import generer
from app.replay import portes
from app.replay.replay_engine import ReplayEngine
from app.replay.scenes import SEQUENCE_DEFAUT, rejection

TICK = 0.25


# =============================================================================================
# Outillage — le MÊME chemin que la production : tape → ReplayEngine → TapeBook → compute_snapshot
# =============================================================================================


def _charger(chemin: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """`(ticks, prints, books)` tels que le terminal les verrait."""
    ticks = [t for t, _ in ReplayEngine(str(chemin), lambda _t: None).iter_ticks()]
    prints, books, book = [], [], TapeBook(tick=TICK)
    for i, t in enumerate(ticks):
        prints.append({"ts": t["timestamp"], "price": t["price"], "size": t["volume"],
                       "side": t["side"], "seq": i})
        book.update(t)
        payload = book.payload()
        if payload is not None:
            books.append({"ts": t["timestamp"], **payload})
    return ticks, prints, books


def _tape(tmp_path: Path, nom: str = "tape.csv", **kw: Any) -> tuple[Path, list[dict[str, Any]]]:
    """Génère un tape et rend `(chemin, vérité terrain)` relue depuis le fichier `.truth.json` —
    pas depuis le retour de `generer`, pour que le sidecar soit lui aussi éprouvé."""
    chemin = tmp_path / nom
    generer(chemin, 500, **kw)
    sidecar = chemin.with_name(chemin.name + ".truth.json")
    if not sidecar.exists():
        return chemin, []
    return chemin, json.loads(sidecar.read_text(encoding="utf-8"))["scenes"]


def _scene(verite: list[dict[str, Any]], nom: str) -> dict[str, Any]:
    return next(s for s in verite if s["nom"] == nom)


def _sur_la_scene(chemin: Path, scene: dict[str, Any], **kw: Any) -> Any:
    """Mesure sur la fenêtre de la SCÈNE seule.

    La fenêtre est bornée au phénomène, pas laissée à 30 s : sur une fenêtre longue, le bruit
    alentour domine et la scène ne dit plus rien. C'est une mesure de laboratoire — le
    comportement à la fenêtre réelle du terminal est éprouvé séparément, plus bas.
    """
    _, prints, books = _charger(chemin)
    return compute_snapshot(now=scene["fin_ts"], prints=prints, books=books,
                            window_s=scene["fin_ts"] - scene["debut_ts"] + 0.01, tick=TICK, **kw)


# =============================================================================================
# 1. Le générateur écrit ce qu'il annonce
# =============================================================================================


def test_le_generateur_intercale_des_SCENES_par_defaut(tmp_path):
    """Un mock sans phénomène de microstructure est le même piège qu'un mock sans pathologie
    (CLAUDE §4) : il ne ment pas, il ne dit simplement rien."""
    bilan = generer(tmp_path / "t.csv", 500)
    assert [s["nom"] for s in bilan["scenes"]] == list(SEQUENCE_DEFAUT)
    assert {s["porte"] for s in bilan["scenes"]} == {"B1", "B2", "B3", "B4"}   # les 4 portes


def test_la_verite_terrain_est_un_fichier_A_COTE_jamais_une_colonne(tmp_path):
    """Une colonne « scène » dans le CSV ferait fuiter la réponse dans la donnée : le moteur la
    lirait, et le tape ne serait plus un tape."""
    chemin, verite = _tape(tmp_path)
    entete = chemin.read_text(encoding="utf-8").splitlines()[0]
    assert entete == "timestamp,price,volume,side,bid_vol,ask_vol"
    assert len(verite) == len(SEQUENCE_DEFAUT)
    assert all(s["debut_ts"] < s["fin_ts"] for s in verite)


def test_aucune_PATHOLOGIE_n_est_injectee_DANS_une_scene(tmp_path):
    """Une ligne écartée au milieu d'un sweep en ferait un demi-sweep, et l'attente ne vaudrait
    plus rien — on croirait mesurer un phénomène qu'on a soi-même amputé."""
    chemin, verite = _tape(tmp_path)
    ticks, _, _ = _charger(chemin)
    lignes = chemin.read_text(encoding="utf-8").splitlines()[1:]
    for s in verite:
        ecrites = s["fin_idx"] - s["debut_idx"] + 1
        rejouees = sum(1 for t in ticks if s["debut_ts"] <= t["timestamp"] <= s["fin_ts"])
        assert rejouees == ecrites, f"{s['nom']} : {rejouees} rejoués pour {ecrites} écrits"
        assert all(lignes[i].count(",") == 5 and ",," not in lignes[i]
                   for i in range(s["debut_idx"], s["fin_idx"] + 1))


def test_les_scenes_sont_DETERMINISTES(tmp_path):
    """Un jeu d'essai qui change à chaque exécution rend tout écart inexplicable."""
    a, _ = _tape(tmp_path, "a.csv", graine=7)
    b, _ = _tape(tmp_path, "b.csv", graine=7)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_un_nom_de_scene_INCONNU_est_REFUSE_pas_ignore(tmp_path):
    """La faute la plus coûteuse du module, trouvée en le maltraitant : `scenes=("sweeep", …)`
    produisait un tape SANS sweep, sans rien dire. On aurait ensuite mesuré B4 dessus et conclu
    que la porte ne marche pas — un défaut inventé de toutes pièces par une faute de frappe.
    """
    with pytest.raises(ValueError) as e:
        generer(tmp_path / "x.csv", 500, scenes=("sweeep", "wall_refill"))
    assert "sweeep" in str(e.value) and "disponibles" in str(e.value)


def test_un_tape_TROP_COURT_pour_ses_scenes_le_DIT(tmp_path):
    """Un tape sans scène qui se croit avec est pire qu'un tape sans scène."""
    bilan = generer(tmp_path / "petit.csv", 8, scenes=SEQUENCE_DEFAUT)
    assert bilan["scenes"] == []
    assert "omise" in bilan["omises"] and "8 ticks" in bilan["omises"]


def test_une_VERITE_TERRAIN_illisible_n_emporte_pas_le_diagnostic(tmp_path, capsys):
    """Le tape est intact, c'est son étiquette qui ne l'est pas : le balayage reste valable et
    doit continuer de s'afficher, sans trace de pile."""
    chemin, _ = _tape(tmp_path)
    chemin.with_name(chemin.name + ".truth.json").write_text("{ pas du json", encoding="utf-8")
    assert portes.main([str(chemin)]) == 0
    sortie = capsys.readouterr().out
    assert "ILLISIBLE" in sortie and "régénérer" in sortie
    assert "BALAYAGE" in sortie


def test_le_bruit_SEUL_reste_possible_et_le_dit(tmp_path):
    chemin, verite = _tape(tmp_path, "bruit.csv", scenes=())
    assert verite == []
    assert not chemin.with_name(chemin.name + ".truth.json").exists()


# =============================================================================================
# 2. B4 — un sweep accélère l'agression
# =============================================================================================
#
# Le piège trouvé en construisant ce test : sur le tape BRUYANT, B4 dépasse 2 à 8 instants sur
# 59, et culmine à 14 — non par accélération, mais parce qu'un « trou de séance » vide la
# fenêtre AVANT et fait exploser un rapport de débits. Une assertion « B4 > 2 » serait donc
# passée pour la mauvaise raison. La comparaison ci-dessous est CONTRÔLÉE : deux fichiers de
# même graine, identiques jusqu'à l'insertion, donc à fenêtre AVANT rigoureusement égale. Seul
# l'après diffère.


def test_un_SWEEP_accelere_l_agression_la_ou_la_verite_le_dit(tmp_path):
    avec, verite = _tape(tmp_path, "avec.csv")
    sans, _ = _tape(tmp_path, "sans.csv", scenes=())
    sw = _scene(verite, "sweep")

    lignes_a = avec.read_text(encoding="utf-8").splitlines()
    lignes_s = sans.read_text(encoding="utf-8").splitlines()
    commun = next(i for i, (x, y) in enumerate(zip(lignes_a, lignes_s)) if x != y)
    assert commun > 50, "les deux tapes doivent partager leur préfixe pour que la comparaison tienne"

    mesures = {}
    for nom, chemin in (("avec", avec), ("sans", sans)):
        _, prints, books = _charger(chemin)
        mesures[nom] = compute_snapshot(now=sw["debut_ts"] + 1.1, prints=prints, books=books,
                                        window_s=3.0, tick=TICK, sweep={"ts": sw["debut_ts"]})

    b4_avec = mesures["avec"].post_sweep_aggression_ratio
    b4_sans = mesures["sans"].post_sweep_aggression_ratio
    assert b4_avec is not None and b4_sans is not None
    # À fenêtre AVANT identique, seule la rafale explique l'écart.
    assert b4_avec > 5 * b4_sans, f"B4 avec={b4_avec:.2f} sans={b4_sans:.2f}"
    assert mesures["avec"].tape_aggressor_buy_fraction > 0.85      # rafale ACHETEUSE
    assert mesures["sans"].tape_aggressor_buy_fraction < 0.8


def test_le_BRUIT_seul_n_a_pas_de_debit_qui_accelere(tmp_path):
    """Le contrôle négatif, et la raison pour laquelle le test précédent compare deux fichiers.

    Instant par instant, le bruit peut afficher un B4 élevé (fenêtre AVANT vidée par un trou de
    séance). Mais il n'a pas de tendance : sa MÉDIANE est à 1, c'est-à-dire « même débit avant
    et après ». C'est cela qu'un sweep contredit.
    """
    chemin, _ = _tape(tmp_path, "bruit.csv", scenes=())
    ticks, prints, books = _charger(chemin)
    vals = []
    for k in range(20, len(ticks) - 20, 7):
        ts = ticks[k]["timestamp"]
        snap = compute_snapshot(now=ts + 1.2, prints=prints, books=books, window_s=3.0,
                                tick=TICK, sweep={"ts": ts})
        if snap.post_sweep_aggression_ratio is not None:
            vals.append(snap.post_sweep_aggression_ratio)
    assert len(vals) > 20
    assert 0.5 < statistics.median(vals) < 1.6, f"médiane {statistics.median(vals):.2f}"


# =============================================================================================
# 3. B1 — un mur qui se recharge
# =============================================================================================


def test_un_MUR_qui_se_recharge_donne_un_B1_proche_de_1(tmp_path):
    """La scène creuse le mur de 400 à 40 puis le remonte à 380 : `rechargé/consommé` ≈ 340/360.
    On n'assène pas 0,944 — la formule doit pouvoir être rediscutée sans casser le test."""
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "wall_refill")
    snap = _sur_la_scene(chemin, s, wall_price=s["wall_price"], wall_side=s["wall_side"])
    assert snap.wall_refill_ratio is not None, snap.missing
    assert 0.6 < snap.wall_refill_ratio < 1.4
    assert snap.tape_aggressor_buy_fraction < 0.1        # on ATTAQUE le bid : que des ventes


def test_un_mur_qui_LACHE_se_distingue_d_un_mur_qui_TIENT(tmp_path):
    """Le couple qui rend le SENS du rapport observable — sans lui, `rechargé/consommé` et son
    inverse valent tous deux ≈ 1 sur un mur qui se reconstitue, et une inversion de la formule
    passe inaperçue. Défaut trouvé en mutant le calculateur pour éprouver ces tests.
    """
    chemin, verite = _tape(tmp_path)
    mesures = {}
    for nom in ("wall_refill", "wall_fail"):
        s = _scene(verite, nom)
        snap = _sur_la_scene(chemin, s, wall_price=s["wall_price"], wall_side=s["wall_side"])
        assert snap.wall_refill_ratio is not None, (nom, snap.missing)
        mesures[nom] = snap.wall_refill_ratio
    assert 0.05 < mesures["wall_fail"] < 0.5, mesures       # rechargé à 120 sur 400 consommés
    assert mesures["wall_refill"] > 2 * mesures["wall_fail"], mesures


def test_B1_est_lie_au_NIVEAU_designe_pas_a_l_ambiance(tmp_path):
    """Falsification : si B1 rendait la même chose à un prix où aucun mur n'a été scripté, il ne
    mesurerait pas un mur mais l'agitation générale."""
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "wall_refill")
    ailleurs = _sur_la_scene(chemin, s, wall_price=s["wall_price"] + 5 * TICK,
                             wall_side=s["wall_side"])
    assert ailleurs.wall_refill_ratio is None
    assert any(m.startswith("B1") for m in ailleurs.missing)


# =============================================================================================
# 4. Absorption — même agressivité, aucun niveau traversé
# =============================================================================================


def test_une_ABSORPTION_encaisse_sans_bouger_le_prix(tmp_path):
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "absorption")
    ticks, _, _ = _charger(chemin)
    prix = {t["price"] for t in ticks if s["debut_ts"] <= t["timestamp"] <= s["fin_ts"]}
    assert len(prix) == 1, f"l'absorption ne doit traverser aucun niveau : {sorted(prix)}"

    snap = _sur_la_scene(chemin, s, wall_price=s["wall_price"], wall_side=s["wall_side"])
    assert snap.tape_aggressor_buy_fraction < 0.15       # agression VENDEUSE
    assert snap.wall_refill_ratio is not None and snap.wall_refill_ratio > 0.5
    # Prix plat → aucun extrême : le calculateur REFUSE de nommer un rejet plutôt que de rendre
    # un 0,0 qui se lirait « rejet neutre observé » alors que rien n'a été observé.
    assert snap.rejection_delta_ratio is None
    assert any("prix plat" in m for m in snap.missing)


def test_un_SWEEP_et_une_ABSORPTION_ne_se_lisent_PAS_pareil(tmp_path):
    """Le couple qui distingue « traverser » de « encaisser ». Un calculateur qui rendrait la
    même chose sur les deux ne mesurerait pas la microstructure."""
    chemin, verite = _tape(tmp_path)
    ticks, _, _ = _charger(chemin)
    niveaux = {}
    for nom in ("sweep", "absorption"):
        s = _scene(verite, nom)
        niveaux[nom] = len({t["price"] for t in ticks
                            if s["debut_ts"] <= t["timestamp"] <= s["fin_ts"]})
    assert niveaux["sweep"] >= 5 and niveaux["absorption"] == 1


# =============================================================================================
# 5. B2 — pondéré au VOLUME, pas au nombre de prints
# =============================================================================================


def test_B2_pese_le_VOLUME_pas_le_NOMBRE_de_prints(tmp_path):
    """« Un print de 100 lots ne pèse pas comme un de 1 lot » — toute la raison d'être de la
    pondération de B2. Sur une scène d'accumulation, les deux lectures se CONTREDISENT : les
    prints disent vendeur, le volume dit acheteur. Sans cette divergence, un B2 compté par prints
    passait l'intégralité de cette suite (trouvé par mutation du calculateur).
    """
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "accumulation")
    ticks, _, _ = _charger(chemin)
    dans = [t for t in ticks if s["debut_ts"] <= t["timestamp"] <= s["fin_ts"]]
    achats = [t for t in dans if t["side"] == "BUY"]
    assert len(achats) / len(dans) < 0.25                        # minorité de PRINTS acheteurs
    assert sum(t["volume"] for t in achats) / sum(t["volume"] for t in dans) > 0.8   # …mais le
    assert _sur_la_scene(chemin, s).tape_aggressor_buy_fraction > 0.8                # VOLUME l'est


# =============================================================================================
# 6. B3 — le rejet d'un extrême, et son SIGNE
# =============================================================================================


def test_un_REJET_du_BAS_donne_un_B3_positif(tmp_path):
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "rejection")
    snap = _sur_la_scene(chemin, s)
    assert snap.rejection_delta_ratio is not None, snap.missing
    assert snap.rejection_delta_ratio > 0.3


def test_un_DOUBLE_CREUX_date_le_rejet_de_la_DERNIERE_touche(tmp_path):
    """Sur un double creux, partir de la PREMIÈRE touche fait compter la vente du second creux
    comme du rejet acheteur : le nombre reste crédible, il désigne juste l'inverse de ce qui
    s'est passé. La scène charge délibérément le second creux en volume vendeur — de quoi rendre
    l'erreur visible au lieu de la noyer (trouvé par mutation du calculateur).
    """
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "double_bottom")
    ticks, _, _ = _charger(chemin)
    dans = [t for t in ticks if s["debut_ts"] <= t["timestamp"] <= s["fin_ts"]]
    bas = min(t["price"] for t in dans)
    assert sum(1 for t in dans if t["price"] == bas) >= 4, "le creux doit être touché DEUX fois"
    snap = _sur_la_scene(chemin, s)
    assert snap.rejection_delta_ratio is not None, snap.missing
    assert snap.rejection_delta_ratio > 0.3, snap.rejection_delta_ratio


def test_le_SIGNE_de_B3_suit_le_sens_du_rejet(tmp_path):
    """Le falsificateur le plus dur : la scène miroir doit produire le signe OPPOSÉ. Une erreur
    de sens sur le delta agresseur reste parfaitement crédible en valeur absolue — c'est
    exactement le genre de faute qu'aucun test de magnitude ne rattrape.
    """
    import random

    from app.replay.mock_data_generator import COLONNES

    signes = {}
    for bas in (True, False):
        scene = rejection(1_785_600_000.0, 5000.0, TICK, random.Random(3), bas=bas)
        chemin = tmp_path / f"rejet_{bas}.csv"
        with open(chemin, "w", newline="", encoding="utf-8") as f:
            import csv
            w = csv.DictWriter(f, fieldnames=COLONNES)
            w.writeheader()
            w.writerows(scene.lignes)
        _, prints, books = _charger(chemin)
        snap = compute_snapshot(now=scene.fin_ts, prints=prints, books=books,
                                window_s=scene.fin_ts - scene.debut_ts + 0.01, tick=TICK)
        assert snap.rejection_delta_ratio is not None, (bas, snap.missing)
        signes[bas] = snap.rejection_delta_ratio
    assert signes[True] > 0 > signes[False], signes


# =============================================================================================
# 6. Ce que la fenêtre RÉELLE du terminal change — le constat qui compte
# =============================================================================================


def test_a_la_fenetre_REELLE_le_sweep_reste_visible(tmp_path):
    """B4 survit à la dilution : une rafale de quelques centaines de ms pèse encore sur un débit
    moyenné sur 30 s. C'est la porte la plus robuste des quatre."""
    chemin, verite = _tape(tmp_path)
    sw = _scene(verite, "sweep")
    _, prints, books = _charger(chemin)
    snap = compute_snapshot(now=sw["debut_ts"] + 1.1, prints=prints, books=books,
                            window_s=30.0, tick=TICK, sweep={"ts": sw["debut_ts"]})
    assert snap.post_sweep_aggression_ratio is not None
    assert snap.post_sweep_aggression_ratio > 2.0


def test_a_la_fenetre_REELLE_B1_se_TAIT_plutot_que_d_inventer(tmp_path):
    """**Le constat le plus utile de cette passe, et il n'est pas confortable.**

    Sur 30 s de tape réaliste, le carnet reconstruit comporte forcément un trou : le replay ne
    publie un carnet QUE lorsqu'un print tombe, donc un creux de séance de quelques secondes
    devient un trou d'observation. Au-delà de `ORDERFLOW_MAX_BOOK_GAP_S` (2 s), B1 refuse de
    mesurer une déplétion qu'il n'a pas vue.

    Ce n'est pas un défaut du calculateur : c'est le fail-closed de §3 qui fonctionne. Mais la
    conséquence doit être dite — **B1 n'est pas exploitable depuis un tape seul**, il lui faut
    un vrai flux L2. Le mur mesuré plus haut l'est sur une fenêtre de laboratoire.
    """
    chemin, verite = _tape(tmp_path, graine=42)
    s = _scene(verite, "wall_refill")
    _, prints, books = _charger(chemin)
    snap = compute_snapshot(now=s["fin_ts"], prints=prints, books=books, window_s=30.0,
                            tick=TICK, wall_price=s["wall_price"], wall_side=s["wall_side"])
    assert snap.wall_refill_ratio is None
    assert any("trou d'observation" in m for m in snap.missing), snap.missing


# =============================================================================================
# 7. L'outil qui rend tout ça lisible — `python -m app.replay.portes`
# =============================================================================================


def test_l_outil_de_diagnostic_montre_chaque_scene_REAGIR(tmp_path, capsys):
    chemin, verite = _tape(tmp_path)
    assert portes.main([str(chemin)]) == 0
    sortie = capsys.readouterr().out
    for s in verite:
        assert s["nom"] in sortie
    assert "MUETTE" not in sortie.split("BALAYAGE")[0], "une scène qui ne réagit pas est un défaut"


def test_l_outil_dit_ce_que_le_tape_ne_peut_PAS_alimenter(tmp_path, capsys):
    """Le chiffre qui compte avant de brancher un enregistrement : une porte muette 95 % du temps
    ne servira à rien en séance, et il vaut mieux le savoir avant que pendant."""
    chemin, _ = _tape(tmp_path)
    portes.main([str(chemin), "--pas", "20"])
    balayage = capsys.readouterr().out.split("BALAYAGE")[1]
    assert "B1" in balayage and "trou d'observation" in balayage
    assert "100%" in balayage                      # B2/B3/B4, elles, répondent partout


def test_sans_verite_terrain_la_section_SCENES_est_omise_pas_inventee(tmp_path, capsys):
    """Un export réel n'a pas de `.truth.json` : l'outil doit le dire, pas deviner des scènes."""
    chemin, _ = _tape(tmp_path, "brut.csv", scenes=())
    portes.main([str(chemin)])
    sortie = capsys.readouterr().out
    assert "aucun fichier de vérité terrain" in sortie
    assert "BALAYAGE" in sortie                    # l'autre section, elle, reste utile


def test_un_fichier_introuvable_le_dit_sans_trace_de_pile(tmp_path, capsys):
    assert portes.main([str(tmp_path / "absent.csv")]) == 2
    assert "introuvable" in capsys.readouterr().out


@pytest.mark.parametrize("porte,champ", [
    ("B1", "wall_refill_ratio"), ("B2", "tape_aggressor_buy_fraction"),
    ("B3", "rejection_delta_ratio"), ("B4", "post_sweep_aggression_ratio"),
])
def test_toute_porte_muette_dit_POURQUOI(tmp_path, porte: str, champ: str):
    """Quatre `None` muets ne disent pas pourquoi, et se lisent comme un marché calme."""
    chemin, verite = _tape(tmp_path)
    s = _scene(verite, "rejection")
    snap = _sur_la_scene(chemin, s)                       # ni mur désigné, ni sweep horodaté
    valeur: Optional[float] = getattr(snap, champ)
    if valeur is None:
        assert any(m.startswith(porte) for m in snap.missing), (porte, snap.missing)
