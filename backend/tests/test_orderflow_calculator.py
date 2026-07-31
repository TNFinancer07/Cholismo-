"""Feature — Order Flow in-house, Niveau 2 CALCUL (D-055).

Le module transforme un flux BRUT (carnet L2/MBO + Time & Sales) en `OrderFlowSnapshot` : les
quatre portes B1-B4, le profil de volume et l'ATR. Il **mesure**, il ne décide pas — aucun seuil,
aucun verdict : c'est `evaluate_lsr` qui compare, dans une tranche ultérieure.

Les tests décrivent d'abord ce qui doit rester **NON calculable** : chaque porte vaut `None` avec
son motif quand ses entrées ne suffisent pas. Une porte qui rendrait une valeur par défaut (0, 1,
0,5) serait la pire des sorties : un chiffre qui a l'air d'une mesure (§3).
"""
import math

import pytest

from app import config
from app.orderflow.calculator import OrderFlowSnapshot, compute_snapshot

T0 = 1_700_000_000.0
TICK = 0.25


def _print(ts_offset, price, size, side="BUY"):
    return {"ts": T0 + ts_offset, "price": price, "size": size, "side": side}


def _book(ts_offset, bids, asks):
    return {"ts": T0 + ts_offset, "bids": bids, "asks": asks}


def _snap(**over):
    kw = dict(now=T0 + 30.0, prints=[], books=[], bars=[], sweep=None, tick=TICK)
    kw.update(over)
    return compute_snapshot(**kw)


# =============================================================================================
# B2 — part acheteuse du tape (tapeAggressorBuyFraction)
# =============================================================================================

def test_B2_pondere_par_le_VOLUME_pas_par_le_NOMBRE_de_prints():
    """Un print de 100 lots ne pèse pas comme un print de 1 lot. Compter les prints donnerait
    0,10 là où le flux réel est acheteur à 92 % — l'inverse de la lecture."""
    prints = [_print(1, 5000.0, 100, "BUY")] + [_print(1 + i, 5000.0, 1, "SELL") for i in range(9)]
    s = _snap(prints=prints)
    assert s.tape_aggressor_buy_fraction == pytest.approx(100 / 109, abs=1e-9)


def test_B2_nominal_et_bornes():
    assert _snap(prints=[_print(1, 5000.0, 70, "BUY"),
                         _print(2, 5000.0, 30, "SELL")]).tape_aggressor_buy_fraction == 0.7
    assert _snap(prints=[_print(1, 5000.0, 50, "BUY")]).tape_aggressor_buy_fraction == 1.0
    assert _snap(prints=[_print(1, 5000.0, 50, "SELL")]).tape_aggressor_buy_fraction == 0.0


def test_B2_couverture_de_cote_INSUFFISANTE_rend_None():
    """Un tape dont on ignore le côté de la moitié du volume ne produit pas un ratio : il produit
    un mensonge. Sous le seuil de couverture, la porte n'est PAS calculée."""
    prints = [_print(1, 5000.0, 10, "BUY"), _print(2, 5000.0, 90, "INCONNU")]
    s = _snap(prints=prints)
    assert s.tape_aggressor_buy_fraction is None
    assert any("B2" in m for m in s.missing)


def test_B2_prints_HORS_FENETRE_exclus():
    # La fenêtre est [now − window, now] ; avec now = T0+30 elle commence à T0. Un print daté
    # AVANT T0 est dehors — c'est le sens du test, et la raison pour laquelle le print gardé est
    # daté +29 (ma première version datait les deux hors fenêtre et ne prouvait rien).
    old = _print(-10, 5000.0, 1000, "SELL")                  # avant le début de la fenêtre
    s = _snap(prints=[old, _print(29, 5000.0, 50, "BUY")])
    assert s.tape_aggressor_buy_fraction == 1.0          # le vieux volume ne pollue pas
    assert s.prints_used == 1


