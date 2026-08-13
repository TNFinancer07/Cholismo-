"""Feature — reconstruction du carnet MBO (D-079, phase P3 item 1).

Port de `of/book.ts` (artefact v1.7). Le suivi **par ordre** est ce qui rend B1 (rechargement de
mur) mesurable : avec du L2 agrégé seul, on ne distingue pas « le mur a été consommé puis
rechargé » de « le mur n'a jamais bougé ». C'est aussi lui qui donne au simulateur FIFO
(D-078) une **vraie** profondeur de file plutôt qu'une déduction.

**L'ambiguïté de côté sur un trade — traitée, pas devinée.**

L'artefact impute le passif d'un trade depuis `ev.side` : `side === 'A' ? asks : bids`. Or
`CLAUDE.md` §5 de ce même artefact avertit : « `tradeSideMeaning` = **agresseur**, pas le passif
consommé. L'inverser retourne B2 et B3 **en silence** ». Et la convention Databento documente
`side` comme le côté de l'**agresseur**. Les deux lectures s'opposent, et la fixture (trade
`side='A'` au prix de l'ask) suit la seconde.

Deviner ici inverserait deux gates sans qu'aucun test ne tombe. On résout donc le côté passif
**dans cet ordre** : (1) l'`order_id` au repos, seule source autoritaire ; (2) à défaut, le PRIX
comparé au meilleur bid/ask — dérivé du carnet, donc indépendant de la convention ; (3) si
aucun des deux ne tranche, l'événement est **rejeté et compté**, jamais imputé au hasard.
"""

from app.mbo.book import MboBook
from app.mbo.events import MboAction, MboEvent, MboSide

TICK = 0.25


def _ev(action, side, price, size, order_id=0, ts=1, seq=1):
    return MboEvent(ts_event=1_700_000_000_000_000_000 + ts, ts_recv=1_700_000_000_000_000_000 + ts,
                    action=action, side=side, price=price, size=size,
                    order_id=order_id, sequence=seq, symbol="MESZ4")


def _book():
    return MboBook(tick_size=TICK)


# ---------------------------------------------------------------------------
# Ajout / meilleures limites
# ---------------------------------------------------------------------------

def test_add_alimente_le_niveau_et_la_meilleure_limite():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
    assert b.best_bid() == 5000.00 and b.best_ask() == 5000.25
    lvl = b.level(MboSide.BID, 5000.00)
    assert lvl.size == 40 and lvl.order_count == 1 and lvl.added_volume == 40


def test_deux_ordres_au_MEME_niveau_s_agregent():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=1))
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 10, order_id=2))
    lvl = b.level(MboSide.BID, 5000.00)
    assert lvl.size == 50 and lvl.order_count == 2


def test_clear_vide_tout():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=1))
    b.apply(_ev(MboAction.CLEAR, MboSide.NONE, 0, 0))
    assert b.best_bid() is None and b.order_count() == 0


# ---------------------------------------------------------------------------
# Annulation — la signature du spoofing
# ---------------------------------------------------------------------------

def test_cancel_retire_le_volume_et_le_COMPTE_separement():
    """`cancelled_volume` distingué de `traded_volume` : c'est ce qui rend une retraite de mur
    (spoofing) distinguable d'une consommation réelle."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
    b.apply(_ev(MboAction.CANCEL, MboSide.ASK, 5000.25, 25, order_id=102))
    lvl = b.level(MboSide.ASK, 5000.25)
    assert lvl.size == 10 and lvl.cancelled_volume == 25 and lvl.traded_volume == 0


def test_cancel_total_retire_l_ordre_du_suivi():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
    b.apply(_ev(MboAction.CANCEL, MboSide.ASK, 5000.25, 35, order_id=102))
    assert b.order_count() == 0
    assert b.level(MboSide.ASK, 5000.25).order_count == 0
    assert b.best_ask() is None, "un niveau vidé ne peut plus être la meilleure limite"


def test_l_historique_de_volume_SURVIT_au_vidage_du_niveau():
    """Indispensable à B1 : sans l'historique, un mur consommé puis rechargé est indiscernable
    d'un mur qui n'a jamais bougé."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=1))
    b.apply(_ev(MboAction.CANCEL, MboSide.ASK, 5000.25, 35, order_id=1))
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 20, order_id=2))
    lvl = b.level(MboSide.ASK, 5000.25)
    assert lvl.added_volume == 55, "35 + 20 cumulés"
    assert lvl.cancelled_volume == 35
    assert lvl.size == 20


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------

