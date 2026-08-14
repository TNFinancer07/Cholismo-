"""Feature — modificateur VIX du sizing + buffer de bruit A3 DYNAMIQUE (D-070).

Deux divergences numériques avec le moteur de référence (`lsr-engine/src`), figées ici AVANT
implémentation (Loop 1 étape 3) :

1. **Le modificateur VIX n'existait PAS dans le chemin de sizing Python.** `computeRiskSize`
   fait `floor(contrats_bruts × mult_VIX)` ; `size_position` ne le faisait pas du tout — donc
   taille pleine à VIX 28, là où la référence coupe de moitié. Et à VIX **exactement 20.00**, la
   borne diffère : `< 20 → 0.75` côté TS, `<= 20 → 0.75` côté Python (`sony.py`). On retient la
   lecture la plus SERRÉE (0.50), cohérente avec le fail-closed par défaut (§2.4).

2. **Le buffer de bruit A3 était FIXE à 2 ticks.** La référence le calcule :
   `min(max_ticks, max(min_ticks, ceil(spread)) + (atr_rapide > atr_lent ? 1 : 0))` — un stop
   qui ne tient pas compte du spread se fait sortir par le bruit qu'il est censé absorber.
"""
import math

import pytest

from app import lsr_tuning
from app.lsr_engine import LsrInputs, evaluate_lsr, noise_buffer_ticks
from app.lsr_tuning import MES_TUNING as MES
from app.lsr_tuning import MNQ_TUNING as MNQ
from app.risk_sizer import APEX_EOD_50K, apex_eod_account, size_position

T = 0.25


# --- 1. Modificateur VIX ---------------------------------------------------------------------

@pytest.mark.parametrize("vix, attendu", [
    (0.0, 1.0), (9.99, 1.0), (14.99, 1.0),
    (15.0, 0.75), (17.5, 0.75), (19.99, 0.75),
    (20.0, 0.50),                       # LA borne : le moteur de référence bascule ICI
    (25.0, 0.50), (30.0, 0.50),
    (30.01, 0.0), (75.0, 0.0),          # au-delà du blocage dur F3 : plus de taille du tout
])
def test_les_paliers_VIX_suivent_le_moteur_de_reference(vix, attendu):
    assert lsr_tuning.vix_multiplier(vix) == attendu


def test_un_VIX_ABSENT_ou_corrompu_ne_vaut_JAMAIS_taille_pleine():
    """§3 — « no signal without data ». Un VIX qu'on ne voit pas n'est pas un VIX calme : le
    multiplicateur tombe à 0, donc le sizer refuse. Le piège inverse (absent → 1.0) donnerait la
    taille MAXIMALE exactement quand on est le plus aveugle."""
    for aveugle in (None, math.nan, math.inf, -math.inf, "20", True):
        assert lsr_tuning.vix_multiplier(aveugle) == 0.0, aveugle


def test_le_sizer_APPLIQUE_le_modificateur_VIX():
    """Comptage réel sur Apex 50K à l'ouverture : buffer 1000, risque min(500, 200) = 200,
    stop 2 ticks × 1.25 $ = 2.50 $/contrat → 80 contrats bruts."""
    compte = apex_eod_account(APEX_EOD_50K)
    brut = size_position(compte, stop_distance_ticks=2, tick_value=1.25, vix=12.0)
    assert brut.status == "APPROVED" and brut.contracts == 80 and brut.vix_multiplier == 1.0
    for vix, mult, attendu in ((17.0, 0.75, 60), (25.0, 0.50, 40), (20.0, 0.50, 40)):
        r = size_position(compte, stop_distance_ticks=2, tick_value=1.25, vix=vix)
        assert (r.contracts, r.vix_multiplier) == (attendu, mult), vix


def test_au_dessus_du_blocage_dur_le_sizer_REFUSE_plutot_que_de_rendre_zero():
    """Un « ordre de 0 contrat » n'existe pas (§3) : au-delà de VIX 30 le sizer rejette, avec un
    motif qui NOMME la volatilité — sinon l'opérateur chercherait un problème de buffer."""
    compte = apex_eod_account(APEX_EOD_50K)
    r = size_position(compte, stop_distance_ticks=2, tick_value=1.25, vix=42.0)
    assert r.status == "REJECTED" and r.reason == "VIX_SUSPENDED" and r.contracts is None


