"""Feature — journal des setups + matrice de calibration (D-082, phase P2).

L'infrastructure qui recevra les 60+ setups, prête AVANT les données. Elle répond à une seule
question : **les setups marqués `FLAG` ont-ils un taux de réussite dégradé ?**

Ces tests verrouillent surtout les quatre règles qui font la différence entre une mesure et un
chiffre rassurant : `NO_FILL` hors du dénominateur, pas de taux sous l'échantillon minimal, un
setup sans issue reste `PENDING`, et process/résultat jamais consolidés.
"""
import os
import sqlite3
import tempfile

import pytest

from app import config
from app.event_store import EventStore
from app.setup_journal import CSV_COLUMNS, SetupJournal


@pytest.fixture
def journal():
    path = os.path.join(tempfile.mkdtemp(), "setups.db")
    return SetupJournal(EventStore(path))


def _armed(setup_id, **over):
    base = {
        "setup_id": setup_id, "armed_ts_ms": 1_000.0, "instrument": "MES", "side": "LONG",
        "entry_price": 5000.0, "stop_loss": 4999.0, "target_price": 5001.25,
        "position_size": 1, "context_health": "OK",
        "o1_status": "PASS", "o2_status": "PASS", "o3_status": "PASS",
        "o4_status": "O4_SOURCE_UNCONFIRMED", "o5_status": "PASS",
        "entry_queue_ahead": 40.0, "entry_feasible": True, "entry_reject_reason": None,
    }
    base.update(over)
    return base


def _outcome(setup_id, status="WIN", pnl=6.25):
    return {"setup_id": setup_id, "status": status,
            "pnl_usd": pnl if status in ("WIN", "LOSS") else None,
            "pnl_ticks": (pnl / 1.25) if status in ("WIN", "LOSS") else None,
            "entry_fill_price": 5000.0 if status != "NO_FILL" else None,
            "exit_reason": "TP" if status == "WIN" else ("SL" if status == "LOSS" else None)}


# ---------------------------------------------------------------------------
# Append-only — garanti par le moteur, pas par convention
# ---------------------------------------------------------------------------

def test_le_journal_est_APPEND_ONLY_au_niveau_SQLite(journal):
    journal.record_armed(_armed("s-1"))
    conn = journal._store._conn
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE setup_journal SET setup_id = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM setup_journal")


def test_un_armement_sans_setup_id_est_REFUSE(journal):
    with pytest.raises(ValueError):
        journal.record_armed({"instrument": "MES"})
    with pytest.raises(ValueError):
        journal.record_outcome({"status": "WIN"})


def test_l_issue_est_un_event_ULTERIEUR_qui_reference_l_armement(journal):
    journal.record_armed(_armed("s-1"))
    journal.record_outcome(_outcome("s-1"))
    events = journal._store.setup_entries()
    assert [e["kind"] for e in events] == ["setup_armed", "setup_outcome"]
    assert all(e["setup_id"] == "s-1" for e in events)
    assert events[0]["seq"] < events[1]["seq"], "l'ordre est porté par seq, pas par ts"


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def test_la_projection_apparie_armement_et_issue(journal):
    journal.record_armed(_armed("s-1"))
    journal.record_outcome(_outcome("s-1", "WIN", 6.25))
    rows = journal.projection()
    assert len(rows) == 1
    assert rows[0]["outcome_status"] == "WIN" and rows[0]["pnl_usd"] == 6.25
    assert rows[0]["o1_status"] == "PASS", "les balises de l'armement sont conservées"


def test_un_setup_SANS_issue_reste_PENDING_jamais_un_resultat_neutre(journal):
    journal.record_armed(_armed("s-1"))
    row = journal.projection()[0]
    assert row["outcome_status"] == "PENDING"
    assert row.get("pnl_usd") is None


def test_un_SECOND_armement_ne_reecrit_pas_le_premier(journal):
    """Une double émission est une anomalie. L'écraser laisserait croire à une correction
    propre ; on garde le premier et on compte l'incident."""
    journal.record_armed(_armed("s-1", entry_price=5000.0))
    journal.record_armed(_armed("s-1", entry_price=9999.0))
    rows = journal.projection()
    assert len(rows) == 1 and rows[0]["entry_price"] == 5000.0
    assert rows[0]["_duplicates"]["armed"] == 1