def test_B2_print_du_FUTUR_ecarte():
    """Désync d'horloge source (leçon D-048/D-050) : un print postérieur à `now` est un fantôme."""
    s = _snap(prints=[_print(+60, 5000.0, 999, "SELL"), _print(29, 5000.0, 50, "BUY")])
    assert s.tape_aggressor_buy_fraction == 1.0 and s.prints_dropped == 1


def test_B2_volume_nul_ou_non_fini_rend_None():
    for bad in (0, -5, math.nan, math.inf, "10", None, True):
        s = _snap(prints=[_print(1, 5000.0, bad, "BUY")])
        assert s.tape_aggressor_buy_fraction is None, bad


# =============================================================================================
# B1 — rechargement du mur (wallRefillRatio)
# =============================================================================================

def test_B1_nominal_consomme_puis_recharge():
    """Mur à 100, mangé jusqu'à 20 (consommé 80), revenu à 80 (rechargé 60) → 0,75."""
    books = [_book(0, [[4999.75, 100]], [[5000.25, 50]]),
             _book(5, [[4999.75, 20]], [[5000.25, 50]]),
             _book(10, [[4999.75, 80]], [[5000.25, 50]])]
    s = _snap(books=books, wall_price=4999.75, wall_side="BID")
    assert s.wall_refill_ratio == pytest.approx(0.75)


def test_B1_mur_JAMAIS_entame_rend_None_pas_1():
    """Sans déplétion, le rapport rechargé/consommé est une division par zéro. Rendre 1,0
    (« le mur a tenu ») serait inventer une défense qui n'a jamais été testée."""
    books = [_book(0, [[4999.75, 100]], []), _book(5, [[4999.75, 100]], [])]
    s = _snap(books=books, wall_price=4999.75, wall_side="BID")
    assert s.wall_refill_ratio is None
    assert any("B1" in m for m in s.missing)


def test_B1_mur_RETIRE_est_un_rechargement_NUL():
    """Le niveau disparaît du carnet alors qu'il est DANS la profondeur publiée : taille 0, fait
    réel (le mur a été retiré) — à distinguer du niveau hors profondeur, testé plus bas."""
    books = [_book(0, [[4999.75, 100], [4999.50, 40]], []),
             _book(5, [[4999.50, 40]], [])]                 # 4999.75 dans la plage, absent → 0
    s = _snap(books=books, wall_price=4999.75, wall_side="BID")
    assert s.wall_refill_ratio == 0.0


def test_B1_niveau_HORS_PROFONDEUR_publiee_rend_None():
    """Un carnet tronqué à 3 niveaux ne dit RIEN du 8e : absence ≠ taille nulle. C'est le piège
    exact d'un feed L2 partiel — le confondre inventerait un mur disparu."""
    books = [_book(0, [[4999.75, 100], [4999.50, 40]], []),
             _book(5, [[4999.75, 100], [4999.50, 40]], [])]
    s = _snap(books=books, wall_price=4990.00, wall_side="BID")   # bien sous la profondeur
    assert s.wall_refill_ratio is None


def test_B1_un_seul_snapshot_ou_aucun_rend_None():
    assert _snap(books=[_book(0, [[4999.75, 100]], [])],
                 wall_price=4999.75, wall_side="BID").wall_refill_ratio is None
    assert _snap(books=[], wall_price=4999.75, wall_side="BID").wall_refill_ratio is None


def test_B1_sans_niveau_de_reference_rend_None():
    """Pas de mur désigné (pas de sweep, pas de prix fourni) → rien à mesurer, et surtout pas un
    niveau choisi au hasard."""
    books = [_book(0, [[4999.75, 100]], []), _book(5, [[4999.75, 20]], [])]
    assert _snap(books=books).wall_refill_ratio is None


def test_B1_rechargement_SUPERIEUR_au_consomme_reste_honnete():
    """Mur mangé de 100 à 20 puis reconstruit à 160 : le ratio dépasse 1 — c'est une défense
    agressive, pas une anomalie. On ne l'écrête pas."""
    books = [_book(0, [[4999.75, 100]], []), _book(5, [[4999.75, 20]], []),
             _book(10, [[4999.75, 160]], [])]
    assert _snap(books=books, wall_price=4999.75, wall_side="BID").wall_refill_ratio == pytest.approx(1.75)