def test_le_modificateur_VIX_ne_peut_pas_ARRONDIR_VERS_LE_HAUT():
    """`floor`, comme la référence : 3 contrats bruts × 0.75 = 2.25 → 2, jamais 3."""
    compte = apex_eod_account(APEX_EOD_50K)
    # stop 50 ticks × 1.25 = 62.50 $/contrat → floor(200 / 62.5) = 3 bruts
    r = size_position(compte, stop_distance_ticks=50, tick_value=1.25, vix=16.0)
    assert r.contracts == 2


# --- 2. Buffer de bruit A3 dynamique ---------------------------------------------------------

@pytest.mark.parametrize("spread, rapide, lent, attendu", [
    (1.0, 1.0, 2.0, 1),      # marché serré, ATR en contraction → plancher MES
    (1.0, 2.0, 1.0, 2),      # expansion de volatilité → +1 tick, plafonné à 2
    (2.0, 1.0, 2.0, 2),      # spread de 2 ticks → le stop doit au moins l'absorber
    (1.4, 1.0, 2.0, 2),      # ceil(1.4) = 2 : on arrondit VERS LE HAUT, jamais vers le bas
    (5.0, 1.0, 2.0, 2),      # spread énorme → plafonné au max (F4 aura déjà refusé avant)
    (0.2, 1.0, 2.0, 1),      # sous 1 tick → le plancher reprend la main
])
def test_le_buffer_suit_la_formule_de_reference(spread, rapide, lent, attendu):
    assert noise_buffer_ticks(spread, rapide, lent, MES) == attendu


def test_les_bornes_MNQ_sont_PLUS_LARGES_que_celles_de_MES():
    """Même marché calme, deux instruments : le Nasdaq bouge plus, son plancher de buffer est
    à 2 ticks contre 1. Un buffer unique serait trop serré sur MNQ ou trop lâche sur MES."""
    assert noise_buffer_ticks(1.0, 1.0, 2.0, MNQ) == 2
    assert noise_buffer_ticks(1.0, 2.0, 1.0, MNQ) == 3


def test_un_ATR_ABSENT_prend_le_buffer_le_PLUS_LARGE():
    """Fail-closed dans le bon sens : sans régime de volatilité observable, on suppose
    l'expansion. Un stop plus loin, c'est MOINS de contrats — jamais plus. L'erreur inverse
    (supposer le calme) resserrerait le stop pile quand on ne voit plus rien."""
    assert noise_buffer_ticks(1.0, None, None, MES) == 2
    assert noise_buffer_ticks(1.0, math.nan, 2.0, MES) == 2
    assert noise_buffer_ticks(1.0, 2.0, None, MES) == 2


def test_un_SPREAD_absent_prend_lui_aussi_le_buffer_le_plus_large():
    assert noise_buffer_ticks(None, 1.0, 2.0, MES) == 2
    assert noise_buffer_ticks(math.nan, 1.0, 2.0, MES) == 2


# --- 3. Câblage dans le moteur ---------------------------------------------------------------

def _book(bid=4999.75, ask=5000.0, depth=70.0):
    return {"bids": [[bid - T * k, depth] for k in range(3)],
            "asks": [[ask + T * k, depth] for k in range(3)]}


class _Snap:
    """Snapshot order flow minimal — seuls les ATR comptent ici."""
    def __init__(self, rapide, lent):
        self.wall_refill_ratio = 0.9
        self.tape_aggressor_buy_fraction = 0.70
        self.atr_fast, self.atr_slow = rapide, lent


def _inputs(**over) -> LsrInputs:
    now = 1_700_000_000.0
    base = dict(now=now, sweep_ts=now - 5.0, sweep_direction="BID_SWEEP",
                prints=[{"ts": now - 1.5 + 0.15 * k, "price": 5000.0 if k else 4998.0,
                         "size": 3.0, "side": "SELL", "seq": k} for k in range(9)],
                absorption=True, aggressor_ratio=0.70, book=_book(), vpoc=5010.0)
    base.update(over)
    return LsrInputs(**base)


def test_le_stop_se_RESSERRE_quand_la_volatilite_se_contracte():
    """Le comportement qui change vraiment : à ATR en contraction et spread de 1 tick, le stop
    passe de 2 ticks (ancienne constante) à 1. Même setup, deux géométries — et donc deux
    tailles de position."""
    calme = evaluate_lsr(_inputs(orderflow=_Snap(1.0, 2.0)))
    agite = evaluate_lsr(_inputs(orderflow=_Snap(2.0, 1.0)))
    assert calme is not None and agite is not None
    assert calme["executionPlan"]["stopLoss"] == 4998.0 - 1 * T
    assert agite["executionPlan"]["stopLoss"] == 4998.0 - 2 * T


