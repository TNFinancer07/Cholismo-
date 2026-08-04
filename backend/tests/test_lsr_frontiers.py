"""Feature — frontières de compte, F2 coupe-circuit du jour, F3-ATR (D-071).

Port de `lsr-engine/src/frontiers.ts` + des deux gates que le Python n'avait PAS. Comportement
figé AVANT implémentation (Loop 1 étape 3).

**La divergence trouvée en portant `frontiers.ts`** — elle ne figurait dans aucune liste :
`compute_buffer` fait `equity − (day_start − DLL)`. Sur une matinée GAGNANTE, ce terme dépasse le
DLL (il y ajoute le profit du jour), alors que la référence plafonne l'allocation quotidienne au
DLL quoi qu'il arrive. Concrètement, à +500 $ sur un Apex 50K, le Python autorisait **50 % de
risque en plus** que le moteur de référence sur le trade suivant. On retient la lecture bornée.

F2 et F3-ATR sont deux refus que le Python ne savait pas prononcer :
- **F2** : au-delà de 80 % de la frontière du jour CONSOMMÉE, la séance est finie. Sans cette
  règle, on continue à trader avec 200 $ de marge sur 1 000 — le sizer accepte, la discipline non.
- **F3-ATR** : volatilité en expansion anormale (`atr_rapide > 1.5 × atr_lent`) → refus. Et ATR
  MANQUANT → refus AUSSI (fail-closed) : la référence est explicite là-dessus, et c'est le seul
  choix cohérent avec §3.
"""
import math

import pytest

from app.lsr_engine import LsrInputs, evaluate_lsr
from app.lsr_frontiers import (F2_CIRCUIT_THRESHOLD, F3_ATR_MULTIPLIER, derive_account_frontiers,
                               f2_daily_circuit_breaker, f3_atr_blocked)
from app.risk_sizer import (APEX_EOD_50K, apex_eod_account, compute_buffer, size_plan,
                            size_position)

T = 0.25
CALME = 12.0


def _acc(equity=50_000.0, day_start=50_000.0):
    return apex_eod_account(APEX_EOD_50K, current_equity=equity, day_start_equity=day_start)


# --- 1. Frontières du jour : port de frontiers.ts ---------------------------------------------

def test_a_louverture_la_frontiere_du_jour_est_le_DLL():
    """Apex 50K neuf : 2 500 jusqu'au plancher, mais 1 000 de DLL — c'est le DLL qui contraint."""
    f = derive_account_frontiers(_acc())
    assert f.perte_jour == 0.0
    assert f.frontiere_jour_initiale == 1_000.0
    assert f.frontiere_jour_restante == 1_000.0


def test_apres_une_perte_la_frontiere_RESTANTE_se_reduit_dautant():
    f = derive_account_frontiers(_acc(equity=49_500.0))
    assert f.perte_jour == 500.0
    assert f.frontiere_jour_initiale == 1_000.0     # l'INITIALE ne bouge pas de la journée
    assert f.frontiere_jour_restante == 500.0


def test_LA_DIVERGENCE_une_matinee_gagnante_ne_donne_PAS_droit_a_plus_de_risque():
    """Le cœur de D-071. À +500 $, `compute_buffer` rendait 1 500 (DLL + profit) ; la référence
    plafonne l'allocation du jour au DLL. 1 500/5 = 300 $ de risque contre 1 000/5 = 200 $ :
    le Python prenait 50 % de plus après une bonne matinée, exactement quand on se croit bon."""
    gagnant = _acc(equity=50_500.0)
    assert compute_buffer(gagnant) == 1_500.0                    # ancienne lecture, non bornée
    f = derive_account_frontiers(gagnant)
    assert f.perte_jour == 0.0                                   # un gain n'est pas une perte
    assert f.frontiere_jour_restante == 1_000.0                  # bornée au DLL


def test_le_sizer_dimensionne_desormais_sur_la_frontiere_BORNEE():
    """Vérification par le nombre de contrats, pas par la formule : stop 2 ticks MES = 2.50 $."""
    gagnant = _acc(equity=50_500.0)
    r = size_position(gagnant, stop_distance_ticks=2, tick_value=1.25, vix=CALME)
    assert r.risk_allowed == 200.0 and r.contracts == 80         # 1 000/5, PAS 1 500/5 = 300


