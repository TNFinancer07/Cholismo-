"""Feature — calibration PAR INSTRUMENT du moteur LSR (D-069).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- la calibration microstructure vit dans `app.lsr_tuning`, pas en scalaires `config.LSR_*` —
  MES et MNQ n'ont ni la même densité de carnet ni la même vitesse ;
- `tuning()` / `spec()` FAIL-CLOSED sur instrument inconnu : `None`, jamais un repli sur MES ;
- `evaluate_lsr` résout la table à L'APPEL (pas à l'import) et refuse d'émettre sans elle ;
- les seuils MES du moteur de référence s'appliquent VRAIMENT : 1 tick de spread max, mur
  rechargé à 0.40 — deux valeurs que le Python relâchait (2 ticks, 0.50).
"""
import time

import pytest

from app import config, lsr_tuning
from app.lsr_engine import LsrInputs, evaluate_lsr

T = config.PRICE_TICK


# --- La table elle-même ---------------------------------------------------------------------

def test_les_deux_instruments_sont_calibres_DIFFEREMMENT():
    """Si MES et MNQ portaient les mêmes nombres, la table ne servirait à rien : elle existe
    parce que le carnet du Nasdaq est plus fin et son mouvement plus rapide."""
    mes, mnq = lsr_tuning.tuning("MES"), lsr_tuning.tuning("MNQ")
    assert mes is not None and mnq is not None
    assert mnq.f4_min_cumulative_depth < mes.f4_min_cumulative_depth   # carnet plus fin
    assert mnq.f4_max_spread_ticks > mes.f4_max_spread_ticks           # spread plus large
    assert mnq.tp_max_ticks > mes.tp_max_ticks                         # mouvement plus ample
    assert mnq.sl_noise_buffer_max_ticks > mes.sl_noise_buffer_max_ticks
    # …mais les gates order flow sont des FRACTIONS de flux, pas des distances : elles ne
    # dépendent pas de la densité du carnet et restent identiques (comme dans le moteur TS).
    assert mnq.b1_min_wall_refill_ratio == mes.b1_min_wall_refill_ratio


def test_un_instrument_INCONNU_ne_retombe_JAMAIS_sur_MES():
    """Le piège : un repli silencieux ferait évaluer MNQ aux seuils MES (150 de profondeur sur
    un carnet qui en porte 60 → jamais d'émission) sans qu'aucun message ne le dise."""
    for absent in ("ES", "NQ", "mes", "", None, "MES "):
        assert lsr_tuning.tuning(absent) is None, absent
        assert lsr_tuning.spec(absent) is None, absent


def test_linstrument_de_config_par_DEFAUT_est_calibre():
    """Garde-fou de cohérence : `LSR_INSTRUMENT` doit désigner une ligne de la table, sinon le
    moteur est muet au démarrage sans que rien ne l'annonce."""
    assert lsr_tuning.tuning(config.LSR_INSTRUMENT) is not None


# --- Câblage dans le moteur ------------------------------------------------------------------

def _book(bid=4999.75, ask=5000.0, depth=70.0, n=3):
    """Carnet MES RÉALISTE : meilleur bid et meilleur ask à 1 tick l'un de l'autre."""
    return {"bids": [[bid - T * k, depth] for k in range(n)],
            "asks": [[ask + T * k, depth] for k in range(n)]}


def _inputs(**over) -> LsrInputs:
    now = time.time()
    base = dict(now=now, sweep_ts=now - 5.0, sweep_direction="BID_SWEEP",
                prints=[{"ts": now - 1.5 + 0.15 * k, "price": 5000.0 if k else 4998.0,
                         "size": 3.0, "side": "SELL", "seq": k} for k in range(9)],
                absorption=True, aggressor_ratio=0.70, book=_book(), vpoc=5000.0)
    base.update(over)
    return LsrInputs(**base)


def test_un_instrument_INCONNU_rend_le_moteur_MUET():
    """Fail-closed jusqu'au bout : sans calibration, pas de géométrie — donc pas de plan."""
    assert evaluate_lsr(_inputs()) is not None            # témoin : le reste est au vert
    assert evaluate_lsr(_inputs(instrument="ES")) is None


def test_MES_refuse_desormais_un_spread_de_2_ticks():
    """Valeur du moteur de référence (`f4MaxSpreadTicks: 1`). Le Python tolérait 2 ticks parce
    que le MOCK en émettait 2 — on a corrigé le mock, pas relâché le seuil."""
    assert evaluate_lsr(_inputs(book=_book(ask=5000.25))) is None      # 2 ticks → rejet
    assert evaluate_lsr(_inputs(book=_book(ask=5000.0))) is not None   # 1 tick → passe


