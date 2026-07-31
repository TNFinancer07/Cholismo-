"""Feature — câblage du calculateur order flow dans le moteur LSR (D-056).

Ce câblage touche le **chemin d'émission live**. La propriété la plus importante n'est donc pas
« les mesures in-house marchent » (D-055 l'a prouvé) mais **« rien ne change tant qu'on ne l'a
pas demandé »** : en mode `source` (défaut), `evaluate_lsr` doit produire EXACTEMENT le même plan,
que le snapshot in-house soit fourni ou non. Un câblage qui modifie le comportement sans qu'on
l'ait demandé est un bug, pas une amélioration.

B3 et B4 ne sont PAS des portes ici : les transformer en critères de rejet ajouterait des refus
sur des seuils non calibrés. Ils sont mesurés et exposés — la décision de les faire gater est
séparée, et documentée comme telle.
"""
import math

from app import config
from app.lsr_engine import LsrInputs, evaluate_lsr
from app.orderflow import OrderFlowSnapshot

T0 = 1_700_000_000.0


def _book(best_bid=4999.75, best_ask=5000.25, size=400):
    return {"bids": [[best_bid - k * 0.25, size] for k in range(5)],
            "asks": [[best_ask + k * 0.25, size] for k in range(5)]}


def _prints(low=4999.00, n=6):
    return [{"ts": T0 - 5 + i * 0.5, "price": low + i * 0.25, "size": 30,
             "side": "BUY", "seq": i} for i in range(n)]


def _snapshot(**over):
    kw = dict(now=T0, window_s=30.0, wall_refill_ratio=0.9,
              tape_aggressor_buy_fraction=0.8, rejection_delta_ratio=0.5,
              post_sweep_aggression_ratio=3.0)
    kw.update(over)
    return OrderFlowSnapshot(**kw)


def _inputs(**over):
    kw = dict(now=T0, sweep_ts=T0 - 2, sweep_direction="BID_SWEEP", prints=_prints(),
              absorption=True, aggressor_ratio=0.8, book=_book(), vpoc=5002.0)
    kw.update(over)
    return LsrInputs(**kw)


# --- LA propriété de sûreté : le défaut ne change RIEN --------------------------------------

def test_mode_SOURCE_par_defaut_le_plan_est_INCHANGE():
    """Avec ou sans snapshot in-house attaché, le mode par défaut produit le même plan — au
    champ près. C'est le test qui autorise à livrer ce câblage sans risquer le chemin live."""
    sans = evaluate_lsr(_inputs())
    avec = evaluate_lsr(_inputs(orderflow=_snapshot()))
    assert sans is not None and avec == sans


def test_mode_SOURCE_ignore_des_mesures_in_house_CONTRADICTOIRES():
    """Un snapshot in-house qui refuserait tout ne doit pas influencer le mode source : sinon la
    bascule serait implicite, donc invisible."""
    hostile = _snapshot(wall_refill_ratio=0.0, tape_aggressor_buy_fraction=0.0)
    assert evaluate_lsr(_inputs(orderflow=hostile)) is not None


def test_le_defaut_de_config_est_bien_SOURCE():
    """Garde-fou : si ce défaut basculait, tout le dépôt changerait de comportement en silence."""
    assert config.LSR_ORDERFLOW_SOURCE == "source"


# --- Mode inhouse : les portes lisent les mesures maison -------------------------------------

def test_mode_INHOUSE_B2_lit_la_mesure_MAISON_pas_le_proxy():
    """Proxy source à 0,05 (refuserait) mais mesure maison à 0,80 (accepte) : en inhouse, c'est
    la mesure maison qui décide. Sans ce test, on ne saurait pas laquelle a parlé."""
    i = _inputs(aggressor_ratio=0.05, orderflow=_snapshot(tape_aggressor_buy_fraction=0.8),
                orderflow_source="inhouse")
    assert evaluate_lsr(i) is not None


def test_mode_INHOUSE_B2_rejette_quand_la_mesure_maison_refuse():
    i = _inputs(aggressor_ratio=0.99, orderflow=_snapshot(tape_aggressor_buy_fraction=0.10),
                orderflow_source="inhouse")
    assert evaluate_lsr(i) is None


def test_mode_INHOUSE_B1_utilise_le_RECHARGEMENT_du_mur():
    au_dessus = _snapshot(wall_refill_ratio=config.LSR_B1_REFILL_MIN + 0.1)
    en_dessous = _snapshot(wall_refill_ratio=config.LSR_B1_REFILL_MIN - 0.1)
    assert evaluate_lsr(_inputs(orderflow=au_dessus, orderflow_source="inhouse")) is not None
    assert evaluate_lsr(_inputs(orderflow=en_dessous, orderflow_source="inhouse")) is None


