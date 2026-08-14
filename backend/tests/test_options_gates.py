"""Feature — portage Python des balises O1-O4 + assemblage O1-O5 (D-076).

Port de `reference/v2/fast-engine/gatesO1toO4.ts` et `decisionLog.ts`, sous verrou de parité
(doctrine D-072 : le test LIT le TypeScript et échoue si les deux côtés divergent).

**La garantie du mode G2 est STRUCTURELLE, pas une configuration.** Aucun évaluateur ne
retourne de booléen, aucun ne lève, et il n'existe nulle part un motif `if (!gate) block()`
désactivé qu'un refactor pourrait réactiver par accident : il n'y a simplement **aucun chemin
de blocage**. Les tests ci-dessous le vérifient par introspection, pas seulement par usage —
sinon la garantie ne tiendrait qu'à la discipline du prochain lecteur.

**Deux divergences délibérées avec le TS**, chacune dans le sens fail-closed, chacune testée :
1. un GEX **non fini** rend O1 `O1_DATA_UNAVAILABLE` (le TS tomberait dans la branche négative
   et produirait un `FLAG_STRONG` porteur d'un `NaN` — invalide en JSON, et §3 exige un refus
   explicite plutôt qu'une mesure inventée) ;
2. l'horodatage du futur, déjà tranché en D-075 pour le contexte lui-même.
"""
import inspect
import json
import math

import pytest

from app import options_gates as og
from app.options_context import ContextHealth, OptionsContextSnapshot

TICK = 0.25


def _snap(health=ContextHealth.OK, **over):
    raw = {
        "status": "OK",
        "gexLocalByStrike": {"5990": -150.0, "6015": 200.0},
        "gammaZeroEs": 6000.0,
        "putWallEs": 5985.0,
        "callWallEs": 6020.0,
        "netDriftCrossover": {"direction": "up", "ts": 1_000_000, "sourceConfirmed": True},
        "conversionFactorUsed": 1.003,
        "computedAt": 1_000_000,
        "sourceVendor": "mock",
    }
    raw.update(over)
    return OptionsContextSnapshot(health=health, raw=raw, age_s=1.0)


_ABSENT = OptionsContextSnapshot(health=ContextHealth.UNAVAILABLE, raw=None, age_s=None)


# ---------------------------------------------------------------------------
# La garantie structurelle — vérifiée par introspection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [og.evaluate_o1, og.evaluate_o2, og.evaluate_o3, og.evaluate_o4])
def test_aucun_evaluateur_ne_retourne_un_booleen(fn):
    """Un booléen invite un `if` ; un objet de statut ne s'y prête pas. C'est ce qui rend le
    blocage accidentel impossible plutôt que seulement déconseillé."""
    src = inspect.getsource(fn)
    assert "return True" not in src and "return False" not in src


@pytest.mark.parametrize("fn", [og.evaluate_o1, og.evaluate_o2, og.evaluate_o3, og.evaluate_o4])
def test_aucun_evaluateur_ne_leve_jamais(fn):
    """Mode G2 : un gate consultatif qui lève interromprait la chaîne d'armement — donc
    bloquerait, en contradiction avec sa propre nature."""
    assert "raise" not in inspect.getsource(fn)


def test_l_entree_de_journal_n_a_NI_blocked_NI_allowed():
    """`OptionsGatesLogEntry` existe pour remplir le journal, pas pour être testée par un `if`.
    Un champ `blocked` suffirait à faire naître le verrou qu'on refuse."""
    entry = og.evaluate_options_gates(_ABSENT, level=6000.0, side="LONG",
                                      entry_price=6000.0, target_price=6001.25,
                                      es_bars=(), now_ms=1_000_000)
    assert "blocked" not in entry and "allowed" not in entry
    assert set(entry) == {"o1", "o2", "o3", "o4", "o5", "context_health", "timestamp"}


