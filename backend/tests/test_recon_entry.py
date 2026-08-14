"""Réconciliation d'un fill d'ENTRÉE observé en direct (D-098).

Grammaire §2.5 : l'entrée est un event, l'issue en est un AUTRE, plus tard, qui référence la
même décision. Ce fichier vérifie surtout ce que l'entrée NE doit pas faire.
"""
from __future__ import annotations

import time

import pytest

from app import config
from app.event_store import EventStore
from app.projections import _reconciled_r_multiples, unmatched_fills
from app.recon import ENTRY_KIND, reconcile, reconcile_entry_fill


@pytest.fixture()
def store(tmp_path):
    return EventStore(str(tmp_path / "events.db"))


def _go(store, instrument="MES", ts=None):
    return store.append("DecisionEvent",
                        {"operator": "SONY", "decision": "GO", "instrument": instrument},
                        ts=ts if ts is not None else time.time())["id"]


def _fill(instrument="MES", ts=None, **kw):
    return {"instrument": instrument, "side": "BUY", "price": 5000.25, "quantity": 1,
            "ts": ts if ts is not None else time.time(), **kw}


def test_une_entree_se_rattache_a_sa_decision_GO(store):
    now = time.time()
    did = _go(store, ts=now)
    ev = reconcile_entry_fill(store, _fill(ts=now + 3), now=now + 3)

    assert ev["decision_id"] == did and ev["matched"] is True
    assert ev["kind"] == ENTRY_KIND


def test_une_entree_n_ecrit_JAMAIS_d_OutcomeEvent(store):
    """Le trade est ouvert : son résultat n'existe pas. Un SCRATCH « en attendant » serait un
    résultat inventé, et il fausserait la matrice au lieu de la remplir."""
    now = time.time()
    _go(store, ts=now)
    reconcile_entry_fill(store, _fill(ts=now), now=now)

    assert store.events("OutcomeEvent") == []
    assert _reconciled_r_multiples(store) == []


def test_un_fill_SANS_GO_est_enregistre_quand_meme(store):
    """Un trade pris hors processus est le signal comportemental le plus important du système.
    Le taire serait pire que de ne rien scraper."""
    ev = reconcile_entry_fill(store, _fill())

    assert ev["matched"] is False and ev["decision_id"] is None
    assert len(unmatched_fills(store)) == 1


def test_une_decision_ne_recoit_pas_DEUX_entrees(store):
    """Le tailer peut relire une ligne (rotation de fichier, redémarrage)."""
    now = time.time()
    did = _go(store, ts=now)
    a = reconcile_entry_fill(store, _fill(ts=now), now=now)
    b = reconcile_entry_fill(store, _fill(ts=now), now=now)

    assert a["decision_id"] == did
    assert b["decision_id"] is None, "la seconde entrée ne doit pas se rattacher à nouveau"


def test_LE_PIEGE_une_entree_ne_fait_pas_perdre_l_issue_du_CSV(store):
    """Le défaut que la conception a évité : `reconcile()` exclut les décisions déjà
    réconciliées. Si une entrée comptait comme telle, le trade clôturé du CSV serait ignoré —
    donc absent de la calibration. Une entrée observée doit rendre la décision PLUS mesurable."""
    now = time.time()
    did = _go(store, ts=now)
    reconcile_entry_fill(store, _fill(ts=now), now=now)

    res = reconcile(store, [{"instrument": "MES", "entry_ts": now, "profit": 250.0,
                             "r_multiple": 2.5}])

    assert res["matched"] == 1, "le CSV doit encore pouvoir réconcilier ce trade"
    outcomes = store.events("OutcomeEvent")
    assert len(outcomes) == 1 and outcomes[0]["decision_id"] == did
    assert _reconciled_r_multiples(store) == [2.5], "le trade entre enfin dans la calibration"


def test_un_recon_SANS_kind_reste_traite_comme_CLOTURE(store):
    """Compatibilité à la LECTURE : l'append-only interdit de réécrire les events d'avant D-098.
    Un `ReconEvent` sans `kind` vient du CSV et décrit un trade fermé."""
    now = time.time()
    did = _go(store, ts=now)
    store.append("ReconEvent", {"decision_id": did, "matched": True,
                                "fill_source": "ninjatrader"}, ts=now)

    res = reconcile(store, [{"instrument": "MES", "entry_ts": now, "profit": 100.0,
                             "r_multiple": 1.0}])
    assert res["matched"] == 0, "un trade déjà clôturé-réconcilié ne se réconcilie pas deux fois"


def test_une_entree_HORS_FENETRE_ne_se_rattache_pas(store):
    now = time.time()
    _go(store, ts=now)
    ev = reconcile_entry_fill(store, _fill(ts=now + config.RECON_MATCH_WINDOW_SECONDS + 60),
                              now=now)
    assert ev["matched"] is False


def test_un_autre_INSTRUMENT_ne_se_rattache_pas(store):
    now = time.time()
    _go(store, instrument="MES", ts=now)
    ev = reconcile_entry_fill(store, _fill(instrument="MNQ", ts=now), now=now)
    assert ev["matched"] is False
