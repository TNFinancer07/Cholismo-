"""D-121 — normalisation des exports fournisseur.

Les tests portent surtout sur les REFUS : c'est là que le brouillon d'origine se serait fait
avoir, et un mappage qui marche sur le cas nominal mais avale un format inconnu ne vaut rien.
"""
from __future__ import annotations

import pytest

from app.mbo import ingest, vendor_schema as vs
from app.mbo.events import MboAction, MboSide


def _tradovate_row(**over):
    row = {"timestamp": "2025-03-03T14:30:00.000000+00:00", "orderId": 42, "action": "Add",
           "side": "Buy", "price": 5012.25, "qty": 3}
    row.update(over)
    return row


def _rithmic_row(**over):
    row = {"Date Time": "2025-03-03T14:30:00+00:00", "Order ID": 7, "Type": "A",
           "BS": "B", "Price": 5012.25, "Volume": 3}
    row.update(over)
    return row


# --- détection -------------------------------------------------------------------------------

def test_detecte_tradovate_et_rithmic():
    assert vs.detect_source(_tradovate_row().keys()) == vs.SOURCE_TRADOVATE
    assert vs.detect_source(_rithmic_row().keys()) == vs.SOURCE_RITHMIC
    assert vs.detect_source(("ts_event", "order_id", "price")) == vs.SOURCE_DATABENTO


def test_source_inconnue_REFUSE_au_lieu_de_laisser_passer():
    """Le défaut central du brouillon : rendre l'entrée inchangée laisserait croire qu'elle était
    déjà au bon format, et l'échec sortirait trois couches plus loin sans rapport."""
    with pytest.raises(vs.VendorSchemaError, match="indétectable"):
        vs.detect_source(("colonne_a", "colonne_b"))


def test_source_ambigue_REFUSE_plutot_que_de_choisir():
    melange = {"ts_event": 1, "order_id": 1, "timestamp": 1, "orderId": 1}
    with pytest.raises(vs.VendorSchemaError, match="ambiguë"):
        vs.detect_source(melange.keys())


def test_source_explicite_inconnue_leve():
    with pytest.raises(vs.VendorSchemaError, match="inconnue"):
        vs.normalize_order_flow_schema([_tradovate_row()], source_type="bookmap")


# --- horodatage : l'invariant entier ---------------------------------------------------------

def test_ts_event_reste_un_ENTIER_de_nanosecondes():
    """`pd.to_datetime` aurait produit un datetime64 que `normalize_row` rejette en
    MISSING_TIMESTAMP — le fichier entier serait parti sans qu'une exception soit levée."""
    rows, _ = vs.normalize_order_flow_schema([_tradovate_row()])
    ts = rows[0]["ts_event"]
    assert isinstance(ts, int) and not isinstance(ts, bool)
    assert ts == 1_741_012_200_000_000_000


def test_la_conversion_ne_perd_pas_la_nanoseconde():
    """En passant par `timestamp()` flottant, l'erreur serait de ~200 ns à l'époque actuelle."""
    rows, _ = vs.normalize_order_flow_schema(
        [_tradovate_row(timestamp="2025-03-03T14:30:00.123456+00:00")])
    assert rows[0]["ts_event"] == 1_741_012_200_123_456_000


def test_un_entier_de_ns_passe_tel_quel():
    rows, _ = vs.normalize_order_flow_schema([_tradovate_row(timestamp=1_741_012_200_000_000_000)])
    assert rows[0]["ts_event"] == 1_741_012_200_000_000_000


def test_date_SANS_fuseau_est_rejetee():
    """La lire comme UTC décalerait toute une séance de plusieurs heures, invisiblement."""
    rows, rapport = vs.normalize_order_flow_schema([_tradovate_row(timestamp="2025-03-03 14:30:00")])
    assert rows == []
    assert rapport["rejected_by_reason"] == {"MISSING_TIMESTAMP": 1}


def test_un_flottant_de_ns_est_refuse():
    rows, rapport = vs.normalize_order_flow_schema([_tradovate_row(timestamp=1.7410122e18)])
    assert rows == [] and rapport["rejected_by_reason"] == {"MISSING_TIMESTAMP": 1}


# --- prix : la mise à l'échelle qui manquait -------------------------------------------------

