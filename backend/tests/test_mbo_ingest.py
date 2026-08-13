"""Feature — ingestion Parquet MBO (D-079, phase P3 item 1).

Tests sur les **fixtures réelles** de l'artefact v1.7 (`mbo_sample.parquet`,
`mbo_corrupt.parquet`, format Databento GLBX.MDP3), pas sur des tables fabriquées ici : une
fixture écrite pour l'occasion se contenterait de refléter mes propres hypothèses de format.

`pyarrow` est optionnel — le cœur (événements + carnet) n'en dépend pas. Ces tests-ci sont
donc les seuls à le requérir, et se sautent proprement s'il est absent.
"""
import pathlib

import pytest

from app.mbo.book import MboBook
from app.mbo.events import MboAction, MboSide, RejectCode
from app.mbo.ingest import MboIngestError, ingest_parquet, replay

pytest.importorskip("pyarrow", reason="lecture Parquet — dépendance optionnelle (dev)")

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SAMPLE = str(FIXTURES / "mbo_sample.parquet")
CORRUPT = str(FIXTURES / "mbo_corrupt.parquet")


# ---------------------------------------------------------------------------
# Lecture nominale
# ---------------------------------------------------------------------------

def test_la_fixture_nominale_produit_ses_sept_evenements():
    events, stats = ingest_parquet(SAMPLE)
    assert stats.rows_read == 7 and stats.events_emitted == 7 and stats.rows_rejected == 0
    assert [e.action for e in events] == ["R", "A", "A", "T", "C", "M", "T"]


def test_le_fixed_point_Databento_est_DESCALE():
    """`price` est un int64 en unités de 1e-9 : 5_000_000_000_000 vaut 5000.00, pas 5e12."""
    events, _ = ingest_parquet(SAMPLE)
    assert events[1].price == pytest.approx(5000.00)
    assert events[2].price == pytest.approx(5000.25)


def test_les_horodatages_restent_ENTIERS_apres_lecture():
    """Le point où un flottant détruirait le déterminisme du rejeu (voir `events.py`)."""
    events, stats = ingest_parquet(SAMPLE)
    assert all(isinstance(e.ts_event, int) for e in events)
    assert isinstance(stats.first_ts, int) and isinstance(stats.last_ts, int)
    assert stats.first_ts == 1_700_000_000_000_000_000


def test_les_bornes_temporelles_sont_remontees():
    _, stats = ingest_parquet(SAMPLE)
    assert stats.last_ts - stats.first_ts == 30_000_000        # 30 ms de fixture


# ---------------------------------------------------------------------------
# Fichier corrompu — rien n'est écarté en silence
# ---------------------------------------------------------------------------

def test_l_action_INCONNUE_est_rejetee_AVEC_son_motif():
    _, stats = ingest_parquet(CORRUPT)
    assert stats.rejections_by_reason.get(RejectCode.UNKNOWN_ACTION) == 1
    assert stats.rows_read == 3 and stats.events_emitted == 2


def test_le_recul_temporel_est_SIGNALE_et_conserve_par_defaut():
    """Trier en silence ferait disparaître le symptôme d'un problème de capture que l'opérateur
    doit connaître avant d'en tirer des conclusions."""
    events, stats = ingest_parquet(CORRUPT)
    assert stats.out_of_order_count == 1
    assert len(events) == 2, "l'événement en recul est conservé, pas jeté"
    assert events[1].ts_event < events[0].ts_event


def test_jeter_les_reculs_est_un_choix_EXPLICITE_et_compte():
    events, stats = ingest_parquet(CORRUPT, drop_out_of_order=True)
    assert len(events) == 1
    assert stats.rejections_by_reason.get(RejectCode.OUT_OF_ORDER) == 1