# ---------------------------------------------------------------------------
# O1 — régime gamma local, signé par le côté
# ---------------------------------------------------------------------------

def test_o1_gex_positif_donne_PASS():
    r = og.evaluate_o1(_snap(), level=6015.0, side="LONG")
    assert r["status"] == "PASS" and r["gex_local"] == 200.0 and r["nearest_strike"] == 6015.0


def test_o1_asymetrie_par_cote_en_regime_negatif():
    """Asymétrie établie dans le Pont v2 : un LONG en régime gamma négatif est la plus
    défavorable des quatre combinaisons."""
    assert og.evaluate_o1(_snap(), 5990.0, "LONG")["status"] == "FLAG_STRONG"
    assert og.evaluate_o1(_snap(), 5990.0, "SHORT")["status"] == "FLAG_WEAK"


def test_o1_sous_le_seuil_de_significativite_le_regime_est_INDETERMINE():
    """En dessous du seuil, le régime est du bruit, pas un signal. Comparaison `<=` — le seuil
    lui-même est indéterminé, pas signifiant."""
    s = _snap(gexLocalByStrike={"6000": og.O1_SIGNIFICANCE_THRESHOLD})
    assert og.evaluate_o1(s, 6000.0, "LONG")["status"] == "O1_REGIME_INDETERMINE"
    s = _snap(gexLocalByStrike={"6000": og.O1_SIGNIFICANCE_THRESHOLD + 0.1})
    assert og.evaluate_o1(s, 6000.0, "LONG")["status"] == "PASS"


def test_o1_contexte_absent_ou_non_OK_est_DATA_UNAVAILABLE():
    assert og.evaluate_o1(_ABSENT, 6000.0, "LONG")["status"] == "O1_DATA_UNAVAILABLE"
    for health in (ContextHealth.STALE, ContextHealth.VENDOR_DOWN):
        assert og.evaluate_o1(_snap(health), 6000.0, "LONG")["status"] == "O1_DATA_UNAVAILABLE"


def test_o1_carte_vide_est_DATA_UNAVAILABLE():
    assert og.evaluate_o1(_snap(gexLocalByStrike={}), 6000.0, "LONG")["status"] == "O1_DATA_UNAVAILABLE"


def test_o1_strike_illisible_est_IGNORE_pas_fatal():
    s = _snap(gexLocalByStrike={"pas-un-nombre": 500.0, "6015": 200.0})
    assert og.evaluate_o1(s, 6015.0, "LONG")["status"] == "PASS"


def test_o1_gex_NON_FINI_est_refuse_DIVERGENCE_assumee():
    """Divergence documentée (D-076). Le TS ferait `Math.abs(NaN) <= 30` → faux, puis
    `NaN > 0` → faux, et conclurait au régime négatif : un `FLAG_STRONG` portant un `NaN`.
    Ce n'est pas du JSON valide, et §3 exige un refus explicite."""
    for mauvais in (float("nan"), float("inf")):
        s = _snap(gexLocalByStrike={"6000": mauvais})
        assert og.evaluate_o1(s, 6000.0, "LONG")["status"] == "O1_DATA_UNAVAILABLE"


# ---------------------------------------------------------------------------
# O2 — zone d'exclusion autour du gamma zero (symétrique par construction)
# ---------------------------------------------------------------------------

def test_o2_loin_du_flip_donne_PASS_pres_du_flip_FLAG():
    loin = 6000.0 + og.O2_EXCLUSION_TICKS * TICK
    assert og.evaluate_o2(_snap(), loin)["status"] == "PASS"
    pres = 6000.0 + (og.O2_EXCLUSION_TICKS - 1) * TICK
    assert og.evaluate_o2(_snap(), pres)["status"] == "FLAG_EXCLUSION_ZONE"