def test_modify_deplace_l_ordre_sans_dupliquer_le_volume():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.MODIFY, MboSide.BID, 4999.75, 40, order_id=101))
    assert b.level(MboSide.BID, 5000.00).size == 0
    assert b.level(MboSide.BID, 4999.75).size == 40
    assert b.order_count() == 1, "un seul ordre, déplacé"
    assert b.best_bid() == 4999.75


# ---------------------------------------------------------------------------
# Trade — la résolution du côté PASSIF
# ---------------------------------------------------------------------------

def test_trade_avec_order_id_CONNU_utilise_le_cote_de_l_ordre_au_repos():
    """Source autoritaire : l'ordre au repos porte son propre côté, aucune convention à deviner."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
    # `side` volontairement INCOHÉRENT avec le passif : l'order_id doit primer.
    b.apply(_ev(MboAction.TRADE, MboSide.BID, 5000.25, 10, order_id=102))
    lvl = b.level(MboSide.ASK, 5000.25)
    assert lvl.size == 25 and lvl.traded_volume == 10
    assert b.level(MboSide.BID, 5000.25) is None, "rien n'a touché le bid"


def test_trade_ANONYME_resout_le_cote_par_le_PRIX_pas_par_le_drapeau():
    """`order_id = 0` est le cas normal dans les données réelles. Le prix comparé aux meilleures
    limites tranche sans dépendre de la convention `side`."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
    b.apply(_ev(MboAction.TRADE, MboSide.ASK, 5000.25, 10, order_id=0))
    assert b.level(MboSide.ASK, 5000.25).traded_volume == 10
    assert b.level(MboSide.BID, 5000.00).traded_volume == 0


def test_le_drapeau_side_NE_PEUT_PAS_inverser_le_passif():
    """Le test qui protège B2/B3. Même trade, drapeau opposé : le résultat ne bouge pas, parce
    que c'est le prix qui décide."""
    def run(flag):
        b = _book()
        b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
        b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
        b.apply(_ev(MboAction.TRADE, flag, 5000.25, 10, order_id=0))
        return b.level(MboSide.ASK, 5000.25).traded_volume

    assert run(MboSide.ASK) == run(MboSide.BID) == 10


def test_trade_AU_DELA_du_meilleur_ask_reste_resolvable():
    """Un balayage traverse plusieurs niveaux : l'échange au-dessus du meilleur ask a bien
    consommé de l'ask. Le rejet ne doit pas frapper ce cas légitime."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))
    assert b.apply(_ev(MboAction.TRADE, MboSide.ASK, 5010.00, 10, order_id=0)) is True
    assert b.unresolved_trades == 0


def test_trade_DANS_LE_SPREAD_est_REJETE_pas_impute_au_hasard():
    """Ni order_id connu, ni prix rattachable à un côté : entre les deux meilleures limites,
    rien ne tranche. Imputer au hasard fausserait le delta signé sans qu'aucun test ne tombe."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.75, 35, order_id=102))
    changed = b.apply(_ev(MboAction.TRADE, MboSide.ASK, 5000.25, 10, order_id=0))
    assert changed is False
    assert b.unresolved_trades == 1
    assert b.level(MboSide.BID, 5000.00).traded_volume == 0
    assert b.level(MboSide.ASK, 5000.75).traded_volume == 0


def test_trade_sur_carnet_VIDE_est_rejete():
    b = _book()
    assert b.apply(_ev(MboAction.TRADE, MboSide.ASK, 5000.25, 10, order_id=0)) is False
    assert b.unresolved_trades == 1


# ---------------------------------------------------------------------------
# Profondeur — ce que F4 consomme, et ce que le simulateur FIFO utilise
# ---------------------------------------------------------------------------

def test_profondeur_cumulee_sur_les_N_meilleurs_niveaux():
    b = _book()
    for i, size in enumerate((10, 20, 30, 40)):
        b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00 - i * TICK, size, order_id=i + 1))
    assert b.cumulative_depth(MboSide.BID, 3) == 60
    assert b.cumulative_depth(MboSide.BID, 99) == 100


def test_les_niveaux_VIDES_ne_comptent_pas_dans_la_profondeur():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 10, order_id=1))
    b.apply(_ev(MboAction.ADD, MboSide.BID, 4999.75, 20, order_id=2))
    b.apply(_ev(MboAction.CANCEL, MboSide.BID, 5000.00, 10, order_id=1))
    assert b.cumulative_depth(MboSide.BID, 5) == 20


