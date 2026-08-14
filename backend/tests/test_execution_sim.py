"""Feature — simulateur d'exécution FIFO (D-078, phase P3).

Port Python d'`execution_sim.js` (artefact v1.7), **durci**. Le biais que ce module existe pour
supprimer est nommé dans `CLAUDE.md` §5 de l'artefact :

> Un ordre limite n'est **pas rempli au simple touché** : il entre en fin de file FIFO et n'est
> exécuté que quand le volume devant lui est consommé. C'est le biais le plus coûteux d'un
> backtest de scalping.

Sur un TP à 5 ticks, supposer le fill au touché transforme des trades jamais remplis en
gagnants. C'est précisément la raison pour laquelle P3 passe avant P2 : sans ce module, les 60+
setups journalisés seraient corrélés à des résultats **faux**, pas seulement absents.

**Quatre défauts de l'artefact, corrigés ici et testés :**

1. `if (vol > 0 && !this.requireTrade === false)` — `(!requireTrade) === false` signifie
   « requireTrade est vrai ». Le drapeau est donc **inversé** : le mettre à `false` (« ne pas
   exiger d'échange ») empêche tout remplissage au lieu de l'assouplir.
2. `_lat()` tire `Math.random()`. L'invariant n°1 de l'artefact exige des fonctions pures à état
   injecté « ce qui rend le backtest rejouable à l'identique » — une latence aléatoire non
   semée le rend précisément **non** rejouable.
3. `queueAhead` est fourni par l'appelant et vaut 0 par défaut : le cas par défaut est donc
   « premier de la file », l'hypothèse la plus optimiste possible. La file se DÉDUIT du carnet.
4. Carnet épuisé : l'artefact invente un prix à 2 ticks du dernier niveau et n'en dit rien. Le
   remplissage devient fictif sans que le résultat le signale.

**Aucun ordre réel (§2.1).** Ce module simule ; il ne parle à aucun courtier.
"""
import pytest

from app.execution_sim import (
    Book, BookLevel, ExecutionSimulator, OrderStatus, book_from_levels,
)

TICK = 0.25


def _book(best_bid=5999.75, best_ask=6000.0, size=50.0, depth=4):
    bids = [BookLevel(best_bid - i * TICK, size) for i in range(depth)]
    asks = [BookLevel(best_ask + i * TICK, size) for i in range(depth)]
    return Book(bids=tuple(bids), asks=tuple(asks))


def _sim(**kw):
    kw.setdefault("latency_ms", 0.0)
    kw.setdefault("latency_jitter_ms", 0.0)
    kw.setdefault("rng_seed", 2026)
    return ExecutionSimulator(tick_size=TICK, **kw)


# ---------------------------------------------------------------------------
# LE biais — un touché ne remplit pas
# ---------------------------------------------------------------------------

def test_un_TOUCHE_seul_ne_remplit_PAS_tant_que_la_file_est_devant():
    """Le cœur du module. 50 lots dorment à 5999.75 ; on se place derrière eux. Le prix vient
    toucher le niveau et 10 lots s'échangent : ils consomment la file, pas notre ordre."""
    sim = _sim()
    order = sim.place_limit("BUY", 5999.75, qty=2, now_ms=0, book=_book())
    assert order.queue_ahead == 50.0, "la file se déduit du carnet, pas d'un défaut optimiste"

    fills = sim.on_trade(ts_ms=1_000, price=5999.75, size=10)
    assert fills == [], "aucun remplissage : 10 lots ne passent pas 50 de file"
    assert order.queue_ahead == 40.0
    assert order.status is OrderStatus.WORKING


def test_le_remplissage_survient_quand_la_file_est_CONSOMMEE():
    sim = _sim()
    order = sim.place_limit("BUY", 5999.75, qty=2, now_ms=0, book=_book(size=10))
    assert sim.on_trade(1_000, 5999.75, 10) == [], "10 lots consomment exactement la file"
    fills = sim.on_trade(1_100, 5999.75, 5)
    assert len(fills) == 1 and fills[0].qty == 2
    assert order.status is OrderStatus.FILLED