def test_B1_carnet_malforme_ignore_sans_casser():
    books = [_book(0, [[4999.75, 100]], []), {"ts": T0 + 5, "bids": "cassé", "asks": []},
             _book(10, [[4999.75, 40]], [])]
    s = _snap(books=books, wall_price=4999.75, wall_side="BID")
    assert s.wall_refill_ratio is not None                  # les snapshots sains suffisent


# =============================================================================================
# B3 — delta de rejet normalisé (rejectionDeltaRatio)
# =============================================================================================

def test_B3_rejet_du_BAS_est_positif():
    """Prix descend jusqu'à un extrême, puis l'acheteur reprend : delta post-extrême positif,
    normalisé par le volume total de la fenêtre."""
    prints = [_print(1, 5000.0, 10, "SELL"), _print(2, 4999.0, 10, "SELL"),   # jambe descendante
              _print(3, 4999.5, 30, "BUY"), _print(4, 5000.0, 10, "BUY")]     # rejet
    s = _snap(prints=prints)
    assert s.rejection_delta_ratio == pytest.approx(40 / 60)   # (30+10) net acheteur / 60 total


def test_B3_rejet_du_HAUT_est_negatif():
    prints = [_print(1, 5000.0, 10, "BUY"), _print(2, 5001.0, 10, "BUY"),
              _print(3, 5000.5, 30, "SELL"), _print(4, 5000.0, 10, "SELL")]
    s = _snap(prints=prints)
    assert s.rejection_delta_ratio == pytest.approx(-40 / 60)


def test_B3_NORMALISE_le_meme_delta_pese_moins_dans_un_flux_plus_gros():
    petit = [_print(1, 4999.0, 10, "SELL"), _print(2, 5000.0, 20, "BUY")]
    gros = [_print(1, 4999.0, 10, "SELL"), _print(2, 5000.0, 20, "BUY"),
            _print(3, 5000.0, 30, "BUY"), _print(4, 5000.0, 30, "SELL")]
    r_petit = _snap(prints=petit).rejection_delta_ratio
    r_gros = _snap(prints=gros).rejection_delta_ratio
    assert r_petit > r_gros > 0                              # même rejet, flux plus dense → dilué


def test_B3_borne_dans_moins_un_plus_un():
    prints = [_print(1, 4999.0, 5, "SELL")] + [_print(2 + i, 5000.0, 100, "BUY") for i in range(5)]
    r = _snap(prints=prints).rejection_delta_ratio
    assert -1.0 <= r <= 1.0


def test_B3_repli_depuis_le_PLUS_HAUT_est_un_rejet_du_haut():
    """Un tape qui vend depuis son plus-haut EST un rejet du haut : ratio négatif. (Mon test
    initial attendait `None` en invoquant « pas de jambe de rejet » — c'était mon attente qui
    était fausse : l'extrême retenu est ici le plus-haut, et la jambe existe.)"""
    prints = [_print(1, 5000.0, 10, "SELL"), _print(2, 4999.0, 10, "SELL")]
    assert _snap(prints=prints).rejection_delta_ratio == pytest.approx(-0.5)


def test_B3_extreme_choisi_selon_le_chemin_PARCOURU_depuis_lui():
    """Quand le prix finit haut, c'est le plus-BAS qui a été rejeté ; quand il finit bas, c'est le
    plus-HAUT. Sans cette règle, le signe serait arbitraire dès qu'il y a un haut et un bas."""
    monte = [_print(1, 4999.0, 10, "SELL"), _print(2, 5001.0, 30, "BUY")]
    assert _snap(prints=monte).rejection_delta_ratio > 0
    descend = [_print(1, 5001.0, 10, "BUY"), _print(2, 4999.0, 30, "SELL")]
    assert _snap(prints=descend).rejection_delta_ratio < 0


