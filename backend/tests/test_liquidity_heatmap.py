"""Feature — Heatmap de liquidité (LOB) : accumulation temporelle du carnet L2 (D-036).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- accumule le carnet `s1_state.order_book` (L2, D-025) en COLONNES temporelles (une par tick
  rapide, 4 Hz) → fenêtre glissante bornée ; le frontend Canvas la dessine (profondeur
  historique) sans surcharger le DOM ;
- FAIL-CLOSED (§3) : carnet périmé/absent → AUCUNE colonne inventée (on conserve l'historique,
  la fraîcheur du bloc suit le carnet) ;
- OBSERVATION seule (§2.1) : rendu lecture seule, jamais un ordre.
"""
from app.heatmap import accumulate_heatmap
from app.meta import Freshness, MetaField


def _ob(bids, asks, fresh=Freshness.FRESH):
    return MetaField(value={"bids": bids, "asks": asks}, last_update_ts=0.0,
                     source="sierra_chart", freshness=fresh)


def test_appends_one_column_when_fresh():
    hist, val = accumulate_heatmap([], _ob([[5000.0, 10.0]], [[5000.5, 8.0]]), 1.0, 60, 10)
    assert len(val["columns"]) == 1
    col = val["columns"][0]
    assert col["ts"] == 1.0 and col["bids"] == [[5000.0, 10.0]] and col["asks"] == [[5000.5, 8.0]]
    assert val["max_size"] == 10.0
    assert hist == val["columns"]                       # l'historique retourné = les colonnes


def test_caps_to_max_columns_dropping_oldest():
    hist = []
    for i in range(70):
        hist, val = accumulate_heatmap(hist, _ob([[5000.0, float(i + 1)]], [[5000.5, 1.0]]),
                                       float(i), 60, 10)
    assert len(val["columns"]) == 60                    # borné
    assert val["columns"][0]["ts"] == 10.0              # 0..9 évincés (les plus anciens)
    assert val["columns"][-1]["ts"] == 69.0             # plus récent en fin


def test_failclosed_stale_book_adds_no_column():
    hist, _ = accumulate_heatmap([], _ob([[5000.0, 10.0]], [[5000.5, 8.0]]), 1.0, 60, 10)
    hist2, val = accumulate_heatmap(hist, _ob([[5000.0, 99.0]], [[5000.5, 99.0]],
                                              fresh=Freshness.STALE), 2.0, 60, 10)
    assert len(val["columns"]) == 1                     # rien d'ajouté sur STALE (§3)
    assert val["columns"][0]["bids"] == [[5000.0, 10.0]]  # ancienne colonne conservée telle quelle
    assert val["max_size"] == 10.0


def test_absent_book_adds_no_column():
    _, val = accumulate_heatmap([], _ob(None, None, fresh=Freshness.ABSENT), 1.0, 60, 10)
    assert val["columns"] == [] and val["max_size"] == 0.0


def test_truncates_each_side_to_levels():
    bids = [[5000.0 - i * 0.5, 5.0] for i in range(20)]
    asks = [[5000.5 + i * 0.5, 5.0] for i in range(20)]
    _, val = accumulate_heatmap([], _ob(bids, asks), 1.0, 60, 10)
    assert len(val["columns"][0]["bids"]) == 10 and len(val["columns"][0]["asks"]) == 10


def test_empty_book_no_column():
    _, val = accumulate_heatmap([], _ob([], []), 1.0, 60, 10)
    assert val["columns"] == [] and val["max_size"] == 0.0


def test_max_size_spans_all_columns_both_sides():
    hist, _ = accumulate_heatmap([], _ob([[5000.0, 3.0]], [[5000.5, 4.0]]), 1.0, 60, 10)
    _, val = accumulate_heatmap(hist, _ob([[5000.0, 2.0]], [[5000.5, 12.0]]), 2.0, 60, 10)
    assert val["max_size"] == 12.0                      # max ask de la 2e colonne
