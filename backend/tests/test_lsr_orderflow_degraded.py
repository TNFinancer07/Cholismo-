"""Feature — câblage order flow sous conditions de marché DÉGRADÉES (D-056, passe /devil).

Deux réalités que le mock propre ne produit jamais :

1. **Le détecteur change d'avis.** Un sweep bascule BID → ASK en plein rechargement de mur. La
   mesure change alors de sujet SANS le dire : elle continue de calculer sur une fenêtre qui
   précède l'événement qu'elle prétend mesurer.
2. **Le flux se coupe.** Le tampon de carnets se remplit avant, se tait pendant, reprend après —
   et deux snapshots ADJACENTS dans la liste peuvent être séparés de trente secondes de cécité.
   Mesurer un rechargement « à travers » ce trou, c'est inférer une déplétion qu'on n'a pas vue.
"""
import math

import pytest

from app import config
from app.orderflow.bridge import book_history_push, snapshot_for_lsr
from app.orderflow.calculator import compute_snapshot

T0 = 1_700_000_000.0


class _Meta:
    def __init__(self, value, freshness="FRESH"):
        self.value, self.freshness = value, freshness


class _Schema:
    class _S1:
        def __init__(self, tape, book):
            self.tape, self.order_book = tape, book
    def __init__(self, tape=None, book=None):
        self.s1_state = self._S1(_Meta(tape or []), _Meta(book))


def _prints(low=4998.0, high=5002.0):
    """Un tape qui touche les DEUX extrêmes : le mur retenu dépendra donc de la direction."""
    return ([{"ts": T0 - 8 + i * 0.4, "price": low + i * 0.25, "size": 40, "side": "SELL",
              "seq": i} for i in range(6)]
            + [{"ts": T0 - 5 + i * 0.4, "price": high - i * 0.25, "size": 40, "side": "BUY",
                "seq": 100 + i} for i in range(6)])


def _books(times_sizes, wall_bid=4998.0, wall_ask=5002.0):
    return [{"ts": T0 + t,
             "bids": [[wall_bid, sz], [wall_bid - 0.25, 50]],
             "asks": [[wall_ask, sz], [wall_ask + 0.25, 50]]}
            for t, sz in times_sizes]


# =============================================================================================
# A. Sweeps chaotiques : le détecteur change d'avis en plein rechargement
# =============================================================================================

def test_A1_la_fenetre_de_mesure_DEMARRE_au_sweep_pas_30s_avant():
    """Sans borne basse, `consumed` se calcule depuis un carnet vieux de 30 s — donc AVANT
    l'événement. La mesure décrit alors une déplétion qui n'a rien à voir avec ce sweep."""
    hist = _books([(-25, 500), (-20, 60), (-2, 200), (-1, 120), (0, 180)])
    tot = snapshot_for_lsr(_Schema(tape=_prints(), book=None), hist, now=T0,
                           sweep_ts=T0 - 3, sweep_direction="BID_SWEEP").wall_refill_ratio
    # Depuis le sweep : 200 → 120 (consommé 80), revenu à 180 (rechargé 60) → 0,75.
    # Depuis −25 s : 500 → 60 → 180, soit 0,27 — une mesure de l'événement PRÉCÉDENT.
    assert tot == pytest.approx(0.75)


def test_A2_apres_un_FLIP_de_direction_rien_n_est_encore_observe():
    """Le sweep bascule à l'instant `now` : on n'a pas encore vu le nouveau mur se faire
    attaquer. Rendre une valeur ici, ce serait décrire le mur PRÉCÉDENT."""
    hist = _books([(-20, 400), (-10, 50), (-1, 300)])
    s = snapshot_for_lsr(_Schema(tape=_prints(), book=None), hist, now=T0,
                         sweep_ts=T0, sweep_direction="ASK_SWEEP")
    assert s.wall_refill_ratio is None
    assert any("B1" in m for m in s.missing)


def test_A3_le_mur_suit_la_DIRECTION_courante_pas_la_precedente():
    """BID_SWEEP → mur au plus-bas ; ASK_SWEEP → mur au plus-haut. Les tailles diffèrent aux deux
    niveaux : si la mesure ne changeait pas de côté, les deux directions donneraient le MÊME
    chiffre — le signe qu'on mesure toujours le mur d'avant."""
    hist = [{"ts": T0 - 5 + i, "bids": [[4998.0, b]], "asks": [[5002.0, a]]}
            for i, (b, a) in enumerate(((400, 100), (40, 90), (360, 95)))]
    schema = _Schema(tape=_prints(), book=None)
    bid = snapshot_for_lsr(schema, hist, now=T0, sweep_ts=T0 - 6,
                           sweep_direction="BID_SWEEP").wall_refill_ratio
    ask = snapshot_for_lsr(schema, hist, now=T0, sweep_ts=T0 - 6,
                           sweep_direction="ASK_SWEEP").wall_refill_ratio
    assert bid is not None and ask is not None and bid != ask


