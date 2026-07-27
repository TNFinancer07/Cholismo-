"""Feature — Couche Compte & RiskSizer (D-047, tranche 1).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- `AccountState` : état STATELESS du compte prop-firm EOD (equity, équité d'ouverture, plancher
  de drawdown — STATIQUE en intraday pour un EOD Trail —, DLL). Le modèle Apex « Intraday
  Trail » est NON-REPRÉSENTABLE par construction (F1 structurel : le type n'admet que EOD) ;
- `compute_buffer` : le capital tradable N'EST PAS l'équité — c'est la DISTANCE VERS LA MORT :
  `min(equity − floor, equity − (day_start − DLL))` ;
- `size_position` : règle stricte du 1/5e — risque alloué = buffer/5 ; contrats =
  floor(risque / (ticks_de_stop × valeur_tick)) ;
- F8 fail-closed : taille < 1 OU buffer ≤ 0 → `REJECTED / INSUFFICIENT_BUFFER`, JAMAIS une
  exception ; entrée corrompue → `REJECTED / INVALID_INPUT` ;
- fonction PURE : compte + géométrie en entrée, résultat en sortie, aucune horloge, aucun état.
"""
import math

import pytest
from pydantic import ValidationError

from app.risk_sizer import (
    APEX_EOD_50K,
    INSTRUMENT_SPECS,
    AccountState,
    apex_eod_account,
    compute_buffer,
    size_position,
)

MES_TICK_VALUE = INSTRUMENT_SPECS["MES"]["tick_value"]     # 1.25 $/tick


def _apex(equity=50_000.0, day_start=50_000.0) -> AccountState:
    return apex_eod_account(APEX_EOD_50K, current_equity=equity, day_start_equity=day_start)


# --- Preset Apex 50K EOD -------------------------------------------------------------------

def test_preset_apex_50k_construit_l_etat_attendu():
    acc = _apex()
    assert acc.account_type == "EOD_TRAILING"
    assert acc.current_equity == 50_000.0 and acc.day_start_equity == 50_000.0
    assert acc.drawdown_floor == 47_500.0                  # 50k − 2500
    assert acc.daily_loss_limit == 1_000.0


def test_modele_intraday_trail_non_representable_f1_structurel():
    with pytest.raises(ValidationError):
        AccountState(account_type="INTRADAY_TRAILING", current_equity=50_000.0,
                     day_start_equity=50_000.0, drawdown_floor=47_500.0,
                     daily_loss_limit=1_000.0)


# --- Buffer : la distance vers la mort ------------------------------------------------------

def test_buffer_en_ouverture_le_dll_est_la_frontiere_contraignante():
    # min(50000−47500, 50000−(50000−1000)) = min(2500, 1000) = 1000 — l'exemple exact du doc
    assert compute_buffer(_apex()) == 1_000.0


def test_buffer_pres_du_plancher_le_floor_devient_contraignant():
    # equity 47800, ouverture 48200 : min(47800−47500, 47800−47200) = min(300, 600) = 300
    assert compute_buffer(_apex(equity=47_800.0, day_start=48_200.0)) == 300.0


def test_buffer_negatif_apres_breach():
    assert compute_buffer(_apex(equity=48_900.0)) < 0      # perte du jour 1100 > DLL 1000


# --- Règle du 1/5e + dimensionnement --------------------------------------------------------

def test_taille_en_ouverture_regle_du_cinquieme():
    # buffer 1000 → risque 200 $ ; stop 8 ticks MES → 200 / (8×1.25=10) = 20 contrats
    r = size_position(_apex(), stop_distance_ticks=8, tick_value=MES_TICK_VALUE)
    assert r.status == "APPROVED" and r.contracts == 20
    assert r.buffer == 1_000.0 and r.risk_allowed == 200.0


def test_taille_arrondie_a_l_entier_inferieur():
    # stop 3 ticks → 200 / 3.75 = 53.33… → 53 (jamais arrondi vers le haut)
    r = size_position(_apex(), stop_distance_ticks=3, tick_value=MES_TICK_VALUE)
    assert r.contracts == 53