def test_o2_est_SYMETRIQUE_ni_long_ni_short_privilegie():
    """Près du point où le mécanisme est éteint, aucun côté n'est avantagé."""
    d = og.O2_EXCLUSION_TICKS * TICK
    assert (og.evaluate_o2(_snap(), 6000.0 + d)["distance_ticks"]
            == og.evaluate_o2(_snap(), 6000.0 - d)["distance_ticks"])


def test_o2_sans_gamma_zero_est_FLIP_UNKNOWN():
    assert og.evaluate_o2(_snap(gammaZeroEs=None), 6000.0)["status"] == "O2_FLIP_UNKNOWN"
    assert og.evaluate_o2(_ABSENT, 6000.0)["status"] == "O2_FLIP_UNKNOWN"


# ---------------------------------------------------------------------------
# O3 — obstacle géométrique entre l'entrée et l'objectif
# ---------------------------------------------------------------------------

def test_o3_mur_ENTRE_entree_et_TP_est_un_obstacle():
    r = og.evaluate_o3(_snap(), entry_price=6015.0, target_price=6025.0, side="LONG")
    assert r["status"] == "FLAG_OBSTACLE" and r["obstacle_level"] == 6020.0


def test_o3_mur_HORS_du_chemin_donne_PASS_sans_niveau():
    r = og.evaluate_o3(_snap(), entry_price=6000.0, target_price=6005.0, side="LONG")
    assert r["status"] == "PASS" and r["obstacle_level"] is None


def test_o3_regarde_le_mur_du_BON_cote():
    """LONG lit le call wall, SHORT le put wall. Les inverser retournerait le gate en silence."""
    long_r = og.evaluate_o3(_snap(), 6015.0, 6025.0, "LONG")
    short_r = og.evaluate_o3(_snap(), 6015.0, 6025.0, "SHORT")
    assert long_r["obstacle_level"] == 6020.0        # call wall
    assert short_r["status"] == "PASS"               # put wall à 5985, hors chemin


def test_o3_tolerance_exclut_un_mur_collé_aux_bornes():
    """Marge pour l'incertitude de conversion SPX→ES : un mur pile sur l'entrée ou le TP n'est
    pas un obstacle traversé."""
    s = _snap(callWallEs=6015.0 + og.O3_TOLERANCE_TICKS * TICK)
    assert og.evaluate_o3(s, 6015.0, 6025.0, "LONG")["status"] == "PASS"


def test_o3_sans_mur_est_WALLS_UNKNOWN():
    assert og.evaluate_o3(_snap(callWallEs=None), 6015.0, 6025.0, "LONG")["status"] == "O3_WALLS_UNKNOWN"
    assert og.evaluate_o3(_ABSENT, 6015.0, 6025.0, "LONG")["status"] == "O3_WALLS_UNKNOWN"


# ---------------------------------------------------------------------------
# O4 — Net Premium Drift : inerte par PRÉREQUIS EXTERNE, pas par bug
# ---------------------------------------------------------------------------

def test_o4_source_non_confirmee_court_circuite_TOUT_le_reste():
    """La source n'est confirmée que sur QQQ, pas SPY/SPX (Pont v2 §4). Ce court-circuit passe
    AVANT toute autre logique : avec les données disponibles aujourd'hui, O4 renvoie donc
    toujours ce statut. Ce n'est pas un bug à corriger."""
    s = _snap(netDriftCrossover={"direction": "up", "ts": 1_000_000, "sourceConfirmed": False})
    assert og.evaluate_o4(s, "LONG", 5985.0, 1_000_000)["status"] == "O4_SOURCE_UNCONFIRMED"


def test_o4_la_logique_d_alignement_EXISTE_et_fonctionne_une_fois_la_source_confirmee():
    """Le code n'est pas mort : il attend une donnée qui n'existe pas encore. On le prouve."""
    assert og.evaluate_o4(_snap(), "LONG", 5985.0, 1_000_000)["status"] == "PASS"


