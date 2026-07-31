"""Feature — pont ContextSchema → OrderFlowSnapshot (D-056).

Le calculateur (D-055) prend des ticks bruts ; le moteur, lui, vit sur le ContextSchema. Ce pont
fait la jonction — et c'est là que se cachent les erreurs d'ALIMENTATION : un mur cherché du
mauvais côté, un carnet périmé consommé comme frais, un historique qui grossit sans borne.

Le pont est PUR : il ne lit pas l'horloge et ne garde rien. L'historique de carnet, lui, est
détenu par l'Engine (le schéma ne porte que le carnet COURANT).
"""
import math

import pytest

from app import config
from app.orderflow.bridge import book_history_push, snapshot_for_lsr


T0 = 1_700_000_000.0


class _Meta:
    def __init__(self, value, freshness="FRESH"):
        self.value = value
        self.freshness = freshness


class _Schema:
    """Double minimal du ContextSchema — seuls les champs que le pont lit."""
    class _S1:
        def __init__(self, tape, book):
            self.tape = tape
            self.order_book = book
    def __init__(self, tape=None, book=None):
        self.s1_state = self._S1(_Meta(tape or []), _Meta(book))


def _prints(n=6, low=4999.0):
    return [{"ts": T0 - 5 + i * 0.5, "price": low + i * 0.25, "size": 40,
             "side": "BUY", "seq": i} for i in range(n)]


def _book(size=300):
    return {"bids": [[4999.75 - k * 0.25, size] for k in range(5)],
            "asks": [[5000.25 + k * 0.25, size] for k in range(5)]}


# --- côté du mur : l'erreur qui inverserait toute la mesure ----------------------------------

def test_BID_SWEEP_cherche_le_mur_du_cote_BID_a_l_extreme_BAS():
    """Un bid balayé : le mur attaqué est un mur ACHETEUR, au plus-bas de la fenêtre. Le chercher
    à l'ask mesurerait la défense de l'autre camp — un contresens complet."""
    hist = [{"ts": T0 - 3, **_book(400)}, {"ts": T0 - 1, **_book(120)}, {"ts": T0, **_book(350)}]
    s = snapshot_for_lsr(_Schema(tape=_prints(), book=_book()), hist, now=T0,
                         sweep_ts=T0 - 2, sweep_direction="BID_SWEEP")
    assert s.wall_refill_ratio is not None            # mesuré côté bid
    assert not any("mur" in m for m in s.missing)


def test_ASK_SWEEP_cherche_le_mur_du_cote_ASK():
    hist = [{"ts": T0 - 3, **_book(400)}, {"ts": T0 - 1, **_book(120)}, {"ts": T0, **_book(350)}]
    s = snapshot_for_lsr(_Schema(tape=_prints(), book=_book()), hist, now=T0,
                         sweep_ts=T0 - 2, sweep_direction="ASK_SWEEP")
    assert s.wall_refill_ratio is not None


def test_sans_direction_de_sweep_aucun_mur_n_est_DESIGNE():
    """Pas de sweep orienté → aucun niveau de référence. En choisir un « au hasard » (le meilleur
    bid, par exemple) mesurerait une défense que personne n'a attaquée."""
    hist = [{"ts": T0 - 3, **_book(400)}, {"ts": T0, **_book(350)}]
    s = snapshot_for_lsr(_Schema(tape=_prints(), book=_book()), hist, now=T0,
                         sweep_ts=None, sweep_direction=None)
    assert s.wall_refill_ratio is None
    assert any("B1" in m for m in s.missing)


# --- fraîcheur : un tape périmé n'alimente rien ----------------------------------------------

def test_tape_PERIME_ne_nourrit_pas_le_calculateur():
    """Même doctrine que `build_lsr_inputs` : FRESH seulement. Un tape périmé produirait des
    mesures d'order flow parfaitement calculées sur un marché qui n'existe plus."""
    schema = _Schema(tape=_prints(), book=_book())
    schema.s1_state.tape = _Meta(_prints(), freshness="STALE")
    s = snapshot_for_lsr(schema, [], now=T0, sweep_ts=T0 - 2, sweep_direction="BID_SWEEP")
    assert s.tape_aggressor_buy_fraction is None
    assert s.prints_used == 0


def test_schema_vide_ne_leve_pas():
    s = snapshot_for_lsr(_Schema(), [], now=T0, sweep_ts=None, sweep_direction=None)
    assert s.prints_used == 0 and s.missing