# =============================================================================================
# B. Le tampon de carnets face à une coupure de flux
# =============================================================================================

def test_B1_un_TROU_d_observation_interdit_la_mesure_de_rechargement():
    """Deux snapshots adjacents dans la liste, trente secondes de cécité entre les deux : la
    « déplétion » constatée n'a jamais été observée, elle est INFÉRÉE. Même faute que
    « hors profondeur ≠ taille nulle » (D-055) — un trou n'est pas une observation."""
    trou = config.ORDERFLOW_MAX_BOOK_GAP_S * 18                  # très au-delà du seuil
    hist = _books([(-2 - trou, 400), (-1.75 - trou, 380), (-2, 40), (0, 300)])
    s = compute_snapshot(now=T0, books=hist, window_s=60, tick=0.25,
                         wall_price=4998.0, wall_side="BID")
    assert s.wall_refill_ratio is None
    assert any("B1" in m and "trou" in m.lower() for m in s.missing)


def test_B2_une_cadence_normale_ne_declenche_PAS_le_garde():
    """Le carnet arrive à 4 Hz : des écarts de 0,25 s sont la normale, pas une coupure."""
    hist = _books([(-3 + i * 0.25, sz) for i, sz in
                   enumerate([400, 300, 200, 100, 60, 90, 150, 240, 320, 380, 400, 400])])
    s = compute_snapshot(now=T0, books=hist, window_s=30, tick=0.25,
                         wall_price=4998.0, wall_side="BID")
    assert s.wall_refill_ratio is not None


def test_B3_pendant_la_coupure_le_tampon_ne_grossit_PAS():
    """Source coupée → le carnet vieillit en STALE puis ABSENT ; rien ne doit entrer. Sinon on
    accumulerait des fossiles qui, plus tard, serviraient de « taille initiale »."""
    hist: list = []
    for i in range(5):                                    # flux sain
        book_history_push(hist, _Meta({"bids": [[4998.0, 300]], "asks": [[5002.0, 300]]}),
                          ts=T0 + i * 0.25)
    avant = len(hist)
    for i in range(40):                                   # coupure : plus rien n'est FRESH
        book_history_push(hist, _Meta({"bids": [[4998.0, 300]], "asks": [[5002.0, 300]]},
                                      freshness="STALE"), ts=T0 + 2 + i * 0.25)
    assert len(hist) == avant == 5


def test_B4_a_la_REPRISE_la_mesure_reste_refusee_tant_que_le_trou_est_dans_la_fenetre():
    """Le flux revient : on ne peut pas mesurer sur une fenêtre qui contient encore la cécité.
    Il faut attendre que le trou sorte de la fenêtre — c'est le prix de l'honnêteté."""
    # Le segment post-coupure doit contenir une VRAIE déplétion suivie d'un rechargement, sinon
    # le refus viendrait de « aucune déplétion » et le test ne prouverait rien sur le trou.
    hist = _books([(-20, 400), (-19, 380)]
                  + [(-1 + i * 0.25, sz) for i, sz in enumerate((300, 180, 80, 140, 220, 260))])
    s = compute_snapshot(now=T0 + 1, books=hist, window_s=30, tick=0.25,
                         wall_price=4998.0, wall_side="BID")
    assert s.wall_refill_ratio is None
    # …puis, une fois le trou hors fenêtre, la mesure repart sur des observations continues.
    s2 = compute_snapshot(now=T0 + 1, books=hist, window_s=3, tick=0.25,
                          wall_price=4998.0, wall_side="BID")
    assert s2.wall_refill_ratio is not None


def test_B5_un_carnet_du_FUTUR_n_entre_pas_dans_le_tampon():
    """Désync d'horloge source : un carnet postérieur à `now` fausserait l'ordre du tampon."""
    hist: list = []
    book_history_push(hist, _Meta({"bids": [[4998.0, 300]], "asks": [[5002.0, 300]]}), ts=math.inf)
    assert hist == []


# =============================================================================================
# C. L'horodatage d'événement — le défaut le plus grave de la passe
# =============================================================================================

def _engine_available() -> bool:
    import asyncio

    from app.redis_state import RedisState

    async def probe() -> bool:
        st = RedisState()
        try:
            return await st.ping()
        finally:
            await st.close()
    return asyncio.run(probe())