def test_B3_exige_la_MEME_couverture_de_cote_que_B2():
    """Sur un tape dont le côté agresseur est inconnu, le delta vaut 0 — et 0 se lirait comme
    « rejet neutre OBSERVÉ » alors que rien n'a été observé. Trouvé par la matrice de dégradation
    de l'essai : B3 restait « mesurée » là où B2 tombait, sur exactement les mêmes prints."""
    prints = [_print(1, 5000.0, 10, "?"), _print(2, 4999.0, 10, "?"),
              _print(3, 5000.0, 30, "?")]
    s = _snap(prints=prints)
    assert s.rejection_delta_ratio is None
    assert any("B3" in m and "côté" in m for m in s.missing)


def test_B3_couverture_PARTIELLE_mais_suffisante_reste_calculee():
    """Le seuil n'est pas « tout ou rien » : au-dessus de la couverture minimale, la mesure
    reste valable (les prints sans côté comptent dans le volume, donc diluent honnêtement)."""
    prints = [_print(1, 4999.0, 90, "SELL"), _print(2, 5000.0, 90, "BUY"),
              _print(3, 5000.0, 20, "?")]                  # 90 % de couverture
    assert _snap(prints=prints).rejection_delta_ratio is not None


def test_B3_prix_plat_rend_None():
    """Aucun extrême distinguable : tous les prints au même prix."""
    prints = [_print(1, 5000.0, 10, "BUY"), _print(2, 5000.0, 10, "SELL")]
    assert _snap(prints=prints).rejection_delta_ratio is None


# =============================================================================================
# B4 — vitesse d'agression post-sweep (postSweepAggressionRatio)
# =============================================================================================

def test_B4_mesure_une_ACCELERATION_de_debit():
    """Les débits se mesurent sur les DEUX moitiés de la fenêtre d'analyse, pas sur l'écart entre
    prints (qu'un seul print ancien suffirait à fausser). Fenêtre 10 s, sweep à T0, `now` = T0+2 :
    avant = 8 s, après = 2 s. 80 lots avant → 10/s ; 200 lots après → 100/s → ×10."""
    prints = [_print(-4, 5000.0, 80, "SELL"), _print(1, 5000.0, 200, "BUY")]
    s = _snap(now=T0 + 2.0, window_s=10.0, prints=prints, sweep={"ts": T0})
    assert s.post_sweep_aggression_ratio == pytest.approx(10.0)


def test_B4_sans_sweep_rend_None():
    s = _snap(prints=[_print(1, 5000.0, 10, "BUY")])
    assert s.post_sweep_aggression_ratio is None
    assert any("B4" in m for m in s.missing)


def test_B4_sans_volume_AVANT_rend_None():
    """Diviser par un débit nul donnerait « ∞ » ou un nombre géant : la porte n'est pas calculable."""
    s = _snap(now=T0 + 5.0, prints=[_print(1, 5000.0, 10, "BUY")], sweep={"ts": T0})
    assert s.post_sweep_aggression_ratio is None


def test_B4_sweep_HORS_FENETRE_rend_None():
    s = _snap(prints=[_print(-2, 5000.0, 10, "BUY")],
              sweep={"ts": T0 - config.ORDERFLOW_WINDOW_S - 60})
    assert s.post_sweep_aggression_ratio is None


def test_B4_sweep_sans_horodatage_utilisable_rend_None():
    for bad in ({"ts": math.nan}, {"ts": None}, {}, {"ts": T0 + 999}, "sweep"):
        assert _snap(prints=[_print(-2, 5000.0, 10, "BUY")],
                     sweep=bad).post_sweep_aggression_ratio is None, bad


# =============================================================================================
# Profil de volume — DÉLÉGUÉ au moteur D-041 (pas de second VPOC dans le terminal)
# =============================================================================================