def test_o4_direction_opposee_ou_absente_est_NO_CONVICTION():
    assert og.evaluate_o4(_snap(), "SHORT", 6020.0, 1_000_000)["status"] == "O4_NO_CONVICTION"
    s = _snap(netDriftCrossover={"direction": None, "ts": None, "sourceConfirmed": True})
    assert og.evaluate_o4(s, "LONG", 5985.0, 1_000_000)["status"] == "O4_NO_CONVICTION"


def test_o4_croisement_TROP_VIEUX_est_NO_CONVICTION():
    trop_tard = 1_000_000 + og.O4_WINDOW_MS + 1
    assert og.evaluate_o4(_snap(), "LONG", 5985.0, trop_tard)["status"] == "O4_NO_CONVICTION"
    pile = 1_000_000 + og.O4_WINDOW_MS
    assert og.evaluate_o4(_snap(), "LONG", 5985.0, pile)["status"] == "PASS"


def test_o4_lieu_trop_eloigne_du_mur_pertinent_est_NO_LOCATION():
    loin = 5985.0 + (og.O4_LOCATION_TOLERANCE_TICKS + 1) * TICK
    assert og.evaluate_o4(_snap(), "LONG", loin, 1_000_000)["status"] == "O4_NO_LOCATION"


def test_o4_sans_mur_pertinent_est_NO_LOCATION():
    s = _snap(putWallEs=None)
    assert og.evaluate_o4(s, "LONG", 5985.0, 1_000_000)["status"] == "O4_NO_LOCATION"


def test_o4_contexte_absent_est_DATA_MISSING():
    assert og.evaluate_o4(_ABSENT, "LONG", 5985.0, 1_000_000)["status"] == "O4_DATA_MISSING"


# ---------------------------------------------------------------------------
# Assemblage + export CSV
# ---------------------------------------------------------------------------

def test_assemblage_produit_les_cinq_balises_et_la_sante_du_contexte():
    bars = tuple({"timestamp": 1_000_000 + i * 60_000, "close": 6000.0 + (i % 3)}
                 for i in range(40))
    entry = og.evaluate_options_gates(_snap(), level=6015.0, side="LONG", entry_price=6015.0,
                                      target_price=6025.0, es_bars=bars, now_ms=1_000_000)
    assert entry["o1"]["gate"] == "O1" and entry["o5"]["status"] in (
        "PASS", "FLAG_HIDDEN_TAIL", "O5_SAMPLE_TOO_SMALL", "O5_DATA_GAP")
    assert entry["context_health"] == "OK"
    json.loads(json.dumps(entry))            # part au journal et au canal SSE tel quel


def test_o5_ne_depend_JAMAIS_du_contexte_options():
    """Calcul local sur les barres ES : zéro dépendance fournisseur. Un Redis mort ne doit pas
    entraîner O5 dans sa chute."""
    bars = tuple({"timestamp": 1_000_000 + i * 60_000, "close": 6000.0 + (i % 5)}
                 for i in range(200))
    entry = og.evaluate_options_gates(_ABSENT, level=6000.0, side="LONG", entry_price=6000.0,
                                      target_price=6001.0, es_bars=bars, now_ms=1_000_000)
    assert entry["context_health"] == "UNAVAILABLE"
    assert entry["o1"]["status"] == "O1_DATA_UNAVAILABLE"
    assert entry["o5"]["status"] in ("PASS", "FLAG_HIDDEN_TAIL"), "O5 calcule quand même"


def test_export_csv_aplati_sans_None_bruts():
    entry = og.evaluate_options_gates(_ABSENT, level=6000.0, side="LONG", entry_price=6000.0,
                                      target_price=6001.0, es_bars=(), now_ms=1_000_000)
    cols = og.to_csv_columns(entry)
    assert cols["o1_status"] == "O1_DATA_UNAVAILABLE"
    assert cols["o1_gex_local"] == "", "une mesure absente s'exporte vide, jamais en 'None'"
    assert all(not isinstance(v, float) or math.isfinite(v) for v in cols.values())