def test_remplissage_PARTIEL_quand_le_volume_ne_couvre_pas_toute_la_quantite():
    sim = _sim()
    order = sim.place_limit("BUY", 5999.75, qty=5, now_ms=0, book=_book(size=0))
    fills = sim.on_trade(1_000, 5999.75, 2)
    assert len(fills) == 1 and fills[0].qty == 2
    assert order.status is OrderStatus.PARTIAL and order.filled_qty == 2
    sim.on_trade(1_100, 5999.75, 10)
    assert order.status is OrderStatus.FILLED and order.filled_qty == 5


def test_prix_qui_TRAVERSE_le_niveau_remplit_sans_attendre_la_file():
    """Si ça s'échange sous notre bid, tout ce qui était devant a nécessairement été servi."""
    sim = _sim()
    order = sim.place_limit("BUY", 5999.75, qty=2, now_ms=0, book=_book(size=500))
    fills = sim.on_trade(1_000, 5999.50, 1)
    assert len(fills) == 1 and fills[0].price == 5999.75
    assert order.status is OrderStatus.FILLED


def test_un_echange_du_MAUVAIS_cote_ne_remplit_rien():
    sim = _sim()
    sim.place_limit("BUY", 5999.75, qty=2, now_ms=0, book=_book(size=0))
    assert sim.on_trade(1_000, 6000.25, 100) == []


def test_la_file_par_defaut_n_est_PAS_zero_sans_carnet():
    """Sans carnet, on ne peut pas déduire la file. Se placer premier serait l'hypothèse la plus
    optimiste possible — exactement le biais qu'on combat. Fail-closed : l'ordre est refusé."""
    sim = _sim()
    assert sim.place_limit("BUY", 5999.75, qty=2, now_ms=0) is None
    assert sim.stats()["rejects"] == 1


def test_file_explicite_acceptee_pour_le_rejeu_MBO():
    """En rejeu MBO on connaît la vraie position de file : elle prime sur la déduction."""
    sim = _sim()
    order = sim.place_limit("BUY", 5999.75, qty=2, now_ms=0, book=_book(size=50), queue_ahead=7)
    assert order.queue_ahead == 7.0


# ---------------------------------------------------------------------------
# Latence — un ordre n'est pas au marché à l'instant où on le décide
# ---------------------------------------------------------------------------

def test_un_evenement_ANTERIEUR_a_l_arrivee_au_marche_est_ignore():
    sim = ExecutionSimulator(tick_size=TICK, latency_ms=35, latency_jitter_ms=0, rng_seed=1)
    order = sim.place_limit("BUY", 5999.75, qty=2, now_ms=0, book=_book(size=0))
    assert order.placed_ts_ms == 35
    assert sim.on_trade(20, 5999.50, 10) == [], "l'ordre n'était pas encore au marché"
    assert sim.on_trade(40, 5999.50, 10) != []


def test_la_latence_est_DETERMINISTE_a_graine_egale():
    """L'artefact tire `Math.random()`, ce qui rend le backtest non rejouable — en
    contradiction avec son propre invariant n°1."""
    def run(seed):
        sim = ExecutionSimulator(tick_size=TICK, latency_ms=35, latency_jitter_ms=15,
                                 rng_seed=seed)
        return [sim.place_limit("BUY", 5999.75, 1, now_ms=0, book=_book(size=0)).placed_ts_ms
                for _ in range(5)]

    assert run(2026) == run(2026), "même graine, même latence"
    assert run(2026) != run(7), "graines distinctes, latences distinctes"


def test_le_jitter_reste_dans_ses_bornes():
    sim = ExecutionSimulator(tick_size=TICK, latency_ms=35, latency_jitter_ms=15, rng_seed=3)
    for _ in range(50):
        o = sim.place_limit("BUY", 5999.75, 1, now_ms=0, book=_book(size=0))
        assert 20 <= o.placed_ts_ms <= 50


# ---------------------------------------------------------------------------
# Annulations — jamais entravées (invariant n°4 de l'artefact)
# ---------------------------------------------------------------------------

def test_expiration_temporelle_annule_l_ordre():
    sim = _sim()
    o = sim.place_limit("BUY", 5999.75, 2, now_ms=0, book=_book(size=0), cancel_after_ms=90_000)
    sim.on_trade(90_001, 6000.25, 1)
    assert o.status is OrderStatus.CANCELLED and o.cancel_reason == "TIME_EXPIRY"