def test_profil_delegue_au_moteur_existant_et_coherent_avec_les_prints():
    prints = [_print(1, 5000.00, 10, "BUY"), _print(2, 5000.25, 40, "BUY"),
              _print(3, 5000.25, 20, "SELL"), _print(4, 5000.50, 5, "SELL")]
    vp = _snap(prints=prints).volume_profile
    assert vp is not None
    assert vp["poc"] == pytest.approx(5000.25)               # 60 lots, le plus gros niveau
    assert vp["total_volume"] == pytest.approx(75)
    by_price = {lvl["price"]: lvl for lvl in vp["levels"]}
    assert by_price[5000.25]["buy"] == pytest.approx(40)     # split acheteur conservé


def test_profil_sans_prints_rend_None():
    assert _snap(prints=[]).volume_profile is None


# =============================================================================================
# ATR 5 / 14
# =============================================================================================

def _bars(n, high=10.0, low=9.0, close=9.5):
    return [{"high": high, "low": low, "close": close} for _ in range(n)]


def test_ATR_valeur_exacte_sur_barres_connues():
    """TR = max(H−L, |H−C_prev|, |L−C_prev|). Barres constantes H=10 L=9 C=9,5 → TR = 1 partout."""
    s = _snap(bars=_bars(20))
    assert s.atr_5 == pytest.approx(1.0) and s.atr_14 == pytest.approx(1.0)


def test_ATR_prend_en_compte_les_GAPS_via_la_cloture_precedente():
    bars = [{"high": 10.0, "low": 9.0, "close": 9.5},
            {"high": 20.0, "low": 19.0, "close": 19.5}]      # gap : TR = |20 − 9,5| = 10,5
    s = _snap(bars=bars, atr_fast=1, atr_slow=1)
    assert s.atr_5 == pytest.approx(10.5)


def test_ATR_barres_INSUFFISANTES_rend_None():
    """Un ATR 14 calculé sur 6 barres n'est pas un ATR 14 : c'est un autre indicateur qui porte
    un nom faux."""
    s = _snap(bars=_bars(6))
    assert s.atr_5 is not None and s.atr_14 is None
    assert any("ATR" in m for m in s.missing)


def test_ATR_barre_CORROMPUE_invalide_la_serie():
    """Écarter une barre au milieu recollerait deux barres non adjacentes : le TR calculé sur ce
    faux voisinage serait inventé. Série cassée → ATR non calculé."""
    bars = _bars(20)
    bars[10] = {"high": math.nan, "low": 9.0, "close": 9.5}
    s = _snap(bars=bars)
    assert s.atr_14 is None and any("ATR" in m for m in s.missing)


def test_ATR_incoherence_haut_bas_rejetee():
    bars = _bars(20)
    bars[5] = {"high": 8.0, "low": 12.0, "close": 9.5}       # high < low : carnet/barre corrompue
    assert _snap(bars=bars).atr_14 is None


# =============================================================================================
# Snapshot global — fail-closed, bornes, pureté
# =============================================================================================

def test_snapshot_VIDE_ne_leve_pas_et_dit_ce_qui_manque():
    s = _snap()
    assert isinstance(s, OrderFlowSnapshot)
    assert (s.wall_refill_ratio, s.tape_aggressor_buy_fraction,
            s.rejection_delta_ratio, s.post_sweep_aggression_ratio) == (None, None, None, None)
    assert s.volume_profile is None and s.atr_5 is None and s.atr_14 is None
    # `missing` est la valeur ajoutée : sans lui, quatre `None` ne disent pas POURQUOI.
    codes = {m.split(":")[0] for m in s.missing}
    assert {"B1", "B2", "B3", "B4"} <= codes
    assert any(m.startswith("ATR(") for m in s.missing)   # le motif porte la période demandée


def test_entrees_inexploitables_ne_LEVENT_jamais():
    for bad in (None, "prints", 42, [None, {}, {"ts": "x"}], [[]]):
        s = _snap(prints=bad, books=bad, bars=bad)
        assert isinstance(s, OrderFlowSnapshot), bad


