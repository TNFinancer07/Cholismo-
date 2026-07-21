"""Feature — Moteur Macro & Risk Guard (D-040).

Approche déterministe figée AVANT implémentation (Loop 1 étape 3) :
- `build_macro_calendar` : normalise les publications éco (ts, name, country, currency, impact ∈
  HIGH|MED|LOW, consensus, previous, actual), calcule `surprise = actual − consensus` (si les deux
  finis), trie chronologiquement, borne. Fail-closed (§3) : ts non-fini / impact invalide / name
  vide → événement écarté ; consensus/actual absent → None (jamais une surprise inventée).
- `compute_macro_risk` (LE RISK GUARD déterministe, câblé à Phase 0 §2.2) : régime selon la
  proximité des annonces HIGH impact vs `now` — EXECUTION_PAUSED si un HIGH est dans la fenêtre
  BLACKOUT symétrique |Δ| ≤ pause ; WARNING si un HIGH approche (pause < Δ ≤ warn) ; NORMAL sinon.
  MED/LOW n'enclenchent jamais le garde. `event`/`seconds_until` = l'annonce qui pilote le régime.
- OBSERVATION seule (§2.1) : le garde ENREGISTRE un régime, ne passe jamais d'ordre.
"""
from app.macro_risk import build_macro_calendar, compute_macro_risk

PAUSE, WARN, GRACE = 900.0, 1800.0, 1800.0   # 15 min / 30 min / grâce passé


def _ev(ts, name="CPI", impact="HIGH", country="US", currency="USD",
        consensus=None, previous=None, actual=None):
    return {"ts": ts, "name": name, "impact": impact, "country": country,
            "currency": currency, "consensus": consensus, "previous": previous, "actual": actual}


def _cal(raw, now=0.0):
    return build_macro_calendar(raw, now, GRACE, 20)


def _risk(raw_events, now=0.0):
    return compute_macro_risk(raw_events, now, PAUSE, WARN)


# ---------- calendrier ----------

def test_surprise_actual_minus_consensus():
    ev = _cal([_ev(100, consensus=3.1, previous=3.0, actual=3.4)])["events"][0]
    assert round(ev["surprise"], 2) == 0.3 and ev["consensus"] == 3.1 and ev["actual"] == 3.4


def test_surprise_none_when_actual_or_consensus_missing():
    assert _cal([_ev(100, consensus=3.1, actual=None)])["events"][0]["surprise"] is None
    assert _cal([_ev(100, consensus=None, actual=3.4)])["events"][0]["surprise"] is None


def test_sorted_chronologically():
    cal = _cal([_ev(300, name="C"), _ev(100, name="A"), _ev(200, name="B")])
    assert [e["name"] for e in cal["events"]] == ["A", "B", "C"]


def test_invalid_impact_dropped():
    cal = _cal([_ev(100, name="OK", impact="HIGH"), _ev(200, name="BAD", impact="EXTREME")])
    assert [e["name"] for e in cal["events"]] == ["OK"]


def test_fail_closed_non_finite_ts_and_empty_name_dropped():
    cal = _cal([_ev(float("nan"), name="X"), _ev(100, name=""), _ev(120, name="OK")])
    assert [e["name"] for e in cal["events"]] == ["OK"]


def test_non_finite_numbers_become_none():
    ev = _cal([_ev(100, consensus=float("inf"), previous=float("nan"), actual=3.0)])["events"][0]
    assert ev["consensus"] is None and ev["previous"] is None and ev["actual"] == 3.0


def test_past_grace_drops_old_events():
    # un événement trop ancien (au-delà de la grâce) est écarté ; le récent reste
    cal = _cal([_ev(-5000, name="OLD"), _ev(-100, name="RECENT"), _ev(500, name="SOON")], now=0.0)
    assert [e["name"] for e in cal["events"]] == ["RECENT", "SOON"]


# ---------- risk guard : détection des fenêtres ----------

def test_normal_when_no_high_near():
    assert _risk([_ev(10000, impact="HIGH")])["regime"] == "NORMAL"      # Δ 10000 > warn


def test_warning_when_high_approaching():
    r = _risk([_ev(1200, impact="HIGH", name="NFP")])                    # pause(900) < Δ1200 ≤ warn(1800)
    assert r["regime"] == "WARNING" and r["event"]["name"] == "NFP" and r["seconds_until"] == 1200


def test_paused_when_high_in_blackout_before():
    r = _risk([_ev(300, impact="HIGH", name="FOMC")])                    # 0 < Δ300 ≤ pause(900)
    assert r["regime"] == "EXECUTION_PAUSED" and r["event"]["name"] == "FOMC" and r["in_window"] is True


def test_paused_when_high_in_blackout_after_release():
    # blackout SYMÉTRIQUE : juste après la publication (Δ négatif dans −pause) → toujours PAUSED
    assert _risk([_ev(-300, impact="HIGH")])["regime"] == "EXECUTION_PAUSED"


def test_normal_after_blackout_passed():
    assert _risk([_ev(-1000, impact="HIGH")])["regime"] == "NORMAL"      # Δ −1000 < −pause


def test_med_low_never_trigger_guard():
    assert _risk([_ev(60, impact="MED"), _ev(120, impact="LOW")])["regime"] == "NORMAL"


def test_paused_takes_priority_over_warning():
    r = _risk([_ev(1500, impact="HIGH", name="WARN_ONE"), _ev(200, impact="HIGH", name="BLACKOUT")])
    assert r["regime"] == "EXECUTION_PAUSED" and r["event"]["name"] == "BLACKOUT"


def test_driving_event_is_nearest_upcoming_high_when_normal():
    r = _risk([_ev(9000, impact="HIGH", name="FAR"), _ev(5000, impact="HIGH", name="NEAR")])
    assert r["regime"] == "NORMAL" and r["event"]["name"] == "NEAR" and r["seconds_until"] == 5000


def test_fail_closed_empty_and_non_finite():
    assert _risk([])["regime"] == "NORMAL" and _risk([])["event"] is None
    assert _risk([_ev(float("nan"), impact="HIGH")])["regime"] == "NORMAL"


# ---------- câblage Phase 0 (verrou unique §2.2) ----------

def _phase0(events):
    from app.meta import Freshness, MetaField
    from app.phase0 import Phase0Input, evaluate_phase0
    from app.schema import ContextSchema
    schema = ContextSchema()
    schema.macro_calendar = MetaField(value={"events": events}, freshness=Freshness.FRESH)
    inp = Phase0Input(schema=schema, streak=0, streak_audit_acked=False,
                      redis_up=True, engine_heartbeat_age=0.0, now=0.0)
    return evaluate_phase0(inp, rms=0.0)


def test_phase0_macro_blackout_blocks_when_high_in_window():
    state, blockers, _ = _phase0([_ev(200, impact="HIGH", name="FOMC")])   # |Δ| 200 ≤ pause
    from app.schema import Phase0State
    assert state == Phase0State.BLOCKED
    assert any(b.rule == "MACRO_BLACKOUT" for b in blockers)               # LE blocker macro présent


def test_phase0_no_macro_blocker_when_high_far():
    _, blockers, _ = _phase0([_ev(10000, impact="HIGH")])                  # Δ 10000 > warn → NORMAL
    assert not any(b.rule == "MACRO_BLACKOUT" for b in blockers)           # macro ne bloque pas