def test_le_carnet_agrege_alimente_le_simulateur_FIFO():
    """La jonction de P3 : la file d'attente du simulateur cesse d'être une déduction, elle
    devient la profondeur RÉELLE observée dans le flux MBO."""
    from app.execution_sim import ExecutionSimulator

    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25, 35, order_id=102))

    sim = ExecutionSimulator(tick_size=TICK, latency_ms=0, latency_jitter_ms=0, rng_seed=1)
    order = sim.place_limit("BUY", 5000.00, qty=2, now_ms=0, book=b.to_aggregated_book(depth=10))
    assert order is not None and order.queue_ahead == 40.0


def test_to_aggregated_book_respecte_l_ordre_des_cotes():
    b = _book()
    for i in range(3):
        b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00 - i * TICK, 10, order_id=100 + i))
        b.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25 + i * TICK, 10, order_id=200 + i))
    agg = b.to_aggregated_book(depth=3)
    assert [lvl.price for lvl in agg.bids] == [5000.00, 4999.75, 4999.50]
    assert [lvl.price for lvl in agg.asks] == [5000.25, 5000.50, 5000.75]


# ---------------------------------------------------------------------------
# Déterminisme et robustesse
# ---------------------------------------------------------------------------

def test_les_horodatages_restent_des_ENTIERS_jamais_des_flottants():
    """L'invariant de l'artefact vise une limite de JavaScript (`Number.MAX_SAFE_INTEGER` =
    9.0e15 contre ~1.78e18 pour un epoch ns). Python a des entiers illimités — mais un `float`
    a la MÊME mantisse de 53 bits que le `number` JS. Stocker des ns en flottant réintroduirait
    donc exactement le bug : deux événements distincts collapseraient sur la même valeur."""
    ev = _ev(MboAction.ADD, MboSide.BID, 5000.0, 10, order_id=1, ts=1)
    assert isinstance(ev.ts_event, int) and not isinstance(ev.ts_event, bool)
    a, b_ = 1_700_000_000_000_000_001, 1_700_000_000_000_000_002
    assert a != b_
    assert float(a) == float(b_), "la preuve : en flottant, ces deux ns sont indiscernables"


def test_un_evenement_ABERRANT_ne_casse_pas_le_carnet():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    for price, size in ((float("nan"), 10), (float("inf"), 10), (5000.0, -5), (5000.0, float("nan"))):
        assert b.apply(_ev(MboAction.ADD, MboSide.BID, price, size, order_id=999)) is False
    assert b.level(MboSide.BID, 5000.00).size == 40


def test_une_action_INCONNUE_est_ignoree_sans_lever():
    b = _book()
    assert b.apply(_ev("X", MboSide.BID, 5000.0, 10, order_id=1)) is False


def test_cancel_d_un_ordre_INCONNU_est_impute_au_niveau_carnet_partiel():
    """Au démarrage, le carnet est partiel : des annulations d'ordres jamais vus arrivent. Les
    ignorer laisserait des niveaux gonflés en permanence."""
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 40, order_id=101))
    b.apply(_ev(MboAction.CANCEL, MboSide.BID, 5000.00, 10, order_id=999))
    assert b.level(MboSide.BID, 5000.00).size == 30


def test_le_volume_d_un_niveau_ne_devient_jamais_NEGATIF():
    b = _book()
    b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00, 10, order_id=1))
    b.apply(_ev(MboAction.CANCEL, MboSide.BID, 5000.00, 999, order_id=1))
    assert b.level(MboSide.BID, 5000.00).size == 0


def test_le_nombre_de_niveaux_suivis_est_BORNE():
    """`level_of` créait une entrée à chaque prix touché, y compris pour des annulations
    d'ordres inconnus à des prix arbitraires : sur une séance, la table grossit sans borne
    (piège « fuite mémoire » de RUNTIME_LOOPS Loop D)."""
    b = MboBook(tick_size=TICK, max_levels_per_side=50)
    for i in range(500):
        b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00 - i * TICK, 10, order_id=i + 1))
    assert b.level_count(MboSide.BID) <= 50


def test_rejouer_la_MEME_sequence_donne_le_MEME_carnet():
    def run():
        b = _book()
        for i in range(20):
            b.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00 - (i % 4) * TICK, 10,
                        order_id=i + 1, ts=i))
        b.apply(_ev(MboAction.TRADE, MboSide.BID, 5000.00, 15, order_id=0, ts=99))
        return (b.best_bid(), b.cumulative_depth(MboSide.BID, 10), b.order_count())

    assert run() == run()
