"""Feature — Cortex Cognitif / bias_detector (D-035, Axe 4).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- ANALYTIQUE post-hoc sur les CompletedTrades — ne bloque ni ne modifie JAMAIS le flux
  d'exécution (§2.1), aucun LLM (déterministe), fail-closed (§3) ;
- 3 détecteurs déterministes :
  1) FOMO : durée anormalement courte (< seuil) ET anomalie de delta à l'entrée ;
  2) EXEC_TOO_LONG : durée > seuil critique max ;
  3) REVENGE : trade initié < 3 min après la clôture d'une PERTE ;
- Psych-Score /100 = score de PROCESSUS (discipline) = % de trades sans biais ; None si aucun
  trade (jamais un faux 100). Process ≠ result (§2.7) : n'est PAS le P&L.
"""
from app.bias_detector import BiasFinding, detect_biases, discipline_report
from app.config import EXEC_MAX_DURATION_S, FOMO_MAX_DURATION_S, REVENGE_WINDOW_S


def _t(**kw) -> dict:
    """Un CompletedTrade dumpé (comme renvoyé par reconcile_fills)."""
    base = dict(instrument="ES 12-24", root="ES", direction="LONG", quantity=1,
                entry_price=5000.0, exit_price=5010.0, entry_ts=0.0, exit_ts=60.0,
                exposure_seconds=60.0, pnl_points=10.0, point_value=50.0, pnl_usd=500.0,
                r_multiple=5.0, entry_delta_anomaly=False)
    base.update(kw)
    return base


def test_revenge_window_is_authority_3min():
    assert REVENGE_WINDOW_S == 180.0            # AUTORITÉ (spec : < 3 min)


# ---------- FOMO ----------

def test_fomo_short_duration_after_delta_anomaly():
    f = detect_biases([_t(exposure_seconds=10.0, entry_delta_anomaly=True)])
    assert any(b.type == "FOMO" for b in f)


def test_fomo_requires_delta_anomaly_failclosed():
    # durée courte MAIS pas d'anomalie de delta connue → PAS de FOMO (jamais inventé, §3)
    f = detect_biases([_t(exposure_seconds=10.0, entry_delta_anomaly=False)])
    assert not any(b.type == "FOMO" for b in f)


def test_fomo_normal_duration_no_flag():
    f = detect_biases([_t(exposure_seconds=FOMO_MAX_DURATION_S + 50, entry_delta_anomaly=True)])
    assert not any(b.type == "FOMO" for b in f)


# ---------- Exécution trop longue ----------

def test_exec_too_long_over_threshold():
    f = detect_biases([_t(exposure_seconds=EXEC_MAX_DURATION_S + 1)])
    assert any(b.type == "EXEC_TOO_LONG" for b in f)


def test_exec_within_limit_no_flag():
    f = detect_biases([_t(exposure_seconds=EXEC_MAX_DURATION_S - 1)])
    assert not any(b.type == "EXEC_TOO_LONG" for b in f)


# ---------- Revenge trading ----------

def test_revenge_trade_within_3min_of_a_loss():
    loss = _t(entry_ts=0.0, exit_ts=100.0, pnl_usd=-250.0, r_multiple=-2.5, exit_price=4990.0)
    revenge = _t(entry_ts=160.0, exit_ts=300.0)          # 60 s après la clôture de la perte
    f = detect_biases([loss, revenge])
    flags = [b for b in f if b.type == "REVENGE"]
    assert len(flags) == 1 and flags[0].trade_index == 1


def test_no_revenge_if_gap_over_3min():
    loss = _t(entry_ts=0.0, exit_ts=100.0, pnl_usd=-250.0)
    later = _t(entry_ts=100.0 + REVENGE_WINDOW_S + 10, exit_ts=900.0)
    f = detect_biases([loss, later])
    assert not any(b.type == "REVENGE" for b in f)


def test_no_revenge_after_a_win():
    win = _t(entry_ts=0.0, exit_ts=100.0, pnl_usd=+500.0)
    nxt = _t(entry_ts=160.0, exit_ts=300.0)              # 60 s après un GAIN → pas revenge
    f = detect_biases([win, nxt])
    assert not any(b.type == "REVENGE" for b in f)


# ---------- Psych-Score ----------

def test_discipline_report_perfect_score():
    r = discipline_report([_t(exposure_seconds=600.0)])   # aucun biais
    assert r["psych_score"] == 100 and r["biased_trades"] == 0 and r["clean_trades"] == 1


def test_discipline_report_penalizes_biases():
    trades = [_t(exposure_seconds=600.0),                                   # clean
              _t(exposure_seconds=5.0, entry_delta_anomaly=True)]           # FOMO
    r = discipline_report(trades)
    assert r["total_trades"] == 2 and r["biased_trades"] == 1 and r["clean_trades"] == 1
    assert r["psych_score"] == 50
    assert r["biases_by_type"].get("FOMO") == 1
    assert len(r["biases"]) == 1 and r["biases"][0]["type"] == "FOMO"


def test_one_trade_multiple_biases_counts_once_in_biased_trades():
    # un seul trade portant 2 biais → 1 seul trade biaisé, 2 findings
    trades = [_t(entry_ts=0.0, exit_ts=100.0, pnl_usd=-250.0),              # perte préalable
              _t(entry_ts=120.0, exit_ts=EXEC_MAX_DURATION_S + 200,
                 exposure_seconds=EXEC_MAX_DURATION_S + 80)]                # revenge + trop long
    r = discipline_report(trades)
    types = {b["type"] for b in r["biases"] if b["trade_index"] == 1}
    assert {"REVENGE", "EXEC_TOO_LONG"} <= types
    assert r["biased_trades"] == 1                                          # compté une fois


def test_discipline_report_empty_is_none_not_fake():
    r = discipline_report([])
    assert r["psych_score"] is None and r["total_trades"] == 0              # fail-closed, pas de faux 100


def test_findings_are_serialisable():
    f = detect_biases([_t(exposure_seconds=5.0, entry_delta_anomaly=True)])
    assert isinstance(f[0], BiasFinding)
    d = discipline_report([_t(exposure_seconds=5.0, entry_delta_anomaly=True)])["biases"][0]
    assert set(d) >= {"type", "trade_index", "instrument", "entry_ts", "exposure_seconds", "detail"}