@pytest.mark.skipif(not _engine_available(), reason="Redis indisponible — intégration sautée")
def test_C1_l_horodatage_d_evenement_NE_GLISSE_PAS_avec_les_re_evaluations():
    """LE défaut : `alert.ts` est régénéré à CHAQUE évaluation d'une condition persistante
    (D-046). Passé tel quel au calculateur, `span_after ≈ 0` en permanence → **B4
    structurellement incalculable en production**, et la fenêtre B1 bornée à un instant qui
    glisse. L'Engine garde donc le PREMIER passage de l'événement."""
    import asyncio

    from app.datasource.mock import MockDataSource
    from app.engine import Engine
    from app.redis_state import RedisState
    from app.schema import LiquiditySweep, LiquiditySweepAlert

    async def scenario():
        state = RedisState()
        try:
            engine = Engine(MockDataSource(), state)
            base = 1_800_000_000.0
            vus = []
            for k in range(6):
                now = base + k                       # l'alerte est ré-horodatée à `now` à chaque tick
                engine.schema.liquidity_sweep = LiquiditySweep(
                    assessable=True, triggered=True, reason="t",
                    alert=LiquiditySweepAlert(ts=now, kind="LIQUIDITY_SWEEP",
                                              direction="BID_SWEEP", trigger="T", detail="t"))
                engine._maybe_emit_lsr(now)
                vus.append(engine._sweep_event_ts)
            assert vus == [base] * 6                 # STABLE malgré six ré-horodatages

            # Un changement de DIRECTION est un événement neuf : la fenêtre redémarre.
            now = base + 10
            engine.schema.liquidity_sweep = LiquiditySweep(
                assessable=True, triggered=True, reason="t",
                alert=LiquiditySweepAlert(ts=now, kind="LIQUIDITY_SWEEP",
                                          direction="ASK_SWEEP", trigger="T", detail="t"))
            engine._maybe_emit_lsr(now)
            assert engine._sweep_event_ts == now

            # Condition levée → plus d'événement du tout (pas de fenêtre fantôme).
            engine.schema.liquidity_sweep = LiquiditySweep(assessable=True, triggered=False,
                                                           reason="", alert=None)
            engine._maybe_emit_lsr(base + 11)
            assert engine._sweep_event_ts is None and engine._sweep_event_key is None
        finally:
            await state.close()
    asyncio.run(scenario())


# =============================================================================================
# D. /polish — l'ombre doit être LISIBLE et PERSISTANTE
# =============================================================================================

@pytest.mark.skipif(not _engine_available(), reason="Redis indisponible — intégration sautée")
def test_D1_l_ombre_SURVIT_a_la_reconstruction_des_extras():
    """`_assemble_fast` reconstruit `extras` à 4 Hz, la boucle sweep y écrit à 1 Hz : l'ombre
    n'était visible que 25 % des ticks (mesuré). Un consommateur la verrait CLIGNOTER —
    indistinguable de « non mesurée », exactement ce que ce terminal refuse."""
    import asyncio
    import time

    from app.datasource.mock import MockDataSource
    from app.engine import Engine
    from app.redis_state import RedisState
    from app.schema import LiquiditySweep, LiquiditySweepAlert

    async def scenario():
        state = RedisState()
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            engine = Engine(MockDataSource(), state)
            base = time.time()
            engine.schema.liquidity_sweep = LiquiditySweep(
                assessable=True, triggered=True, reason="t",
                alert=LiquiditySweepAlert(ts=base, kind="LIQUIDITY_SWEEP",
                                          direction="BID_SWEEP", trigger="T", detail="t"))
            engine._maybe_emit_lsr(base)                     # la boucle sweep écrit l'ombre
            assert "orderflow_shadow" in engine._extras
            for k in range(6):                               # six ticks rapides ensuite
                await engine.ds.tick_fast(state)
                await engine._assemble_fast(base + 0.25 * (k + 1))
                assert "orderflow_shadow" in engine._extras, f"effacée au tick {k}"
        finally:
            await state.close()
    asyncio.run(scenario())


def test_D2_l_ombre_porte_une_LIGNE_LISIBLE_pas_seulement_des_nombres():
    """Un dict de valeurs brutes n'est pas un message. La première chose qu'un humain doit lire,
    c'est le VERDICT : d'accord, en désaccord (et sur quoi), ou pas mesurable."""
    from app.orderflow import OrderFlowSnapshot
    from app.orderflow.bridge import orderflow_shadow

    class _S:
        class s1_state:
            class order_flow:
                absorption = _Meta(True)
                aggressor_ratio = _Meta(0.85)
        class liquidity_sweep:
            triggered = True
            class alert:
                direction = "BID_SWEEP"

    accord = orderflow_shadow(_S(), OrderFlowSnapshot(
        now=T0, window_s=30.0, wall_refill_ratio=0.9, tape_aggressor_buy_fraction=0.85))
    assert "accord" in accord["resume"].lower() and "B" not in accord["resume"].split()[0]

    desaccord = orderflow_shadow(_S(), OrderFlowSnapshot(
        now=T0, window_s=30.0, wall_refill_ratio=0.1, tape_aggressor_buy_fraction=0.85))
    assert "DÉSACCORD" in desaccord["resume"] and "B1" in desaccord["resume"]

    muet = orderflow_shadow(_S(), OrderFlowSnapshot(now=T0, window_s=30.0))
    assert "non mesur" in muet["resume"].lower()