def test_pertes_successives_la_taille_decroit_jusqu_au_blocage_f8():
    """Le scénario demandé : Apex 50K, pertes successives → la taille fond MATHÉMATIQUEMENT
    (jamais ne remonte) jusqu'au coupe-circuit F8."""
    stop_ticks = 8                                          # 10 $/contrat sur MES
    sizes = []
    statuses = []
    for equity in (50_000.0, 49_600.0, 49_300.0, 49_100.0, 49_020.0, 49_001.0, 48_990.0):
        r = size_position(_apex(equity=equity), stop_distance_ticks=stop_ticks,
                          tick_value=MES_TICK_VALUE)
        statuses.append(r.status)
        sizes.append(r.contracts if r.contracts is not None else 0)
    # 50000→buffer 1000→20 ; 49600→600→12 ; 49300→300→6 ; 49100→100→2 ;
    # 49020→20→0 (F8) ; 49001→1→0 (F8) ; 48990→buffer<0 (F8)
    assert sizes == [20, 12, 6, 2, 0, 0, 0]
    assert statuses == ["APPROVED"] * 4 + ["REJECTED"] * 3
    assert all(a >= b for a, b in zip(sizes, sizes[1:]))    # décroissance monotone


def test_f8_taille_zero_rejette_insufficient_buffer():
    r = size_position(_apex(equity=49_020.0), stop_distance_ticks=8, tick_value=MES_TICK_VALUE)
    assert r.status == "REJECTED" and r.reason == "INSUFFICIENT_BUFFER"
    assert r.contracts is None                              # jamais un 0 déguisé en taille


def test_f8_buffer_nul_ou_negatif_rejette():
    for equity in (49_000.0, 48_500.0, 47_499.0):           # buffer 0, <0, sous le plancher
        r = size_position(_apex(equity=equity), stop_distance_ticks=8,
                          tick_value=MES_TICK_VALUE)
        assert r.status == "REJECTED" and r.reason == "INSUFFICIENT_BUFFER", equity


def test_frontiere_exacte_un_contrat():
    # buffer 100 → risque 20 $ ; stop 16 ticks (20 $) → exactement 1 contrat, approuvé
    r = size_position(_apex(equity=49_100.0), stop_distance_ticks=16, tick_value=MES_TICK_VALUE)
    assert r.status == "APPROVED" and r.contracts == 1
    # un cent de moins de risque → 0.99… contrat → F8
    r2 = size_position(_apex(equity=49_099.0), stop_distance_ticks=16, tick_value=MES_TICK_VALUE)
    assert r2.status == "REJECTED"


# --- Corruption d'entrée : REJECTED, jamais une exception -----------------------------------

def test_entrees_corrompues_invalid_input_zero_exception():
    acc = _apex()
    for bad_ticks in (0, -3, math.nan, math.inf, None):
        r = size_position(acc, stop_distance_ticks=bad_ticks, tick_value=MES_TICK_VALUE)
        assert r.status == "REJECTED" and r.reason == "INVALID_INPUT", bad_ticks
    for bad_tv in (0.0, -1.25, math.nan, None):
        r = size_position(acc, stop_distance_ticks=8, tick_value=bad_tv)
        assert r.status == "REJECTED" and r.reason == "INVALID_INPUT", bad_tv


def test_equite_non_finie_invalid_input():
    for bad in (math.nan, math.inf):
        acc = AccountState(account_type="EOD_TRAILING", current_equity=bad,
                           day_start_equity=50_000.0, drawdown_floor=47_500.0,
                           daily_loss_limit=1_000.0)
        r = size_position(acc, stop_distance_ticks=8, tick_value=MES_TICK_VALUE)
        assert r.status == "REJECTED" and r.reason == "INVALID_INPUT"


def test_purete_meme_entree_meme_resultat():
    acc = _apex(equity=49_300.0)
    a = size_position(acc, stop_distance_ticks=8, tick_value=MES_TICK_VALUE)
    b = size_position(acc, stop_distance_ticks=8, tick_value=MES_TICK_VALUE)
    assert a == b
    assert acc.current_equity == 49_300.0                   # jamais muté
