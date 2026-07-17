"""Feature — Trade Reconciliator (D-033) : moteur analytique FIFO sur l'historique des
snapshots.

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- charge les snapshots JSON, en extrait le `fill` DÉCLENCHEUR (embarqué par le log_scraper) ;
- apparie chronologiquement entrée↔sortie par instrument en **FIFO** (position nette, flips
  gérés) ;
- convertit l'écart de prix en **P&L USD** via un dictionnaire de contrats ($/point) ;
- calcule par `CompletedTrade` : durée d'exposition, P&L USD, **R-Multiple** (risque réf. 100 $) ;
- FAIL-CLOSED (§3) : fill sans côté / instrument inconnu / dossier absent → jamais un P&L
  inventé (côté manquant → non résolu ; contrat inconnu → P&L USD None, points seulement).
- ANALYTIQUE hors-ligne : lit des projections passées, ne passe jamais d'ordre (§2.1).
"""
import json
import os

from app.trade_reconciliator import (POINT_VALUE, REFERENCE_RISK_USD, Fill,
                                     analyze_trades, load_fills_from_snapshots,
                                     normalize_instrument, reconcile_fills)


def test_contract_dict_and_reference_risk():
    assert POINT_VALUE["ES"] == 50.0 and POINT_VALUE["MES"] == 5.0   # AUTORITÉ (spec)
    assert REFERENCE_RISK_USD == 100.0


def test_normalize_instrument_to_root():
    assert normalize_instrument("ES 12-24") == "ES"
    assert normalize_instrument("MES 03-25") == "MES"
    assert normalize_instrument("nq 12-24") == "NQ"          # insensible à la casse
    assert normalize_instrument("") == ""


def test_reconcile_long_trade_pnl_usd_and_r():
    fills = [Fill("ES 12-24", "BUY", 5000.0, 2, 1000.0),
             Fill("ES 12-24", "SELL", 5010.0, 2, 1300.0)]
    res = reconcile_fills(fills)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.direction == "LONG" and t.quantity == 2
    assert t.pnl_points == 10.0
    assert t.point_value == 50.0
    assert t.pnl_usd == 1000.0                                # 10 pts × 2 × 50 $
    assert t.r_multiple == 10.0                               # 1000 $ / 100 $
    assert t.exposure_seconds == 300.0


def test_reconcile_short_trade():
    fills = [Fill("ES 12-24", "SELL", 5010.0, 1, 0.0),
             Fill("ES 12-24", "BUY", 5000.0, 1, 60.0)]
    t = reconcile_fills(fills).trades[0]
    assert t.direction == "SHORT"
    assert t.pnl_points == 10.0 and t.pnl_usd == 500.0 and t.r_multiple == 5.0
    assert t.exposure_seconds == 60.0


def test_reconcile_fifo_partial_and_position_flip():
    # BUY 3 @100 → SELL 1 @110 (ferme 1) → SELL 3 @105 (ferme 2, ouvre short 1)
    fills = [Fill("MES 03-25", "BUY", 100.0, 3, 0.0),
             Fill("MES 03-25", "SELL", 110.0, 1, 10.0),
             Fill("MES 03-25", "SELL", 105.0, 3, 20.0)]
    res = reconcile_fills(fills)
    assert len(res.trades) == 2
    assert res.trades[0].quantity == 1 and res.trades[0].pnl_usd == 50.0   # 10 pts ×1 ×5
    assert res.trades[1].quantity == 2 and res.trades[1].pnl_usd == 50.0   # 5 pts ×2 ×5
    assert res.open_lots == 1                                              # short 1 restant


def test_reconcile_unknown_contract_gives_points_but_no_usd():
    fills = [Fill("XYZ 01-25", "BUY", 10.0, 1, 0.0),
             Fill("XYZ 01-25", "SELL", 12.0, 1, 5.0)]
    t = reconcile_fills(fills).trades[0]
    assert t.pnl_points == 2.0
    assert t.point_value is None and t.pnl_usd is None and t.r_multiple is None  # jamais inventé


def test_reconcile_missing_side_is_unresolved_not_invented():
    fills = [Fill("ES 12-24", None, 5000.0, 1, 0.0),         # côté inconnu → non résolu
             Fill("ES 12-24", "SELL", 5010.0, 1, 10.0)]
    res = reconcile_fills(fills)
    assert res.unresolved_fills >= 1
    assert all(t.entry_price != 5000.0 or t.direction == "SHORT" for t in res.trades)


def test_reconcile_summary_aggregates():
    fills = [Fill("ES 12-24", "BUY", 5000.0, 1, 0.0),
             Fill("ES 12-24", "SELL", 5010.0, 1, 60.0),      # +500 $
             Fill("ES 12-24", "BUY", 5010.0, 1, 120.0),
             Fill("ES 12-24", "SELL", 5005.0, 1, 180.0)]     # −250 $
    s = reconcile_fills(fills).summary
    assert s["trade_count"] == 2 and s["wins"] == 1 and s["losses"] == 1
    assert s["total_pnl_usd"] == 250.0 and s["total_r"] == 2.5