def test_une_SECONDE_issue_ne_remplace_pas_la_premiere(journal):
    journal.record_armed(_armed("s-1"))
    journal.record_outcome(_outcome("s-1", "LOSS", -5.0))
    journal.record_outcome(_outcome("s-1", "WIN", 100.0))
    rows = journal.projection()
    assert rows[0]["outcome_status"] == "LOSS" and rows[0]["pnl_usd"] == -5.0
    assert rows[0]["_duplicates"]["outcome"] == 1


def test_une_issue_ORPHELINE_est_conservee_au_journal_mais_absente_de_la_projection(journal):
    journal.record_outcome(_outcome("inconnu"))
    assert journal.projection() == []
    assert len(journal._store.setup_entries()) == 1, "l'event reste au journal, immuable"


# ---------------------------------------------------------------------------
# Export CSV
# ---------------------------------------------------------------------------

def test_les_colonnes_CSV_sont_FIXES_et_ordonnees(journal):
    journal.record_armed(_armed("s-1"))
    header = journal.to_csv().splitlines()[0]
    assert header == ",".join(CSV_COLUMNS)


def test_un_None_s_exporte_VIDE_jamais_en_chaine_None(journal):
    """« None » dans un CSV se relit comme une valeur, et fausserait toute reprise en pandas."""
    journal.record_armed(_armed("s-1", o1_gex_local=None))
    lines = journal.to_csv().splitlines()
    assert "None" not in lines[1]
    assert ",," in lines[1]


def test_l_export_ecrit_le_fichier_demande(journal, tmp_path):
    journal.record_armed(_armed("s-1"))
    path = tmp_path / "setups.csv"
    journal.to_csv(str(path))
    assert path.read_text(encoding="utf-8").startswith("setup_id,")


def test_un_journal_VIDE_exporte_son_entete_seule(journal):
    assert journal.to_csv().strip() == ",".join(CSV_COLUMNS)


# ---------------------------------------------------------------------------
# LA matrice de calibration — la question de P2
# ---------------------------------------------------------------------------

def _fill(journal, n, *, o1_status, status, pnl=6.25, offset=0):
    for i in range(n):
        sid = f"{o1_status}-{status}-{i + offset}"
        journal.record_armed(_armed(sid, o1_status=o1_status))
        journal.record_outcome(_outcome(sid, status, pnl))


def test_la_matrice_compare_PASS_et_FLAG_sur_la_meme_balise(journal):
    """La question de P2, posée en une assertion : le taux de réussite est-il dégradé sous
    `FLAG_STRONG` ? La matrice le montre ; elle ne le conclut pas."""
    _fill(journal, 8, o1_status="PASS", status="WIN")
    _fill(journal, 2, o1_status="PASS", status="LOSS", pnl=-5.0)
    _fill(journal, 3, o1_status="FLAG_STRONG", status="WIN")
    _fill(journal, 7, o1_status="FLAG_STRONG", status="LOSS", pnl=-5.0)

    matrix = journal.calibration_matrix(min_cell_sample=10)["by_gate"]["o1"]
    assert matrix["PASS"]["win_rate"] == pytest.approx(0.8)
    assert matrix["FLAG_STRONG"]["win_rate"] == pytest.approx(0.3)
    assert matrix["PASS"]["status"] == "OK" and matrix["FLAG_STRONG"]["status"] == "OK"


def test_sous_l_echantillon_minimal_AUCUN_taux_n_est_publie(journal):
    """Un taux de réussite sur trois trades n'est pas une mesure, c'est du bruit avec une
    décimale."""
    _fill(journal, 3, o1_status="FLAG_WEAK", status="WIN")
    cell = journal.calibration_matrix(min_cell_sample=10)["by_gate"]["o1"]["FLAG_WEAK"]
    assert cell["settled"] == 3
    assert cell["win_rate"] is None and cell["status"] == "INSUFFICIENT_DATA"
    assert cell["avg_pnl_usd"] is None


def test_les_NO_FILL_sortent_du_denominateur_mais_sont_REMONTES(journal):
    """« La stratégie gagne-t-elle ? » et « les entrées sont-elles servies ? » sont deux
    questions distinctes ; les mélanger rend les deux illisibles."""
    _fill(journal, 10, o1_status="PASS", status="WIN")
    _fill(journal, 10, o1_status="PASS", status="NO_FILL", offset=100)
    cell = journal.calibration_matrix(min_cell_sample=10)["by_gate"]["o1"]["PASS"]
    assert cell["setups"] == 20 and cell["settled"] == 10
    assert cell["win_rate"] == pytest.approx(1.0), "10 gagnants sur 10 trades PRIS"
    assert cell["no_fill"] == 10 and cell["no_fill_rate"] == pytest.approx(0.5)