def test_invalidation_par_le_prix_annule_l_ordre():
    sim = _sim()
    o = sim.place_limit("BUY", 5999.75, 2, now_ms=0, book=_book(size=0), cancel_beyond=5999.00)
    sim.on_trade(1_000, 5998.75, 1)
    assert o.status is OrderStatus.CANCELLED and o.cancel_reason == "PRICE_INVALIDATION"


def test_le_gouverneur_gele_les_ENVOIS_apres_trop_d_annulations_rapides():
    sim = _sim(fast_cancel_limit=3)
    for i in range(3):
        o = sim.place_limit("BUY", 5999.75, 1, now_ms=i * 10, book=_book(size=0))
        sim.cancel(o.id, "OPERATOR_CHANGED_MIND", now_ms=i * 10 + 100)
    assert sim.stats()["frozen"] is True
    assert sim.place_limit("BUY", 5999.75, 1, now_ms=999, book=_book(size=0)) is None


def test_une_annulation_de_PROTECTION_n_est_jamais_comptee_ni_bloquee():
    """Invariant n°4 : « on freine les envois, jamais les sorties ». Un arrêt de risque ne doit
    pas pouvoir déclencher le gel qui l'empêcherait de se répéter."""
    sim = _sim(fast_cancel_limit=2)
    for reason in ("RISK_HALT", "NEWS_BLACKOUT", "SESSION_END", "OPERATOR"):
        o = sim.place_limit("BUY", 5999.75, 1, now_ms=0, book=_book(size=0))
        assert sim.cancel(o.id, reason, now_ms=10) is not None
    assert sim.stats()["frozen"] is False
    assert sim.stats()["fast_cancels"] == 0


def test_annuler_reste_possible_meme_gele():
    sim = _sim(fast_cancel_limit=1)
    o = sim.place_limit("BUY", 5999.75, 1, now_ms=0, book=_book(size=0))
    sim.cancel(o.id, "MIND_CHANGE", now_ms=10)
    assert sim.stats()["frozen"] is True
    o2 = sim.place_limit("BUY", 5999.75, 1, now_ms=20, book=_book(size=0))
    assert o2 is None                                   # envoi gelé
    assert sim.cancel(o.id, "RISK_HALT", now_ms=30) is None   # déjà annulé, pas une erreur


def test_annuler_un_ordre_inconnu_ne_leve_pas():
    assert _sim().cancel("inexistant", "OPERATOR", now_ms=0) is None


# ---------------------------------------------------------------------------
# Ordres au marché — le slippage est une CONSOMMATION de liquidité
# ---------------------------------------------------------------------------

def test_marche_sans_slippage_si_le_meilleur_niveau_suffit():
    sim = _sim()
    fill = sim.market_order("BUY", qty=10, book=_book(size=50), now_ms=0)
    assert fill.price == 6000.0 and fill.slip_ticks == 0.0 and fill.levels_consumed == 1


def test_marche_qui_TRAVERSE_plusieurs_niveaux_paie_le_slippage():
    sim = _sim()
    fill = sim.market_order("BUY", qty=30, book=_book(size=10), now_ms=0)
    # 10@6000.00 + 10@6000.25 + 10@6000.50 -> moyenne 6000.25, soit 1 tick de slippage
    assert fill.price == pytest.approx(6000.25)
    assert fill.slip_ticks == pytest.approx(1.0)
    assert fill.levels_consumed == 3


def test_le_SHORT_slippe_dans_l_autre_sens():
    sim = _sim()
    fill = sim.market_order("SELL", qty=30, book=_book(size=10), now_ms=0)
    assert fill.price == pytest.approx(5999.50)
    assert fill.slip_ticks == pytest.approx(1.0)


def test_carnet_EPUISE_est_SIGNALE_pas_comble_en_silence():
    """L'artefact invente un prix à 2 ticks du dernier niveau sans le dire : le remplissage
    devient fictif et le résultat ne le signale pas (§3)."""
    sim = _sim()
    fill = sim.market_order("BUY", qty=1_000, book=_book(size=10, depth=4), now_ms=0)
    assert fill.book_exhausted is True
    assert fill.filled_qty < 1_000, "on ne remplit pas ce que le carnet ne portait pas"
    assert fill.unfilled_qty == 1_000 - fill.filled_qty