# ---------- chargement depuis snapshots ----------

def _write_snap(directory, sid, created_ts, fill):
    os.makedirs(directory, exist_ok=True)
    payload = {"snapshot_id": sid, "created_ts": created_ts, "operator": "SONY",
               "session_marker": "OVERLAP_NY", "order_book": {}, "cvd_by_level": {},
               "econ_calendar": {}, "liquidity_sweep": {}, "fill": fill}
    with open(os.path.join(directory, f"{sid}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_load_fills_from_snapshots_chronological(tmp_path):
    d = str(tmp_path)
    _write_snap(d, "snap_2000_sony", 2.0,
                {"instrument": "ES 12-24", "side": "SELL", "price": 5010.0, "quantity": 1, "ts": 2.0})
    _write_snap(d, "snap_1000_sony", 1.0,
                {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 1, "ts": 1.0})
    fills = load_fills_from_snapshots(d)
    assert len(fills) == 2
    assert fills[0].ts == 1.0 and fills[1].ts == 2.0         # trié chronologiquement
    assert fills[0].side == "BUY"


def test_load_skips_context_only_snapshots(tmp_path):
    d = str(tmp_path)
    _write_snap(d, "snap_1000_sony", 1.0,
                {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 1, "ts": 1.0})
    _write_snap(d, "snap_2000_sony", 2.0, None)              # capture de contexte, sans fill
    assert len(load_fills_from_snapshots(d)) == 1


def test_load_absent_dir_is_empty(tmp_path):
    assert load_fills_from_snapshots(str(tmp_path / "n_existe_pas")) == []


# ---------- Cortex Cognitif — enrichissement + psych (D-035) ----------

def _write_snap_sweep(directory, sid, ts, fill, triggered):
    payload = {"snapshot_id": sid, "created_ts": ts, "operator": "SONY", "session_marker": "X",
               "order_book": {}, "cvd_by_level": {}, "econ_calendar": {},
               "liquidity_sweep": {"triggered": triggered}, "fill": fill}
    with open(os.path.join(directory, f"{sid}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_load_extracts_entry_delta_anomaly_from_sweep(tmp_path):
    d = str(tmp_path)
    _write_snap_sweep(d, "snap_1000_sony", 1.0,
                      {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 1, "ts": 1.0},
                      triggered=True)
    fills = load_fills_from_snapshots(d)
    assert fills[0].delta_anomaly is True


def test_reconcile_carries_entry_anomaly_into_trade():
    fills = [Fill("ES 12-24", "BUY", 5000.0, 1, 0.0, delta_anomaly=True),
             Fill("ES 12-24", "SELL", 5010.0, 1, 5.0, delta_anomaly=False)]
    t = reconcile_fills(fills).trades[0]
    assert t.entry_delta_anomaly is True         # l'anomalie de l'ENTRÉE, pas de la sortie


def test_analyze_trades_includes_discipline_and_flags_fomo(tmp_path):
    d = str(tmp_path)
    # entrée sur sweep + tenue très courte (5 s) → FOMO ; le payload porte le Psych-Score
    _write_snap_sweep(d, "snap_1000_sony", 1.0,
                      {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 1, "ts": 1.0},
                      triggered=True)
    _write_snap_sweep(d, "snap_1006_sony", 6.0,
                      {"instrument": "ES 12-24", "side": "SELL", "price": 5010.0, "quantity": 1, "ts": 6.0},
                      triggered=False)
    res = analyze_trades(d)
    assert "discipline" in res
    assert res["discipline"]["psych_score"] == 0          # 1 trade, biaisé → 0 % discipliné
    assert res["discipline"]["biases_by_type"].get("FOMO") == 1
    assert res["trades"][0]["entry_delta_anomaly"] is True


# ---------- /devil (D-033) : durcissement ----------

def test_reconcile_out_of_order_timestamps_are_sorted():
    # la SORTIE est fournie avant l'ENTRÉE dans la liste → tri interne par ts avant FIFO
    fills = [Fill("ES 12-24", "SELL", 5010.0, 1, 300.0),
             Fill("ES 12-24", "BUY", 5000.0, 1, 0.0)]
    t = reconcile_fills(fills).trades[0]
    assert t.direction == "LONG" and t.entry_ts == 0.0 and t.exit_ts == 300.0
    assert t.pnl_usd == 500.0 and t.exposure_seconds == 300.0


def test_reconcile_orphan_position_not_closed_no_fabrication():
    res = reconcile_fills([Fill("ES 12-24", "BUY", 5000.0, 2, 0.0)])   # BUY sans SELL
    assert res.trades == []                                           # aucun trade inventé
    assert res.open_lots == 1 and res.summary["open_lots"] == 1


def test_reconcile_negative_or_zero_quantity_is_unresolved():
    res = reconcile_fills([Fill("ES 12-24", "BUY", 5000.0, -2, 0.0),
                           Fill("ES 12-24", "SELL", 5010.0, 0, 10.0)])
    assert res.trades == [] and res.unresolved_fills == 2


def test_reconcile_ts_none_is_unresolved_not_crash():
    res = reconcile_fills([Fill("ES 12-24", "BUY", 5000.0, 1, None),   # pas d'horodatage
                           Fill("ES 12-24", "SELL", 5010.0, 1, 10.0)])
    assert res.unresolved_fills >= 1                                  # trié sans crash


def test_reconcile_zero_reference_risk_gives_none_r(monkeypatch):
    import app.trade_reconciliator as tr
    monkeypatch.setattr(tr, "REFERENCE_RISK_USD", 0.0)
    res = tr.reconcile_fills([Fill("ES 12-24", "BUY", 5000.0, 1, 0.0),
                              Fill("ES 12-24", "SELL", 5010.0, 1, 10.0)])
    assert res.trades[0].pnl_usd == 500.0                            # P&L $ calculable
    assert res.trades[0].r_multiple is None                         # R indéfini si risque 0 → None
    assert res.summary["total_r"] == 0.0                            # somme robuste, pas de crash


def test_load_skips_corrupt_or_non_object_json(tmp_path):
    d = str(tmp_path)
    with open(os.path.join(d, "snap_1_sony.json"), "w") as f:
        f.write("{ pas du json ]")                                  # syntaxe invalide
    with open(os.path.join(d, "snap_2_sony.json"), "w") as f:
        f.write("[1, 2, 3]")                                        # JSON valide mais pas un objet
    _write_snap(d, "snap_3_sony", 3.0,
                {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 1, "ts": 3.0})
    fills = load_fills_from_snapshots(d)
    assert len(fills) == 1 and fills[0].price == 5000.0             # seul le sain chargé, pas de crash


def test_load_skips_fill_with_nonnumeric_values(tmp_path):
    d = str(tmp_path)
    _write_snap(d, "snap_1_sony", 1.0,
                {"instrument": "ES 12-24", "side": "BUY", "price": "abc", "quantity": 1, "ts": 1.0})
    _write_snap(d, "snap_2_sony", 2.0,
                {"instrument": "ES 12-24", "side": "SELL", "price": 5010.0, "quantity": "xx", "ts": 2.0})
    assert load_fills_from_snapshots(d) == []                       # valeurs corrompues → écartées


def test_load_deterministic_order_on_timestamp_tie(tmp_path):
    d = str(tmp_path)
    _write_snap(d, "snap_2000_sony", 5.0,                           # même ts que l'autre
                {"instrument": "ES 12-24", "side": "SELL", "price": 5010.0, "quantity": 1, "ts": 5.0})
    _write_snap(d, "snap_1000_sony", 5.0,
                {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 1, "ts": 5.0})
    fills = load_fills_from_snapshots(d)
    # départage par snapshot_id (déterministe, indépendant de l'ordre listdir du FS)
    assert [f.side for f in fills] == ["BUY", "SELL"]
    assert reconcile_fills(fills).trades[0].direction == "LONG"


def test_analyze_unknown_instrument_is_endpoint_safe(tmp_path):
    d = str(tmp_path)
    _write_snap(d, "snap_1_sony", 1.0,
                {"instrument": "XYZ 01-25", "side": "BUY", "price": 10.0, "quantity": 1, "ts": 1.0})
    _write_snap(d, "snap_2_sony", 2.0,
                {"instrument": "XYZ 01-25", "side": "SELL", "price": 12.0, "quantity": 1, "ts": 2.0})
    res = analyze_trades(d)                                         # ne crashe pas
    t = res["trades"][0]
    assert t["pnl_points"] == 2.0 and t["pnl_usd"] is None and t["r_multiple"] is None


def test_analyze_trades_end_to_end(tmp_path):
    d = str(tmp_path)
    _write_snap(d, "snap_1000_sony", 1.0,
                {"instrument": "ES 12-24", "side": "BUY", "price": 5000.0, "quantity": 2, "ts": 1.0})
    _write_snap(d, "snap_1300_sony", 300.0,
                {"instrument": "ES 12-24", "side": "SELL", "price": 5010.0, "quantity": 2, "ts": 300.0})
    res = analyze_trades(d)
    assert res["fills_loaded"] == 2
    assert res["summary"]["trade_count"] == 1
    assert res["trades"][0]["pnl_usd"] == 1000.0
    assert res["trades"][0]["r_multiple"] == 10.0
    assert res["trades"][0]["exposure_seconds"] == 299.0