def test_le_prix_est_mis_a_l_echelle_fixed_point():
    """Sans ça, `ingest.py` divise 5012.25 par 1e9 et obtient 5e-6 : fini, donc accepté, et faux
    partout en aval. Le défaut le plus discret du brouillon."""
    rows, _ = vs.normalize_order_flow_schema([_tradovate_row(price=5012.25)])
    assert rows[0]["price"] == 5_012_250_000_000
    assert rows[0]["price"] / ingest.PRICE_SCALE == pytest.approx(5012.25)


def test_prix_non_fini_rejette_la_ligne_et_le_compte():
    rows, rapport = vs.normalize_order_flow_schema([_tradovate_row(price=float("nan"))])
    assert rows == [] and rapport["rejected_by_reason"] == {"NON_FINITE_PRICE": 1}


def test_databento_n_est_PAS_remis_a_l_echelle():
    """Il EST le schéma interne : le retoucher serait un aller-retour qui ne peut que perdre."""
    brut = [{"ts_event": 1, "order_id": 2, "price": 5_012_250_000_000, "size": 1,
             "action": "A", "side": "B", "sequence": 9}]
    rows, rapport = vs.normalize_order_flow_schema(brut)
    assert rows == brut and rapport["source"] == vs.SOURCE_DATABENTO


# --- vocabulaires : rejet compté, jamais NaN -------------------------------------------------

def test_action_inconnue_REJETTE_au_lieu_de_produire_un_NaN():
    """`.map()` pandas rend NaN : la ligne survit, paraît complète, et porte un trou."""
    rows, rapport = vs.normalize_order_flow_schema([_tradovate_row(action="Replace")])
    assert rows == [] and rapport["rejected_by_reason"] == {"UNKNOWN_ACTION": 1}


def test_cote_inconnu_REJETTE_et_compte():
    rows, rapport = vs.normalize_order_flow_schema([_rithmic_row(BS="X")])
    assert rows == [] and rapport["rejected_by_reason"] == {"UNKNOWN_SIDE": 1}


def test_le_cote_NONE_est_conserve_pas_rejete():
    """Un TRADE sans côté attribué est légitime en MBO ; le rejeter jetterait des impressions
    réelles. Le brouillon d'origine ne le prévoyait pas."""
    rows, _ = vs.normalize_order_flow_schema([_tradovate_row(side="None", action="Trade")])
    assert rows[0]["side"] == MboSide.NONE and rows[0]["action"] == MboAction.TRADE


def test_les_actions_sont_TRADUITES_pas_recopiees():
    """Le brouillon n'avait aucun mappage d'action : chaque ligne serait tombée en
    UNKNOWN_ACTION, et le fichier serait revenu vide sans la moindre exception."""
    rows, _ = vs.normalize_order_flow_schema([_tradovate_row(action="Cancel")])
    assert rows[0]["action"] == MboAction.CANCEL
    rows, _ = vs.normalize_order_flow_schema([_rithmic_row(Type="MODIFY")])
    assert rows[0]["action"] == MboAction.MODIFY


# --- séquence fabriquée, et annoncée ---------------------------------------------------------

def test_sequence_absente_est_fabriquee_ET_annoncee():
    """Une séquence fabriquée ne peut pas détecter un trou de capture. Le rapport doit le dire,
    sinon on lit une continuité qui n'a jamais été observée."""
    rows, rapport = vs.normalize_order_flow_schema([_tradovate_row(), _tradovate_row()])
    assert [r["sequence"] for r in rows] == [0, 1]
    assert rapport["sequence_synthesised"] is True


def test_sequence_fournie_est_conservee():
    rows, rapport = vs.normalize_order_flow_schema([_tradovate_row(sequence=77)])
    assert rows[0]["sequence"] == 77 and rapport["sequence_synthesised"] is False


# --- colonnes et rapport ---------------------------------------------------------------------

def test_colonne_requise_absente_est_fatale_au_fichier():
    ampute = _tradovate_row()
    del ampute["price"]
    with pytest.raises(vs.VendorSchemaError, match="price"):
        vs.normalize_order_flow_schema([ampute])