def test_horloge_non_finie_rend_un_snapshot_ENTIEREMENT_vide():
    for bad in (math.nan, math.inf, None, "now"):
        s = _snap(now=bad)
        assert s.missing and s.tape_aggressor_buy_fraction is None, bad


def test_flux_OBESE_borne_sans_exploser():
    """Doctrine D-050 : au-delà de la borne, on ne consomme pas le lot entier. Le calcul reste
    fait sur les prints les plus RÉCENTS (les plus pertinents en microstructure)."""
    huge = [_print(-i * 0.001, 5000.0, 1, "BUY") for i in range(config.ORDERFLOW_MAX_PRINTS + 500)]
    s = _snap(prints=huge)
    assert s.prints_used <= config.ORDERFLOW_MAX_PRINTS


def test_fonction_PURE_aucune_lecture_d_horloge():
    """Règle commune D-045/047/050/052 : `now` est injecté, jamais lu."""
    import inspect

    from app.orderflow import calculator
    src = inspect.getsource(calculator)
    for banned in ("time.time", "datetime", "perf_counter", "monotonic"):
        assert banned not in src, banned


def test_snapshot_est_IMMUABLE():
    s = _snap()
    with pytest.raises(Exception):
        s.wall_refill_ratio = 1.0            # type: ignore[misc]


# =============================================================================================
# /devil (Loop 4) — cinq façons de faire mentir le calculateur
# =============================================================================================

def test_devil_carnet_CROISE_invalide_la_mesure_du_mur():
    """Bid ≥ ask : le carnet est corrompu (pathologie réelle, déjà détectée ailleurs sous
    CROSSED_BOOK). Mesurer un rechargement de mur dessus produirait un nombre plausible à partir
    d'une donnée fausse — la pire des sorties."""
    croise = [{"ts": T0 + t, "bids": [[5000.25, size]], "asks": [[5000.00, 40]]}
              for t, size in ((0, 100), (5, 20), (10, 80))]
    s = _snap(books=croise, wall_price=5000.25, wall_side="BID")
    assert s.wall_refill_ratio is None
    assert any("B1" in m and "crois" in m.lower() for m in s.missing)


def test_devil_un_seul_snapshot_SAIN_parmi_des_croises_ne_suffit_pas():
    books = [{"ts": T0, "bids": [[4999.75, 100]], "asks": [[5000.25, 40]]},          # sain
             {"ts": T0 + 5, "bids": [[5000.50, 20]], "asks": [[5000.00, 40]]}]       # croisé
    assert _snap(books=books, wall_price=4999.75,
                 wall_side="BID").wall_refill_ratio is None


def test_devil_volume_DERISOIRE_n_est_pas_une_mesure():
    """« 100 % acheteur » sur un seul lot n'est pas un flux acheteur : c'est du bruit présenté
    comme une mesure. Sous le volume minimal, B2 et B3 ne sont pas calculés."""
    s = _snap(prints=[_print(1, 5000.0, 1, "BUY")])
    assert s.tape_aggressor_buy_fraction is None
    assert s.rejection_delta_ratio is None
    assert any("volume" in m for m in s.missing)


def test_devil_volume_juste_au_dessus_du_plancher_est_mesure():
    n = config.ORDERFLOW_MIN_VOLUME
    s = _snap(prints=[_print(1, 4999.0, n, "SELL"), _print(2, 5000.0, n, "BUY")])
    assert s.tape_aggressor_buy_fraction == 0.5


def test_devil_valeurs_GEANTES_ne_produisent_jamais_NaN_ni_inf():
    """Des tailles à 1e308 débordent en `inf`, et inf/inf = NaN : une porte publierait alors
    « nan » comme s'il s'agissait d'un ratio. Toute grandeur non finie est retirée."""
    huge = [_print(1, 5000.0, 1e308, "BUY"), _print(2, 4999.0, 1e308, "SELL"),
            _print(3, 5000.0, 1e308, "BUY")]
    s = _snap(prints=huge, sweep={"ts": T0 + 15})
    for value in (s.tape_aggressor_buy_fraction, s.rejection_delta_ratio,
                  s.post_sweep_aggression_ratio, s.wall_refill_ratio):
        assert value is None or math.isfinite(value)