def test_les_PENDING_ne_font_pas_baisser_le_taux_de_non_remplissage(journal):
    """Sinon il baisserait mécaniquement à chaque armement, sans qu'aucune entrée n'ait été
    servie ni refusée."""
    _fill(journal, 5, o1_status="PASS", status="NO_FILL")
    for i in range(15):
        journal.record_armed(_armed(f"pending-{i}"))
    cell = journal.calibration_matrix()["overall"]
    assert cell["pending"] == 15 and cell["no_fill"] == 5
    assert cell["no_fill_rate"] == pytest.approx(1.0), "5 non servis sur 5 RÉSOLUS"


def test_le_volet_RESULTAT_reste_masque_sous_le_seuil(journal):
    """`CLAUDE §2.7` : process et résultat jamais consolidés, résultat affiché après 20+ trades."""
    _fill(journal, config.RESULT_SCORE_MIN_TRADES - 1, o1_status="PASS", status="WIN")
    assert journal.calibration_matrix()["result_visible"] is False
    _fill(journal, 1, o1_status="PASS", status="WIN", offset=999)
    assert journal.calibration_matrix()["result_visible"] is True


def test_la_matrice_couvre_les_CINQ_balises(journal):
    journal.record_armed(_armed("s-1"))
    journal.record_outcome(_outcome("s-1"))
    by_gate = journal.calibration_matrix()["by_gate"]
    assert set(by_gate) == {"o1", "o2", "o3", "o4", "o5"}
    assert "O4_SOURCE_UNCONFIRMED" in by_gate["o4"], "O4 inerte reste une modalité mesurable"


def test_une_matrice_VIDE_ne_ment_pas(journal):
    matrix = journal.calibration_matrix()
    assert matrix["generated_from"] == 0
    assert matrix["overall"]["win_rate"] is None
    assert matrix["overall"]["no_fill_rate"] is None
    assert matrix["result_visible"] is False


def test_le_module_ne_conclut_JAMAIS_qu_une_balise_fonctionne():
    """« Le taux de réussite réel est INCONNU. La calibration doit mesurer, jamais confirmer. »
    Aucune formulation conclusive ne doit exister dans ce module."""
    import inspect

    from app import setup_journal
    src = inspect.getsource(setup_journal).lower()
    for interdit in ("has_edge", "is_profitable", "works", "edge_confirmed", "validated_gate"):
        assert interdit not in src


# ---------------------------------------------------------------------------
# La chaîne complète : L4 → journal → harnais → matrice
# ---------------------------------------------------------------------------

def test_la_chaine_L4_puis_harnais_alimente_la_matrice(journal):
    """Bout-en-bout sur les vrais objets : l'entrée produite par L4 et l'issue produite par le
    harnais de rejeu s'apparient sans adaptateur."""
    from app.execution_sim import Book, BookLevel
    from app.gates_journal import evaluate_at_arming
    from app.options_context import ContextHealth, OptionsContextSnapshot
    from app.replay_harness import Outcome

    snapshot = OptionsContextSnapshot(
        health=ContextHealth.OK,
        raw={"status": "OK", "gexLocalByStrike": {"5000": 200.0}, "gammaZeroEs": 5010.0,
             "putWallEs": 4990.0, "callWallEs": 5020.0,
             "netDriftCrossover": {"direction": "up", "ts": 1, "sourceConfirmed": False},
             "conversionFactorUsed": 1.0, "computedAt": 1, "sourceVendor": "mock"},
        age_s=1.0)
    manifest = {"id": "m-7", "instrument": "MES", "direction": "LONG",
                "entry": {"price": 5000.0},
                "risk": {"stopLoss": 4999.0, "takeProfit": 5001.25, "positionSize": 1}}
    book = Book(bids=(BookLevel(5000.0, 40.0),), asks=(BookLevel(5000.25, 10.0),))

    entry = evaluate_at_arming(manifest, options_snapshot=snapshot, es_bars=[], book=book,
                               now_ms=1_000.0)
    journal.record_armed(entry)
    journal.record_outcome(Outcome(setup_id="m-7", status="NO_FILL",
                                   entry_queue_ahead=40.0).as_event())

    row = journal.projection()[0]
    assert row["setup_id"] == "m-7" and row["outcome_status"] == "NO_FILL"
    assert row["o1_status"] == "PASS" and row["o4_status"] == "O4_SOURCE_UNCONFIRMED"
    assert row["entry_queue_ahead"] == 40.0
    csv_out = journal.to_csv().splitlines()
    assert len(csv_out) == 2 and csv_out[1].startswith("m-7,")