def test_le_rapport_compte_les_lignes_entrantes_et_sortantes():
    rows, rapport = vs.normalize_order_flow_schema(
        [_tradovate_row(), _tradovate_row(action="Replace"), _tradovate_row()])
    assert len(rows) == 2
    assert rapport["rows_in"] == 3 and rapport["rows_out"] == 2
    assert rapport["rejected_by_reason"] == {"UNKNOWN_ACTION": 1}


def test_l_entree_n_est_jamais_mutee():
    source = _tradovate_row()
    copie = dict(source)
    vs.normalize_order_flow_schema([source])
    assert source == copie


def test_liste_vide_ne_leve_pas_avec_une_source_explicite():
    rows, rapport = vs.normalize_order_flow_schema([], source_type="tradovate")
    assert rows == [] and rapport["rows_in"] == 0


# --- bout en bout : la sortie traverse réellement `ingest.normalize_row` ----------------------

def test_la_sortie_est_ACCEPTEE_par_normalize_row():
    """Le test qui compte : deux mappages cohérents entre eux ne prouvent rien si l'ingestion les
    refuse. On confronte à la fonction qui fait autorité, pas à une idée de son contrat."""
    from app.mbo.events import IngestStats

    rows, _ = vs.normalize_order_flow_schema([_tradovate_row(), _rithmic_row()],
                                             source_type="tradovate")
    stats = IngestStats()
    event = ingest.normalize_row(rows[0], stats)
    assert event is not None, stats.rejections_by_reason
    assert event.price == pytest.approx(5012.25)
    assert event.action == MboAction.ADD and event.side == MboSide.BID
    assert stats.rows_rejected == 0


def test_toutes_les_colonnes_requises_sont_presentes_en_sortie():
    rows, _ = vs.normalize_order_flow_schema([_rithmic_row()])
    for col in ingest.REQUIRED_COLUMNS:
        assert col in rows[0], f"colonne {col} absente — `ingest_parquet` refuserait le fichier"


# --- câblage : le module a un APPELANT, et il est exercé -------------------------------------

def _ecrire_parquet(chemin, lignes):
    pq = pytest.importorskip("pyarrow.parquet")
    import pyarrow as pa
    colonnes = {cle: [ligne[cle] for ligne in lignes] for cle in lignes[0]}
    pq.write_table(pa.table(colonnes), str(chemin))


def test_ingest_parquet_traduit_un_export_tradovate(tmp_path):
    """Le piège n°5 du dépôt : « ça existe mais rien ne l'appelle ». Ce test passe par
    `ingest_parquet`, le vrai chemin de la calibration, pas par la fonction seule."""
    fichier = tmp_path / "tradovate.parquet"
    _ecrire_parquet(fichier, [_tradovate_row(), _tradovate_row(action="Cancel")])

    evenements, stats = ingest.ingest_parquet(str(fichier), source_type="tradovate")
    assert len(evenements) == 2 and stats.rows_rejected == 0
    assert evenements[0].price == pytest.approx(5012.25)
    assert [e.action for e in evenements] == [MboAction.ADD, MboAction.CANCEL]


def test_sans_source_type_le_comportement_est_INCHANGE(tmp_path):
    """Le défaut reste `None` : un export Tradovate non déclaré échoue comme avant, sur les
    colonnes manquantes. Une détection automatique implicite renommerait des colonnes que
    personne n'a demandé de toucher."""
    fichier = tmp_path / "tradovate.parquet"
    _ecrire_parquet(fichier, [_tradovate_row()])
    with pytest.raises(ingest.MboIngestError, match="colonnes requises absentes"):
        ingest.ingest_parquet(str(fichier))


def test_les_rejets_de_traduction_entrent_dans_les_MEMES_statistiques(tmp_path):
    """Un rapport qui n'additionnerait pas les deux étapes afficherait un taux de rejet flatteur."""
    fichier = tmp_path / "tradovate.parquet"
    _ecrire_parquet(fichier, [_tradovate_row(), _tradovate_row(action="Replace")])
    evenements, stats = ingest.ingest_parquet(str(fichier), source_type="tradovate")
    assert len(evenements) == 1
    assert stats.rejections_by_reason == {"UNKNOWN_ACTION": 1}


def test_la_cli_de_calibration_expose_source():
    """Sans l'option, la fonction resterait inatteignable depuis la commande réelle."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "calibration.py"
    texte = src.read_text(encoding="utf-8")
    assert '"--source"' in texte
    assert "source_type=args.source" in texte