# ---------------------------------------------------------------------------
# Verrou de parité (D-072) — le test qui LIT le TypeScript
# ---------------------------------------------------------------------------

def _ts(name):
    return og.ts_reference_source(name)


@pytest.mark.parametrize("const,python_value", [
    ("O1_SIGNIFICANCE_THRESHOLD", lambda: og.O1_SIGNIFICANCE_THRESHOLD),
    ("O2_EXCLUSION_TICKS", lambda: og.O2_EXCLUSION_TICKS),
    ("O3_TOLERANCE_TICKS", lambda: og.O3_TOLERANCE_TICKS),
    ("O4_WINDOW_MS", lambda: og.O4_WINDOW_MS),
    ("O4_LOCATION_TOLERANCE_TICKS", lambda: og.O4_LOCATION_TOLERANCE_TICKS),
])
def test_parite_des_seuils_O1_a_O4(const, python_value):
    import re
    m = re.search(rf"{const}\s*=\s*([0-9_.]+)", _ts("gatesO1toO4.ts"))
    assert m, f"{const} introuvable dans gatesO1toO4.ts"
    assert float(m.group(1).replace("_", "")) == float(python_value()), \
        f"{const} diverge entre TypeScript et Python"


def test_parite_du_tick_ES():
    import re
    m = re.search(r"TICK_ES\s*=\s*([0-9.]+)", _ts("gatesO1toO4.ts"))
    assert m and float(m.group(1)) == og.TICK_ES


@pytest.mark.parametrize("gate,statuses", [
    ("O1Status", {"PASS", "FLAG_WEAK", "FLAG_STRONG", "O1_REGIME_INDETERMINE", "O1_DATA_UNAVAILABLE"}),
    ("O2Status", {"PASS", "FLAG_EXCLUSION_ZONE", "O2_FLIP_UNKNOWN"}),
    ("O3Status", {"PASS", "FLAG_OBSTACLE", "O3_WALLS_UNKNOWN"}),
    ("O4Status", {"PASS", "O4_NO_CONVICTION", "O4_NO_LOCATION", "O4_DATA_MISSING",
                  "O4_SOURCE_UNCONFIRMED"}),
])
def test_parite_des_codes_de_STATUT(gate, statuses):
    """Un statut ajouté d'un seul côté ne casse aucun test d'usage : il produit une colonne de
    journal que personne ne sait relire. Le verrou attrape l'écart tout de suite."""
    import re
    src = _ts("gatesO1toO4.ts")
    m = re.search(rf"export type {gate}\s*=\s*([^;]+);", src)
    assert m, f"{gate} introuvable"
    ts_statuses = set(re.findall(r"'([A-Z0-9_]+)'", m.group(1)))
    assert ts_statuses == statuses
    assert ts_statuses == set(og.STATUSES[gate[:2]]), \
        f"{gate} : le port Python ne déclare pas les mêmes statuts"


def test_parite_les_colonnes_CSV_portent_les_MEMES_noms():
    """Le journal des 60+ setups sera relu par la calibration : une colonne renommée d'un côté
    casse la corrélation silencieusement."""
    import re
    src = _ts("decisionLog.ts")
    # Le corps de `toCsvColumns` UNIQUEMENT : balayer tout le fichier ramasserait aussi les
    # champs de `OptionsGatesLogEntry` (dont `timestamp`), qui n'est pas une colonne CSV.
    body = src.split("export function toCsvColumns", 1)[1]
    ts_cols = set(re.findall(r"^\s{4}([a-z0-9_]+):", body, re.MULTILINE))
    assert len(ts_cols) == 15, f"colonnes extraites : {sorted(ts_cols)}"
    entry = og.evaluate_options_gates(_ABSENT, level=1.0, side="LONG", entry_price=1.0,
                                      target_price=2.0, es_bars=(), now_ms=0)
    assert ts_cols == set(og.to_csv_columns(entry))