def test_pont_PUR_aucune_lecture_d_horloge():
    import inspect

    from app.orderflow import bridge
    src = inspect.getsource(bridge)
    for banned in ("time.time", "datetime", "perf_counter", "monotonic"):
        assert banned not in src, banned


# --- historique de carnet : borné, frais, ordonné --------------------------------------------

def test_historique_BORNE_et_ordonne():
    """Sans borne, une session de six heures à 4 Hz garderait 86 400 carnets en mémoire."""
    hist: list = []
    for k in range(config.BOOK_HISTORY_MAX + 50):
        book_history_push(hist, _Meta(_book()), ts=T0 + k)
    assert len(hist) == config.BOOK_HISTORY_MAX
    assert [b["ts"] for b in hist] == sorted(b["ts"] for b in hist)
    assert hist[-1]["ts"] == T0 + config.BOOK_HISTORY_MAX + 49    # les RÉCENTS sont gardés


def test_historique_refuse_le_carnet_NON_FRESH_ou_malforme():
    hist: list = []
    book_history_push(hist, _Meta(_book(), freshness="STALE"), ts=T0)
    book_history_push(hist, _Meta(None), ts=T0 + 1)
    book_history_push(hist, _Meta("cassé"), ts=T0 + 2)
    book_history_push(hist, None, ts=T0 + 3)
    book_history_push(hist, _Meta(_book()), ts=math.nan)
    assert hist == []                                  # rien d'inexploitable n'entre
    book_history_push(hist, _Meta(_book()), ts=T0 + 4)
    assert len(hist) == 1


# --- comparaison OMBRE : la preuve avant la bascule ------------------------------------------

def test_ombre_expose_les_deux_valeurs_ET_les_deux_verdicts():
    """Comparer les VALEURS ne suffit pas : ce qui compte est de savoir si l'écart change une
    DÉCISION. L'ombre porte donc les deux verdicts de porte, calculés avec la règle du moteur."""
    from app.orderflow.bridge import orderflow_shadow
    from app.orderflow import OrderFlowSnapshot

    class _OF:
        absorption = _Meta(True)
        aggressor_ratio = _Meta(0.82)
    class _Sweep:
        triggered = True
        class alert:
            direction = "BID_SWEEP"
    schema = _Schema(tape=_prints(), book=_book())
    schema.s1_state.order_flow = _OF()
    schema.liquidity_sweep = _Sweep()

    snap = OrderFlowSnapshot(now=T0, window_s=30.0, wall_refill_ratio=0.9,
                             tape_aggressor_buy_fraction=0.30,
                             rejection_delta_ratio=0.4, post_sweep_aggression_ratio=2.0)
    sh = orderflow_shadow(schema, snap)
    assert sh["b2"]["source"] == 0.82 and sh["b2"]["inhouse"] == 0.30
    assert sh["b2"]["delta"] == pytest.approx(0.52)
    # LE point : les deux sources ne rendent PAS le même verdict — c'est ce désaccord qu'on veut
    # voir s'accumuler (ou disparaître) avant d'oser basculer.
    assert sh["b2"]["verdict_source"] is True and sh["b2"]["verdict_inhouse"] is False
    assert sh["b2"]["agree"] is False
    assert sh["b1"]["verdict_source"] is True and sh["b1"]["verdict_inhouse"] is True
    assert sh["b3"] == 0.4 and sh["b4"] == 2.0            # mesurés, non gatants


def test_ombre_sans_direction_ne_rend_AUCUN_verdict():
    """Sans sweep orienté, la porte B2 n'a pas de sens : rendre un verdict serait inventer une
    comparaison que le moteur ne fait pas."""
    from app.orderflow.bridge import orderflow_shadow
    from app.orderflow import OrderFlowSnapshot

    schema = _Schema(tape=_prints(), book=_book())
    schema.s1_state.order_flow = type("OF", (), {"absorption": _Meta(True),
                                                 "aggressor_ratio": _Meta(0.8)})()
    sh = orderflow_shadow(schema, OrderFlowSnapshot(now=T0, window_s=30.0,
                                                    tape_aggressor_buy_fraction=0.9))
    assert sh["b2"]["verdict_source"] is None and sh["b2"]["agree"] is None


def test_ombre_ne_LEVE_jamais_meme_sur_un_schema_absurde():
    """Un défaut d'OBSERVATION ne doit pas casser la boucle qu'il observe."""
    from app.orderflow.bridge import orderflow_shadow
    from app.orderflow import OrderFlowSnapshot
    sh = orderflow_shadow(object(), OrderFlowSnapshot(now=T0, window_s=30.0))
    assert isinstance(sh, dict) and "source" in sh