def test_carnet_VIDE_ne_produit_aucun_remplissage():
    sim = _sim()
    fill = sim.market_order("BUY", qty=5, book=Book(bids=(), asks=()), now_ms=0)
    assert fill.filled_qty == 0 and fill.price is None and fill.book_exhausted is True


def test_le_marche_CONSOMME_le_carnet_deux_ordres_ne_prennent_pas_la_meme_liquidite():
    """L'artefact ne mute pas le carnet : deux ordres au marché au même instant obtenaient tous
    deux le meilleur niveau, fabriquant de la liquidité."""
    sim = _sim()
    book = _book(size=10)
    f1, book = sim.market_order_consuming("BUY", 10, book, now_ms=0)
    f2, book = sim.market_order_consuming("BUY", 10, book, now_ms=1)
    assert f1.price == 6000.0
    assert f2.price == 6000.25, "le second paie le niveau suivant"


# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------

def test_les_stats_comptent_envois_remplissages_et_slippage_moyen():
    sim = _sim()
    o = sim.place_limit("BUY", 5999.75, 2, now_ms=0, book=_book(size=0))
    sim.on_trade(1_000, 5999.75, 5)
    sim.market_order("BUY", 30, _book(size=10), now_ms=2_000)
    st = sim.stats()
    assert st["placed"] == 1 and st["filled"] == 2
    assert st["avg_slip_ticks"] == pytest.approx(0.5)    # 0 sur la limite, 1 sur le marché
    assert o.status is OrderStatus.FILLED


def test_le_ratio_OTR_reste_None_sous_l_echantillon_minimal():
    """Un ratio calculé sur trois messages ne mesure rien. Mieux vaut `None` qu'un chiffre qui
    a l'air d'une mesure (§3)."""
    sim = _sim()
    o = sim.place_limit("BUY", 5999.75, 1, now_ms=0, book=_book(size=0))
    sim.cancel(o.id, "OPERATOR", now_ms=5_000)
    assert sim.stats()["otr_ratio"] is None


# ---------------------------------------------------------------------------
# Robustesse — le simulateur ne lève pas sur des entrées de rejeu douteuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("price,size", [
    (float("nan"), 10), (float("inf"), 10), (5999.75, float("nan")),
    (5999.75, -5), (None, 10), (5999.75, None),
])
def test_un_evenement_de_marche_ABERRANT_est_ignore_sans_lever(price, size):
    sim = _sim()
    o = sim.place_limit("BUY", 5999.75, 2, now_ms=0, book=_book(size=0))
    assert sim.on_trade(1_000, price, size) == []
    assert o.status is OrderStatus.WORKING


def test_une_quantite_non_finie_est_refusee_a_l_envoi():
    sim = _sim()
    for qty in (0, -1, float("nan")):
        assert sim.place_limit("BUY", 5999.75, qty, now_ms=0, book=_book(size=0)) is None


def test_book_from_levels_ordonne_et_ecarte_l_illisible():
    b = book_from_levels(bids=[[5999.25, 5], [5999.75, 10], ["x", 1], [5999.50, float("nan")]],
                         asks=[[6000.25, 5], [6000.0, 10]])
    assert [lvl.price for lvl in b.bids] == [5999.75, 5999.25], "bids décroissants"
    assert [lvl.price for lvl in b.asks] == [6000.0, 6000.25], "asks croissants"


def test_aucun_chemin_ne_passe_un_ordre_reel():
    """§2.1 — ce module SIMULE. Un test de garde, parce que la frontière est facile à franchir
    sans y penser une fois qu'un simulateur produit des `Fill` crédibles."""
    import inspect

    from app import execution_sim
    src = inspect.getsource(execution_sim)
    for interdit in ("requests", "httpx", "socket", "broker", "submit_order", "aiohttp"):
        assert interdit not in src


def test_un_COTE_inconnu_est_refuse_pas_lu_du_mauvais_cote():
    """Régression (D-080). `book.bids if side == "BUY" else book.asks` faisait d'un côté mal
    orthographié — ou d'un `LONG` non traduit — une file lue du MAUVAIS côté du carnet, donc
    presque toujours nulle : « premier de la file », le biais que ce module interdit."""
    sim = _sim()
    for cote in ("LONG", "SHORT", "buy", "", None):
        assert sim.place_limit(cote, 5999.75, 2, now_ms=0, book=_book(size=50)) is None
