"""Feature — Volume Profile dynamique (D-041).

Approche figée AVANT implémentation (Loop 1 étape 3) :
- agrège le volume exécuté par NIVEAU de prix (quantifié sur la grille de tick `k = round(prix/
  tick)`), sur une distribution synthétique `{prix: volume}` ;
- **POC** = niveau au volume max (égalité → prix le plus BAS, déterministe) ;
- **Value Area (70 %)** : depuis le POC, on ÉTEND en ajoutant à chaque pas le voisin (au-dessus de
  VAH ou en-dessous de VAL) au plus GROS volume, jusqu'à `va_pct · total` (égalité → côté haut) ;
  **VAH/VAL** = bornes prix de la VA ;
- **LVN** (Low Volume Nodes) = minima LOCAUX stricts (volume < deux voisins) ET `≤ lvn_ratio · vol
  POC` — une lacune à volume nul est un LVN fort ;
- grille CONTIGUË (lacunes remplies à 0) bornée à `max_levels` autour du POC (prix aberrant lointain
  n'explose jamais le profil) ;
- FAIL-CLOSED (§3) : prix/volume non-fini → ignoré ; OBSERVATION seule (§2.1).
"""
from app.volume_profile import build_volume_profile

TICK, VA, LVN_R, MAXL = 1.0, 0.7, 0.3, 400


def _vp(dist):
    return build_volume_profile(dist, TICK, VA, LVN_R, MAXL)


def test_poc_is_max_volume_level():
    assert _vp({100: 10, 101: 50, 102: 20})["poc"] == 101


def test_poc_tie_breaks_to_lowest_price():
    assert _vp({100: 50, 101: 0, 102: 50})["poc"] == 100     # égalité → prix bas (déterministe)


def test_value_area_expands_both_sides_to_70pct():
    # {100:10,101:20,102:40(POC),103:20,104:10} total=100, cible=70
    # POC102(40) → +103(20)=60 → +101(20)=80 ≥70 → VA={101,102,103}
    r = _vp({100: 10, 101: 20, 102: 40, 103: 20, 104: 10})
    assert r["poc"] == 102 and r["vah"] == 103 and r["val"] == 101 and r["total_volume"] == 100


def test_value_area_asymmetric_heavy_side():
    # POC102(50) → +101(25)>+103(15) → 75 ≥70 → VA={101,102}
    r = _vp({100: 5, 101: 25, 102: 50, 103: 15, 104: 5})
    assert r["poc"] == 102 and r["vah"] == 102 and r["val"] == 101


def test_lvn_local_minima_below_ratio():
    r = _vp({100: 50, 101: 5, 102: 50, 103: 5, 104: 50})
    assert r["lvn"] == [101, 103]                            # creux stricts, 5 ≤ 0.3·50


def test_lvn_zero_volume_gap_is_lvn():
    r = _vp({100: 50, 102: 50})                              # 101 rempli à 0 → creux fort
    assert 101 in r["lvn"]


def test_levels_contiguous_and_sorted():
    r = _vp({100: 10, 102: 30})                              # 101 rempli à 0
    prices = [lvl["price"] for lvl in r["levels"]]
    assert prices == [100, 101, 102]
    assert {lvl["price"]: lvl["volume"] for lvl in r["levels"]}[101] == 0


def test_quantizes_price_to_tick_grid():
    # tick 0.25 : 5000.10 et 5000.12 → même niveau 5000.0
    r = build_volume_profile({5000.10: 10, 5000.12: 5}, 0.25, VA, LVN_R, MAXL)
    lv = {lvl["price"]: lvl["volume"] for lvl in r["levels"]}
    assert lv[5000.0] == 15


def test_single_level_va_full_no_lvn():
    r = _vp({100: 50})
    assert r["poc"] == 100 and r["vah"] == 100 and r["val"] == 100 and r["lvn"] == []


def test_total_volume():
    assert _vp({100: 10, 101: 20, 102: 30})["total_volume"] == 60


def test_fail_closed_non_finite_ignored():
    r = _vp({float("nan"): 999, 100: 40, 101: float("inf")})
    assert r["poc"] == 100 and r["total_volume"] == 40


def test_empty_distribution():
    r = _vp({})
    assert r["poc"] is None and r["vah"] is None and r["val"] is None
    assert r["levels"] == [] and r["lvn"] == [] and r["total_volume"] == 0


def test_aberrant_far_price_bounded():
    r = build_volume_profile({100: 50, 1_000_000: 10}, TICK, VA, LVN_R, max_levels=50)
    assert len(r["levels"]) <= 50 and r["poc"] == 100       # fenêtre bornée autour du POC


# ---------- /devil (D-041) : conditions limites ----------

import math  # noqa: E402


def test_uniform_flat_distribution_no_crash():
    # distribution PLATE (aucun POC net) → POC = prix bas (déterministe), aucun LVN strict, pas de crash
    r = _vp({100: 10, 101: 10, 102: 10, 103: 10})
    assert r["poc"] == 100 and r["lvn"] == [] and r["total_volume"] == 40
    assert r["val"] <= r["poc"] <= r["vah"]                  # VA cohérente


def test_single_peak_va_is_poc_only():
    # pic unique : le POC seul dépasse déjà 70 % → VA = {POC}, aucune extension
    r = _vp({100: 5, 101: 5, 102: 1000, 103: 5})
    assert r["poc"] == 102 and r["vah"] == 102 and r["val"] == 102


def test_negative_and_zero_volume_ignored():
    r = _vp({100: 50, 101: -10, 102: 0})                    # vol ≤ 0 → ignoré (fail-closed §3)
    assert r["poc"] == 100 and r["total_volume"] == 50 and len(r["levels"]) == 1


def test_zero_or_negative_tick_returns_empty():
    assert build_volume_profile({100: 50}, 0.0, VA, LVN_R, MAXL)["poc"] is None
    assert build_volume_profile({100: 50}, -0.25, VA, LVN_R, MAXL)["poc"] is None


def test_non_dict_input_returns_empty():
    assert build_volume_profile([(100, 50)], TICK, VA, LVN_R, MAXL)["poc"] is None
    assert build_volume_profile(None, TICK, VA, LVN_R, MAXL)["levels"] == []


def test_massive_distribution_bounded_and_finite():
    dist = {100 + i * 0.25: (i % 50) + 1 for i in range(5000)}   # 5000 niveaux, gros volumes
    r = build_volume_profile(dist, 0.25, VA, LVN_R, max_levels=400)
    assert len(r["levels"]) <= 400
    assert math.isfinite(r["total_volume"]) and math.isfinite(r["poc"])
    assert all(math.isfinite(lvl["price"]) and math.isfinite(lvl["volume"]) for lvl in r["levels"])


def test_bool_volume_ignored():
    # bool est un int en Python → ne doit pas compter comme volume
    r = _vp({100: True, 101: 40})
    assert r["poc"] == 101 and r["total_volume"] == 40