def test_devil_volume_qui_DEBORDE_ne_produit_AUCUNE_mesure():
    """Le filet de finitude sur le RÉSULTAT ne suffit pas : quand le volume total déborde en
    `inf`, `delta / inf` vaut 0,0 — fini, donc publié, et lu comme « rejet neutre observé ».
    C'est un zéro fabriqué par débordement. Trouvé en relisant la sortie de l'essai."""
    huge = [_print(1, 5000.0, 1e308, "BUY"), _print(2, 4999.0, 1e308, "SELL"),
            _print(3, 5000.0, 1e308, "BUY"), _print(4, 5001.0, 1e308, "SELL")]
    s = _snap(prints=huge, sweep={"ts": T0 + 20})
    assert s.tape_aggressor_buy_fraction is None
    assert s.rejection_delta_ratio is None
    assert s.post_sweep_aggression_ratio is None
    assert any("non fini" in m for m in s.missing)


def test_devil_carnet_a_tailles_geantes_ne_publie_pas_inf():
    books = [_book(0, [[4999.75, 1e308]], [[5000.25, 1]]),
             _book(5, [[4999.75, 1.0]], [[5000.25, 1]]),
             _book(10, [[4999.75, 1e308]], [[5000.25, 1]])]
    r = _snap(books=books, wall_price=4999.75, wall_side="BID").wall_refill_ratio
    assert r is None or math.isfinite(r)


def test_devil_B3_double_touche_la_jambe_part_de_la_DERNIERE():
    """Double creux : le rejet commence quand le prix quitte l'extrême POUR DE BON. Partir de la
    première touche ferait compter la vente du second creux comme du rejet acheteur."""
    prints = [_print(1, 5000.0, 10, "SELL"),
              _print(2, 4999.0, 10, "SELL"),      # 1re touche du bas
              _print(3, 4999.5, 10, "BUY"),
              _print(4, 4999.0, 40, "SELL"),      # 2e touche du bas — vente
              _print(5, 5000.0, 30, "BUY")]       # LE rejet
    s = _snap(prints=prints)
    assert s.rejection_delta_ratio == pytest.approx(30 / 100)   # seule la vraie jambe compte


def test_devil_fenetre_ABSURDE_rend_un_snapshot_MOTIVE_pas_un_silence():
    """`window_s` à 0 ou non fini (config cassée) viderait la fenêtre et rendrait quatre `None`
    sans cause visible : un snapshot muet ressemble à un marché calme."""
    for bad in (0.0, -5.0, math.nan, math.inf):
        s = _snap(window_s=bad, prints=[_print(1, 5000.0, 100, "BUY")])
        assert s.tape_aggressor_buy_fraction is None
        assert any("fenêtre" in m for m in s.missing), bad


# =============================================================================================
# /devil (2e passe) — ce que la première passe n'avait pas regardé
# =============================================================================================

def test_devil2_tick_INVALIDE_ne_publie_pas_un_profil_vide_mais_present():
    """`build_volume_profile` rend un objet VIDE (et non `None`) quand le tick est absurde. Publié
    tel quel, ce profil se lit « connecté mais sans volume » — exactement le mensonge refusé en
    D-053. Un tick invalide ne dégrade pas le profil : il l'empêche."""
    prints = [_print(1, 5000.0, 50, "BUY"), _print(2, 5000.25, 50, "SELL")]
    # `None` n'est PAS dans la liste : c'est le « non fourni » documenté de l'API, qui retombe
    # sur `config.PRICE_TICK`. L'y mettre testerait le contraire de ce qu'on veut.
    for bad in (0.0, -0.25, math.nan, math.inf, "0.25"):
        s = _snap(prints=prints, tick=bad)
        assert s.volume_profile is None, bad
        assert any("tick" in m for m in s.missing), bad