def test_mode_INHOUSE_B1_ignore_l_absorption_du_fournisseur():
    """`absorption=False` ne doit plus rien bloquer quand c'est la mesure maison qui fait foi —
    sinon les deux sources gateraient EN MÊME TEMPS, ce que personne n'a demandé."""
    i = _inputs(absorption=False, orderflow=_snapshot(), orderflow_source="inhouse")
    assert evaluate_lsr(i) is not None


def test_mode_INHOUSE_mesure_ABSENTE_rejette_fail_closed():
    """Une porte non calculable n'est pas une porte ouverte (§3). C'est la différence entre
    « le mur a tenu » et « on n'a pas pu regarder »."""
    for absent in ({"wall_refill_ratio": None}, {"tape_aggressor_buy_fraction": None}):
        i = _inputs(orderflow=_snapshot(**absent), orderflow_source="inhouse")
        assert evaluate_lsr(i) is None, absent


def test_mode_INHOUSE_sans_snapshot_du_tout_rejette():
    """Mode maison demandé mais calculateur non alimenté : on ne retombe PAS silencieusement sur
    les proxys — ce serait la bascule implicite qu'on refuse, à l'envers."""
    assert evaluate_lsr(_inputs(orderflow=None, orderflow_source="inhouse")) is None


def test_mode_INHOUSE_borne_la_fraction_comme_le_mode_source():
    """La corruption ne devient jamais un signal, quelle que soit la source de la mesure."""
    for bad in (1.7, -0.2, math.nan):
        i = _inputs(orderflow=_snapshot(tape_aggressor_buy_fraction=bad),
                    orderflow_source="inhouse")
        assert evaluate_lsr(i) is None, bad


def test_source_INCONNUE_rejette_plutot_que_de_deviner():
    i = _inputs(orderflow=_snapshot(), orderflow_source="maison")
    assert evaluate_lsr(i) is None


# --- B3/B4 mesurés, jamais gatants dans cette tranche ----------------------------------------

def test_B3_et_B4_ne_BLOQUENT_pas_en_inhouse():
    """Les rendre gatants ajouterait des rejets sur des seuils non calibrés. Décision séparée,
    assumée : ils sont mesurés et exposés, pas appliqués."""
    hostile = _snapshot(rejection_delta_ratio=-0.9, post_sweep_aggression_ratio=0.01)
    assert evaluate_lsr(_inputs(orderflow=hostile, orderflow_source="inhouse")) is not None


def test_la_source_est_relue_AU_MOMENT_DE_L_APPEL_pas_a_l_import():
    """Bug trouvé par l'essai, invisible en test unitaire : `orderflow_source: str =
    config.LSR_ORDERFLOW_SOURCE` fige le défaut à l'IMPORT du module. Toute bascule au runtime
    (variable d'environnement relue, réglage event-sourcé, essai) restait donc sans effet — le
    moteur jurait « [source] » en mode maison. La source se résout à l'APPEL."""
    original = config.LSR_ORDERFLOW_SOURCE
    try:
        config.LSR_ORDERFLOW_SOURCE = "inhouse"
        hostile = _snapshot(wall_refill_ratio=0.0)      # mur non rechargé → maison refuse
        assert evaluate_lsr(_inputs(orderflow=hostile)) is None
        config.LSR_ORDERFLOW_SOURCE = "source"
        assert evaluate_lsr(_inputs(orderflow=hostile)) is not None   # proxy accepte
    finally:
        config.LSR_ORDERFLOW_SOURCE = original


def test_le_motif_d_emission_NOMME_la_source_qui_a_parle():
    """Sans ça, deux manifestes identiques à l'écran auraient été décidés par deux moteurs
    différents — et personne ne pourrait le savoir après coup."""
    original = config.LSR_ORDERFLOW_SOURCE
    try:
        config.LSR_ORDERFLOW_SOURCE = "inhouse"
        plan = evaluate_lsr(_inputs(orderflow=_snapshot(), absorption=False))
        assert plan is not None and "[inhouse]" in plan["reason"] and "mur rechargé" in plan["reason"]
        config.LSR_ORDERFLOW_SOURCE = "source"
        plan = evaluate_lsr(_inputs())
        assert "[source]" in plan["reason"] and "absorption" in plan["reason"]
    finally:
        config.LSR_ORDERFLOW_SOURCE = original