def test_le_plancher_de_campagne_reprend_la_main_quand_il_est_PLUS_PROCHE():
    """Fin de campagne : 100 $ jusqu'au plancher, 1 000 de DLL encore disponibles. C'est le
    plancher qui compte — franchir le DLL pause la journée, franchir le plancher tue le compte."""
    f = derive_account_frontiers(_acc(equity=47_600.0, day_start=47_600.0))
    assert f.frontiere_jour_restante == 100.0


def test_un_compte_EN_BREACH_rend_une_frontiere_NULLE_jamais_negative():
    """Port fidèle : `max(0, …)`. Une frontière négative n'existe pas — sous le plancher, il ne
    reste rien à risquer, et surtout pas « moins que rien »."""
    f = derive_account_frontiers(_acc(equity=47_000.0, day_start=50_000.0))
    assert f.frontiere_jour_restante == 0.0
    assert f.perte_jour == 3_000.0


def test_INVARIANT_buffer_dAFFICHAGE_et_frontiere_saccordent_sur_le_VERDICT():
    """Les deux nombres coexistent volontairement : `compute_buffer` est SIGNÉ (un −500 dit à
    l'opérateur qu'il est PASSÉ SOUS la ligne, là où un 0 dirait « pile dessus »), la frontière
    est bornée pour le sizing. Ce qu'ils ne doivent JAMAIS faire, c'est se contredire sur la
    question « reste-t-il de quoi trader ? »."""
    for equity in (52_000.0, 50_000.0, 49_500.0, 47_600.0, 47_500.0, 47_000.0, 40_000.0):
        for day_start in (50_000.0, 48_000.0):
            a = _acc(equity=equity, day_start=day_start)
            assert (compute_buffer(a) > 0) == (derive_account_frontiers(a).frontiere_jour_restante
                                               > 0), (equity, day_start)


# --- 2. F2 — coupe-circuit du jour ------------------------------------------------------------

def test_F2_laisse_passer_tant_que_la_consommation_reste_sous_le_seuil():
    assert f2_daily_circuit_breaker(derive_account_frontiers(_acc())) is None
    assert f2_daily_circuit_breaker(derive_account_frontiers(_acc(equity=49_500.0))) is None


def test_F2_coupe_a_80_pourcent_de_la_frontiere_du_jour():
    """1 000 de frontière initiale → 800 $ perdus = 80 % → coupé. Le seuil est ATTEINT, pas
    dépassé : `>=`, comme la référence."""
    assert f2_daily_circuit_breaker(derive_account_frontiers(_acc(equity=49_201.0))) is None
    r = f2_daily_circuit_breaker(derive_account_frontiers(_acc(equity=49_200.0)))
    assert r == "F2_DAILY_CIRCUIT_BREAKER"


def test_F2_coupe_aussi_quand_la_frontiere_INITIALE_est_deja_nulle():
    """Journée commencée SOUS le plancher : il n'y a pas de « 80 % de zéro » à calculer, il y a
    juste une séance qui n'aurait pas dû s'ouvrir."""
    mort = _acc(equity=47_000.0, day_start=47_000.0)
    assert f2_daily_circuit_breaker(derive_account_frontiers(mort)) == "F2_DAILY_CIRCUIT_BREAKER"


def test_le_seuil_F2_est_bien_celui_du_moteur_de_reference():
    assert F2_CIRCUIT_THRESHOLD == 0.8


# --- 3. F3-ATR — expansion anormale de volatilité ---------------------------------------------

@pytest.mark.parametrize("rapide, lent, bloque", [
    (1.0, 1.0, False),        # régime stable
    (1.49, 1.0, False),       # expansion tolérée
    (1.5, 1.0, False),        # PILE au multiple : `>` strict, comme la référence
    (1.51, 1.0, True),        # au-delà → refus
    (3.0, 1.0, True),
    (0.5, 1.0, False),        # contraction : jamais bloquante
])
def test_F3_ATR_bloque_au_dela_du_multiple(rapide, lent, bloque):
    assert f3_atr_blocked(rapide, lent) is bloque


