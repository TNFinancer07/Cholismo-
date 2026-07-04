"""Scenarios (TASKS 2.3) — Calme · News EUR Tier 1 · Streak loss · VIX spike · Custom.

Each scenario = base market values + pathology intensities (CLAUDE §4). Custom exposes the
VIX/CHOP/CVD/GEX/RMS sliders. Pathology probabilities are per-tick, per-source.
"""
from __future__ import annotations

from typing import Any

# Pathology knobs: drop (missing ticks), late (delayed data), nan (NaN values),
# desync (clock offset on last_update_ts), contradict (cross-source divergence).
DEFAULT_PATHOLOGIES = {
    "drop_p": 0.03, "late_p": 0.05, "late_range": (2.0, 10.0),
    "nan_p": 0.01, "desync_p": 0.02, "desync_range": (-20.0, 20.0),
    "contradict_p": 0.03,
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "calme": {
        "label": "Calme",
        "base": {"vix": 14.0, "vvix": 92.0, "chop": 38.0, "cvd": 420.0, "gex": 2.4e9,
                 "rms": 1.0, "svs": 68.0, "eurusd": 1.085, "dxy": 104.2, "real_rates": 1.6,
                 "aggressor": 0.58, "es": 5450.0},
        "vol": 0.4,
        "pathologies": {**DEFAULT_PATHOLOGIES, "drop_p": 0.01, "late_p": 0.02, "nan_p": 0.005},
        "simulated_streak": 0,
    },
    "news_eur_tier1": {
        "label": "News EUR Tier 1",
        "base": {"vix": 22.0, "vvix": 112.0, "chop": 55.0, "cvd": -900.0, "gex": 0.6e9,
                 "rms": 3.0, "svs": 44.0, "eurusd": 1.0980, "dxy": 103.1, "real_rates": 1.9,
                 "aggressor": 0.31, "es": 5410.0},
        "vol": 2.2,
        "pathologies": {**DEFAULT_PATHOLOGIES, "late_p": 0.18, "late_range": (3.0, 15.0),
                        "contradict_p": 0.15, "drop_p": 0.08},
        "simulated_streak": 0,
    },
    "streak_loss": {
        "label": "Streak loss",
        "base": {"vix": 18.0, "vvix": 101.0, "chop": 58.0, "cvd": -620.0, "gex": 1.1e9,
                 "rms": 4.0, "svs": 38.0, "eurusd": 1.079, "dxy": 104.9, "real_rates": 1.75,
                 "aggressor": 0.42, "es": 5395.0},
        "vol": 1.0,
        "pathologies": DEFAULT_PATHOLOGIES,
        # 7 = one before the forced-audit threshold of 8 (PRD §C2: proximity visible).
        "simulated_streak": 7,
    },
    "vix_spike": {
        "label": "VIX spike",
        "base": {"vix": 34.0, "vvix": 142.0, "chop": 66.0, "cvd": -1800.0, "gex": -0.8e9,
                 "rms": 5.0, "svs": 22.0, "eurusd": 1.062, "dxy": 106.8, "real_rates": 2.3,
                 "aggressor": 0.18, "es": 5290.0},
        "vol": 3.5,
        "pathologies": {**DEFAULT_PATHOLOGIES, "drop_p": 0.15, "late_p": 0.20, "nan_p": 0.04,
                        "desync_p": 0.08},
        "simulated_streak": 3,
    },
    "custom": {
        "label": "Custom (sliders)",
        "base": {"vix": 16.0, "vvix": 95.0, "chop": 45.0, "cvd": 0.0, "gex": 1.5e9,
                 "rms": 2.0, "svs": 55.0, "eurusd": 1.085, "dxy": 104.0, "real_rates": 1.7,
                 "aggressor": 0.5, "es": 5430.0},
        "vol": 0.8,
        "pathologies": DEFAULT_PATHOLOGIES,
        "simulated_streak": 0,
    },
}

# Custom sliders (TASKS 2.3) map onto these base fields.
SLIDER_FIELDS = ("vix", "chop", "cvd", "gex", "rms")

DEFAULT_SCENARIO = "calme"


def resolve(scenario_state: dict[str, Any] | None) -> dict[str, Any]:
    """Merge the persisted scenario state (name + sliders) with its definition."""
    name = (scenario_state or {}).get("name", DEFAULT_SCENARIO)
    definition = SCENARIOS.get(name, SCENARIOS[DEFAULT_SCENARIO])
    base = dict(definition["base"])
    sliders = (scenario_state or {}).get("sliders") or {}
    for field in SLIDER_FIELDS:
        if sliders.get(field) is not None:
            base[field] = float(sliders[field])
    # Demo scenarios simulate an active session window by default (D-020); pass
    # force_session=null in POST /scenario to use the real clock.
    force_session = (scenario_state or {}).get("force_session", "OVERLAP_NY")
    return {
        "name": name,
        "label": definition["label"],
        "base": base,
        "vol": definition["vol"],
        "pathologies": definition["pathologies"],
        "simulated_streak": int((scenario_state or {}).get("simulated_streak",
                                                           definition["simulated_streak"])),
        "force_session": force_session,
    }