def test_le_taux_de_rejet_est_CALCULE_pas_seulement_disponible():
    """Un fichier à moitié rejeté qui produit un backtest d'allure normale est le pire résultat
    possible. Le ratio doit sauter aux yeux sans que l'appelant ait à le calculer."""
    _, stats = ingest_parquet(CORRUPT)
    assert stats.as_dict()["reject_ratio"] == pytest.approx(1 / 3)


def test_un_fichier_illisible_LEVE_au_lieu_de_rendre_une_liste_vide():
    """Une liste vide se lirait « séance sans événements » — indistinguable d'un fichier absent."""
    with pytest.raises(MboIngestError):
        ingest_parquet(str(FIXTURES / "inexistant.parquet"))


def test_colonne_requise_absente_est_FATALE_au_fichier(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq
    path = tmp_path / "tronque.parquet"
    pq.write_table(pa.table({"ts_event": pa.array([1], pa.int64())}), path)
    with pytest.raises(MboIngestError, match="colonnes requises absentes"):
        ingest_parquet(str(path))


# ---------------------------------------------------------------------------
# Rejeu tick-by-tick — la reconstruction du carnet
# ---------------------------------------------------------------------------

def test_le_rejeu_reconstruit_le_carnet_etat_final_de_la_fixture():
    """Déroulé de la fixture : clear · bid 5000.00 x40 (101) · ask 5000.25 x35 (102) ·
    trade 10 sur l'ask · cancel 25 sur l'ask · modify 101 vers 4999.75 · trade 15 sur le bid."""
    events, _ = ingest_parquet(SAMPLE)
    book = MboBook(tick_size=0.25)
    changed = [c for _, c in replay(iter(events), book)]

    assert all(changed), "chaque événement de cette fixture modifie le carnet"
    ask = book.level(MboSide.ASK, 5000.25)
    assert ask.traded_volume == 10 and ask.cancelled_volume == 25
    assert ask.size == 0, "35 = 10 échangés + 25 annulés"
    bid = book.level(MboSide.BID, 4999.75)
    assert bid.traded_volume == 15 and bid.size == 25
    assert book.best_bid() == 4999.75
    assert book.best_ask() is None, "l'ask a été entièrement vidé"


def test_les_trades_ANONYMES_de_la_fixture_sont_tous_resolus():
    """Les deux trades portent `order_id = 0` — le cas normal des données réelles. Si la
    résolution par le prix échouait, `unresolved_trades` le dirait au lieu de fausser le delta."""
    events, _ = ingest_parquet(SAMPLE)
    book = MboBook(tick_size=0.25)
    list(replay(iter(events), book))
    assert book.unresolved_trades == 0


def test_le_rejeu_est_REPRODUCTIBLE_a_l_identique():
    """L'invariant qui justifie tout le reste : deux rejeux du même fichier donnent le même
    carnet, sinon aucun backtest n'est comparable à un autre."""
    def run():
        events, _ = ingest_parquet(SAMPLE)
        book = MboBook(tick_size=0.25)
        list(replay(iter(events), book))
        return (book.best_bid(), book.best_ask(), book.order_count(),
                book.cumulative_depth(MboSide.BID, 10))

    assert run() == run()


def test_le_carnet_reconstruit_alimente_le_simulateur_FIFO():
    """La jonction de P3 : la file d'attente du simulateur devient la profondeur RÉELLEMENT
    observée dans le flux MBO, au lieu d'une déduction."""
    from app.execution_sim import ExecutionSimulator

    events, _ = ingest_parquet(SAMPLE)
    book = MboBook(tick_size=0.25)
    for event, _changed in replay(iter(events), book):
        if event.action == MboAction.MODIFY:
            break                                   # on s'arrête juste après le déplacement

    sim = ExecutionSimulator(tick_size=0.25, latency_ms=0, latency_jitter_ms=0, rng_seed=1)
    order = sim.place_limit("BUY", 4999.75, qty=2, now_ms=0,
                            book=book.to_aggregated_book(depth=10))
    assert order is not None
    assert order.queue_ahead == 40.0, "les 40 lots de l'ordre 101 sont devant nous"