def test_F3_ATR_bloque_quand_lATR_MANQUE_fail_closed():
    """Le piège exact : `None > None` est faux en TS comme en Python — un ATR absent passerait
    donc la gate SANS être mesuré. La référence traite explicitement ce cas en BLOCAGE, et c'est
    le seul choix compatible avec « no signal without data » (§3)."""
    for rapide, lent in ((None, 1.0), (1.0, None), (None, None), (math.nan, 1.0),
                         (1.0, math.inf), (0.0, 1.0), (1.0, 0.0), (-1.0, 1.0)):
        assert f3_atr_blocked(rapide, lent) is True, (rapide, lent)


def test_le_multiplicateur_F3_est_bien_celui_du_moteur_de_reference():
    assert F3_ATR_MULTIPLIER == 1.5


# --- 4. Câblage : les deux gates REFUSENT vraiment une émission --------------------------------

def _book(depth=70.0):
    return {"bids": [[4999.75 - T * k, depth] for k in range(3)],
            "asks": [[5000.0 + T * k, depth] for k in range(3)]}


class _Snap:
    def __init__(self, rapide=1.0, lent=1.0):
        self.wall_refill_ratio = 0.9
        self.tape_aggressor_buy_fraction = 0.70
        self.atr_fast, self.atr_slow = rapide, lent


def _inputs(**over) -> LsrInputs:
    now = 1_700_000_000.0
    base = dict(now=now, sweep_ts=now - 5.0, sweep_direction="BID_SWEEP",
                prints=[{"ts": now - 1.5 + 0.15 * k, "price": 5000.0 if k else 4998.0,
                         "size": 3.0, "side": "SELL", "seq": k} for k in range(9)],
                absorption=True, aggressor_ratio=0.70, book=_book(), vpoc=5010.0,
                orderflow=_Snap())
    base.update(over)
    return LsrInputs(**base)


def test_F3_ATR_est_PORTEE_mais_PAS_ENCORE_CABLEE_et_on_dit_pourquoi():
    """Refus argumenté, mesuré plutôt que supposé.

    La règle est écrite et testée ci-dessus. Elle n'est PAS branchée dans `evaluate_lsr`, parce
    que Cholismo **n'a pas d'ATR à lui donner** : le tampon de prints du footprint est borné à
    `FOOTPRINT_MAX_PRINTS` (800 ≈ 80 s de tape), et un ATR-14 sur bougies de 60 s réclame 15
    bougies, soit ~14 minutes d'historique continu. Mesure sur 400 ticks du stack de démo :
    **1 bougie produite, 0 ATR calculable, 100 % des snapshots bloqués**.

    Brancher la gate maintenant rendrait le moteur définitivement muet — un fail-closed qui ne
    protège de rien puisqu'il refuse TOUT. Ce qui manque n'est pas la règle, c'est une SOURCE
    d'ATR (historique OHLC borné, indépendant du tampon d'affichage). Tranche séparée.

    Ce test EXISTE pour que le jour où l'ATR arrive, il tombe en échec et rappelle de câbler."""
    from app import config

    bougies_requises = config.ORDERFLOW_ATR_SLOW + 1
    prints_par_bougie = config.FOOTPRINT_CANDLE_SECONDS * 10        # ~10 prints/s, cadence mock
    assert config.FOOTPRINT_MAX_PRINTS < bougies_requises * prints_par_bougie, (
        "le tampon de prints suffit désormais à un ATR-14 : câbler `f3_atr_blocked` dans "
        "`evaluate_lsr` et remplacer ce test par celui du comportement de la gate")
    # …et en attendant, un ATR absurde ne change RIEN au verdict : la gate n'est pas branchée.
    assert evaluate_lsr(_inputs(orderflow=_Snap(3.0, 1.0))) is not None
    assert evaluate_lsr(_inputs(orderflow=None)) is not None


def test_F2_empeche_le_TICKET_meme_quand_le_setup_est_parfait():
    """F2 vit dans la couche COMPTE, pas dans la microstructure : le plan existe, le ticket non."""
    plan = evaluate_lsr(_inputs())
    assert plan is not None
    assert size_plan(plan, _acc(equity=49_500.0), vix=CALME) is not None    # 50 % consommés
    assert size_plan(plan, _acc(equity=49_200.0), vix=CALME) is None        # 80 % → coupé