def test_MNQ_tolere_le_spread_que_MES_refuse():
    """La table sert précisément à ça : la même donnée, deux verdicts, parce que les deux
    carnets ne se ressemblent pas."""
    livre = _book(ask=5000.25, depth=25.0)          # 2 ticks, top-3 = 75 par côté
    assert evaluate_lsr(_inputs(book=livre, instrument="MES")) is None
    assert evaluate_lsr(_inputs(book=livre, instrument="MNQ")) is not None


def test_MNQ_applique_sa_PROPRE_profondeur_plancher():
    """Un carnet de 20 par niveau (top-3 = 60) est pile au plancher MNQ et très loin du MES."""
    maigre = _book(ask=5000.25, depth=20.0)
    assert evaluate_lsr(_inputs(book=maigre, instrument="MNQ")) is not None
    assert evaluate_lsr(_inputs(book=_book(ask=5000.25, depth=19.0),
                                instrument="MNQ")) is None


def test_le_seuil_B1_du_moteur_de_reference_sapplique(monkeypatch):
    """`b1MinWallRefillRatio: 0.40` — le Python exigeait 0.50, donc refusait des murs que le
    moteur de référence valide. Divergence de seuil = divergence de trades pris."""
    monkeypatch.setattr(config, "LSR_ORDERFLOW_SOURCE", "inhouse")

    class _Snap:
        def __init__(self, refill):
            self.wall_refill_ratio = refill
            self.tape_aggressor_buy_fraction = 0.70

    assert evaluate_lsr(_inputs(orderflow=_Snap(0.45))) is not None   # ≥ 0.40 → passe
    assert evaluate_lsr(_inputs(orderflow=_Snap(0.35))) is None       # < 0.40 → rejet


def test_la_geometrie_MNQ_utilise_les_bornes_MNQ():
    """TP plafond 8 ticks sur MNQ contre 5 sur MES : sur un VPOC lointain, le TP MNQ va PLUS
    loin. Un scalaire unique rendrait les deux plans identiques — donc l'un des deux faux."""
    loin = _inputs(vpoc=5020.0, book=_book(ask=5000.25, depth=70.0))
    mes = evaluate_lsr(_inputs(vpoc=5020.0))               # MES exige 1 tick de spread
    mnq = evaluate_lsr(loin.model_copy(update={"instrument": "MNQ"}))
    assert mes is not None and mnq is not None
    entree_mes, entree_mnq = mes["executionPlan"]["entryPrice"], mnq["executionPlan"]["entryPrice"]
    assert mes["executionPlan"]["takeProfit"] - entree_mes == pytest.approx(5 * T)
    assert mnq["executionPlan"]["takeProfit"] - entree_mnq == pytest.approx(8 * T)


def test_aucune_grandeur_par_instrument_ne_SURVIT_dans_config():
    """Anti-régression du motif qu'on corrige : la même valeur écrite à deux endroits finit
    par diverger au premier retouchage d'un seul côté. Après D-069 il n'y a qu'UNE table."""
    survivants = [n for n in ("LSR_F4_MAX_SPREAD_TICKS", "LSR_F4_MIN_DEPTH",
                              "LSR_ENTRY_OFFSET_TICKS", "LSR_SL_BUFFER_TICKS",
                              "LSR_TP_MIN_TICKS", "LSR_TP_MAX_TICKS",
                              "LSR_TP_VPOC_MARGIN_TICKS", "LSR_B2_FLIP", "LSR_B1_REFILL_MIN")
                  if hasattr(config, n)]
    assert survivants == [], f"doublons de calibration restés dans config.py : {survivants}"


def test_un_instrument_mal_configure_est_ANNONCE_au_demarrage(caplog):
    """/devil — le fail-closed silencieux est le pire des deux mondes : le moteur n'émet plus
    rien et ressemble à un moteur calme. Une faute de frappe dans l'environnement doit se lire
    dans les logs de démarrage, pas se déduire d'une absence de manifestes."""
    import asyncio
    import logging

    from app.datasource.mock import MockDataSource
    from app.engine import Engine
    from app.redis_state import RedisState

    async def _demarre():
        moteur = Engine(RedisState(), MockDataSource())
        await moteur.start()
        await moteur.stop()

    original = config.LSR_INSTRUMENT
    try:
        config.LSR_INSTRUMENT = "SPX"                    # inexistant dans la table
        with caplog.at_level(logging.ERROR, logger="cholismo.engine"):
            asyncio.run(_demarre())
        assert "SPX" in caplog.text                      # nomme le coupable…
        assert "MES" in caplog.text and "MNQ" in caplog.text   # …ET ce qui est admis
    finally:
        config.LSR_INSTRUMENT = original
