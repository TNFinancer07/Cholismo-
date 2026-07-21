"""Moteur Macro : calendrier des publications éco + Risk Guard déterministe (D-040).

`build_macro_calendar` normalise les publications OBSERVÉES (§2.1) — impact HIGH/MED/LOW,
consensus/previous/actual, `surprise = actual − consensus`. `compute_macro_risk` est LE garde
déterministe (CLAUDE §2.2) : il classe le régime macro selon la proximité des annonces HIGH
impact vs `now` (EXECUTION_PAUSED / WARNING / NORMAL). Ce même calcul alimente la règle Phase 0
`MACRO_BLACKOUT` (verrou UNIQUE) ET la projection `macro_risk` affichée — jamais deux logiques.

Purs et déterministes (aucun LLM, aucun état caché). FAIL-CLOSED (§3) : ts non-fini / impact
invalide / name vide → événement écarté ; nombre non-fini → None (jamais une surprise inventée).
Les fenêtres (pause ±15 min, warn) sont **v1 provisional** (config)."""
from __future__ import annotations

import math

_IMPACTS = ("HIGH", "MED", "LOW")


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _num(x):
    return float(x) if _finite(x) else None


def build_macro_calendar(raw_events, now: float, past_grace: float, max_events: int) -> dict:
    """Normalise + trie chronologiquement + borne les publications éco. Retourne `{events:
    [{ts, name, country, currency, impact, consensus, previous, actual, surprise}]}`. Écarte les
    événements structurellement cassés (fail-closed §3) et ceux plus vieux que `past_grace`."""
    events = []
    for e in (raw_events if isinstance(raw_events, list) else []):
        if not isinstance(e, dict):
            continue
        ts, name, impact = e.get("ts"), e.get("name"), e.get("impact")
        if not (_finite(ts) and isinstance(name, str) and name and impact in _IMPACTS):
            continue                                   # fail-closed : événement invalide écarté
        if float(ts) <= now - past_grace:
            continue                                   # trop ancien (au-delà de la grâce)
        consensus, actual = _num(e.get("consensus")), _num(e.get("actual"))
        events.append({
            "ts": float(ts), "name": name, "country": e.get("country"),
            "currency": e.get("currency"), "impact": impact,
            "consensus": consensus, "previous": _num(e.get("previous")), "actual": actual,
            "surprise": (actual - consensus) if (actual is not None and consensus is not None) else None,
        })
    events.sort(key=lambda x: x["ts"])
    return {"events": events[:max_events] if max_events > 0 else events}


def compute_macro_risk(raw_events, now: float, pause_window: float, warn_window: float) -> dict:
    """Risk Guard déterministe (§2.2). Régime selon la proximité des annonces HIGH impact :
    - **EXECUTION_PAUSED** si un HIGH est dans le BLACKOUT symétrique `|ts − now| ≤ pause` ;
    - **WARNING** si un HIGH approche (`pause < ts − now ≤ warn`) sans être encore en blackout ;
    - **NORMAL** sinon. MED/LOW n'enclenchent jamais le garde. Retourne `{regime, event: {name,
    ts, impact, country} | None, seconds_until, in_window}` où `event` PILOTE le régime."""
    highs = [e for e in (raw_events if isinstance(raw_events, list) else [])
             if isinstance(e, dict) and e.get("impact") == "HIGH" and _finite(e.get("ts"))]

    in_blackout = [e for e in highs if abs(float(e["ts"]) - now) <= pause_window]
    approaching = [e for e in highs if pause_window < float(e["ts"]) - now <= warn_window]
    upcoming = [e for e in highs if float(e["ts"]) - now > 0]

    if in_blackout:
        regime, driver = "EXECUTION_PAUSED", min(in_blackout, key=lambda e: abs(float(e["ts"]) - now))
    elif approaching:
        regime, driver = "WARNING", min(approaching, key=lambda e: float(e["ts"]) - now)
    else:
        regime = "NORMAL"
        driver = min(upcoming, key=lambda e: float(e["ts"]) - now) if upcoming else None

    event = None if driver is None else {
        "name": driver.get("name"), "ts": float(driver["ts"]),
        "impact": driver.get("impact"), "country": driver.get("country"),
    }
    return {
        "regime": regime, "event": event,
        "seconds_until": (float(driver["ts"]) - now) if driver is not None else None,
        "in_window": bool(in_blackout),
    }