def test_devil2_carnets_DESORDONNES_sont_remis_en_ordre():
    """Les prints étaient triés, pas les carnets : `sizes[0]` et `sizes[-1]` étaient donc la
    PREMIÈRE et la DERNIÈRE reçues, pas la plus ancienne et la plus récente. Deux tampons
    concaténés (ou un feed qui double-livre) suffisaient à mesurer entre les mauvaises bornes."""
    ordonne = [_book(0, [[4999.75, 100]], []), _book(5, [[4999.75, 20]], []),
               _book(10, [[4999.75, 80]], [])]
    melange = [ordonne[2], ordonne[0], ordonne[1]]
    a = _snap(books=ordonne, wall_price=4999.75, wall_side="BID").wall_refill_ratio
    b = _snap(books=melange, wall_price=4999.75, wall_side="BID").wall_refill_ratio
    assert a == pytest.approx(0.75) and b == pytest.approx(a)


def test_devil2_prints_DUPLIQUES_ne_comptent_pas_deux_fois():
    """Rejeu de flux ou fenêtres qui se chevauchent : le même print livré deux fois gonfle les
    volumes (donc B3, B4 et le profil). Dédup sur `seq` — l'identifiant EXPLICITE du flux."""
    p1 = {**_print(1, 5000.0, 60, "BUY"), "seq": 101}
    p2 = {**_print(2, 4999.0, 40, "SELL"), "seq": 102}
    simple = _snap(prints=[p1, p2])
    double = _snap(prints=[p1, p2, dict(p1), dict(p2)])
    assert double.prints_used == simple.prints_used == 2
    assert double.volume_profile["total_volume"] == pytest.approx(100)


def test_devil2_prints_identiques_SANS_seq_sont_CONSERVES():
    """Sans identifiant, deux prints identiques sont indiscernables d'un vrai double passage au
    même prix — ce qui arrive tout le temps. Dédupliquer « au contenu » effacerait du volume RÉEL."""
    p = _print(1, 5000.0, 60, "BUY")
    s = _snap(prints=[dict(p), dict(p)])
    assert s.prints_used == 2 and s.volume_profile["total_volume"] == pytest.approx(120)


def test_devil2_B4_refuse_une_fenetre_de_quelques_MILLISECONDES():
    """Un débit mesuré sur 1 ms n'est pas un débit : c'est du bruit multiplié par mille. Sous le
    plancher de durée, la porte n'est pas calculée."""
    prints = [_print(-5, 5000.0, 100, "SELL"), _print(-0.0005, 5000.0, 30, "BUY")]
    s = _snap(now=T0, prints=prints, sweep={"ts": T0 - 0.001})
    assert s.post_sweep_aggression_ratio is None
    assert any("B4" in m and "durée" in m for m in s.missing)


def test_devil2_B4_reste_calculee_au_dessus_du_plancher_de_duree():
    span = config.ORDERFLOW_MIN_SPAN_S
    prints = [_print(-3 * span, 5000.0, 100, "SELL"), _print(-span / 2, 5000.0, 100, "BUY")]
    s = _snap(now=T0, window_s=6 * span, prints=prints, sweep={"ts": T0 - span})
    assert s.post_sweep_aggression_ratio is not None


def test_devil2_TOUS_les_prints_dates_du_futur_dit_POURQUOI():
    """Erreur de câblage classique : le `now` passé au calculateur est en retard sur le flux. Le
    motif « volume sous le plancher » enverrait chercher au mauvais endroit."""
    s = _snap(prints=[_print(+10, 5000.0, 100, "BUY"), _print(+20, 5000.0, 100, "SELL")],
              now=T0)
    assert s.prints_dropped == 2 and s.prints_used == 0
    # Le motif dit « postérieur(s) à `now` » — plus précis que « futur », et il NOMME la cause
    # probable (l'horloge d'appel). L'assertion suit le message réel, pas celui que j'imaginais.
    assert any("postérieur" in m and "horloge" in m for m in s.missing)