def test_sans_snapshot_order_flow_le_stop_reste_au_PLUS_LARGE():
    """Comportement historique préservé quand la mesure manque : 2 ticks sur MES."""
    plan = evaluate_lsr(_inputs(orderflow=None))
    assert plan is not None and plan["executionPlan"]["stopLoss"] == 4998.0 - 2 * T


# --- 4. Le garde qui empêche la régression ---------------------------------------------------

def test_aucun_module_de_PRODUCTION_nappelle_size_position_sans_vix():
    """`size_position(vix=None)` = « je n'applique pas le modificateur de régime ». C'est
    légitime pour tester la règle du 1/5e isolément, jamais dans `app/` : ce serait la taille
    pleine à VIX 28. Le contrôle est syntaxique (AST) parce qu'un tel oubli ne casse AUCUN test
    existant — il rend juste des positions deux fois trop grosses, en silence."""
    import ast
    import pathlib

    coupables = []
    for chemin in sorted(pathlib.Path("app").rglob("*.py")):
        arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            nom = noeud.func.attr if isinstance(noeud.func, ast.Attribute) else \
                getattr(noeud.func, "id", None)
            if nom != "size_position":
                continue
            if not any(kw.arg == "vix" for kw in noeud.keywords):
                coupables.append(f"{chemin}:{noeud.lineno}")
    assert coupables == [], ("appels à size_position SANS `vix=` dans le code de "
                            f"production : {coupables}")


def test_le_chemin_dEMISSION_refuse_un_VIX_aveugle():
    """La propriété qui compte vraiment : `size_plan` est le seul chemin par lequel un ticket
    part. Sans VIX observable il rend None — pas un ticket à taille pleine."""
    from app.risk_sizer import size_plan

    plan = {"status": "APPROVED", "instrument": "MES", "direction": "LONG", "reason": "essai",
            "executionPlan": {"entryType": "LIMIT", "entryPrice": 5448.25, "stopLoss": 5447.5,
                              "takeProfit": 5449.5, "contracts": 1}}
    compte = apex_eod_account(APEX_EOD_50K)
    assert size_plan(plan, compte, vix=12.0) is not None
    for aveugle in (None, math.nan, math.inf, "12"):
        assert size_plan(plan, compte, vix=aveugle) is None, aveugle


# --- 5. Blackout news : DEUX verrous, pas un seul mal réglé ------------------------------------

def test_les_DEUX_blackouts_news_restent_INDEPENDANTS():
    """Divergence apparente avec le moteur de référence (`f5DefaultBlackout*Ms` = ±2 min) contre
    `MACRO_PAUSE_WINDOW_S = 900` (±15 min). Ce n'est PAS la même porte :

    - **±2 min** = porte F5 du moteur LSR. Côté Python c'est `NEWS_LOCK_BEFORE/AFTER_MIN`, qui
      produit `HARD_LOCK` et fait rejeter `evaluate_lsr`. **Déjà aligné, à la minute près.**
    - **±15 min** = règle Phase 0 `MACRO_BLACKOUT` de Cholismo (D-040), qui gèle le Go/No-Go
      HUMAIN. Elle est STRICTEMENT PLUS LARGE, donc plus prudente.

    La ramener à 2 min « pour aligner » rouvrirait 13 minutes de part et d'autre de chaque NFP —
    un DESSERRAGE de discipline déguisé en correction de parité. On garde les deux, et ce test
    interdit qu'on les confonde plus tard."""
    from app import config

    assert config.NEWS_LOCK_BEFORE_MIN == 2 and config.NEWS_LOCK_AFTER_MIN == 2   # F5 LSR
    assert config.MACRO_PAUSE_WINDOW_S == 900                                     # Phase 0
    assert config.MACRO_PAUSE_WINDOW_S > config.NEWS_LOCK_BEFORE_MIN * 60, (
        "la porte Phase 0 doit rester la PLUS LARGE des deux : c'est elle qui protège l'humain")


def test_la_porte_F5_du_moteur_LSR_bloque_bien_a_2_minutes():
    """Vérification par le COMPORTEMENT, pas par la constante : c'est `HARD_LOCK` qui rejette."""
    assert evaluate_lsr(_inputs(orderflow=_Snap(1.0, 2.0), news_state="HARD_LOCK")) is None
    assert evaluate_lsr(_inputs(orderflow=_Snap(1.0, 2.0), news_state="WARNING")) is not None
