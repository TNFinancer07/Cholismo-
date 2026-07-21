"""Chaîne d'options (OMON) + Term Structure de volatilité (D-039).

`build_options_chain` agrège la chaîne OBSERVÉE (§2.1) — Calls/Puts par EXPIRATION puis par
STRIKE — portant IV + Grecques (delta, gamma, vanna, charm), et classe la MONEYNESS de façon
déterministe vs le sous-jacent. `build_term_structure` ordonne la structure de volatilité
(VIX9D/VIX/VIX3M/VIX6M) et en classe l'état (CONTANGO / BACKWARDATION / FLAT).

Purs et déterministes (aucun LLM, aucun état caché). FAIL-CLOSED (§3) : strike non-fini → ligne
ignorée ; IV/grecque non-finie → None (jamais inventée) ; sous-jacent non-fini → moneyness None ;
< 2 échéances → état None. Les seuils (bande ATM, eps FLAT) sont **v1 provisional** (config)."""
from __future__ import annotations

import math

_GREEKS = ("iv", "delta", "gamma", "vanna", "charm")


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _leg(raw: dict, moneyness: str | None) -> dict:
    """Nettoie une patte (call ou put) : grecque non-finie → None (fail-closed §3)."""
    src = raw if isinstance(raw, dict) else {}
    out = {g: (float(src[g]) if _finite(src.get(g)) else None) for g in _GREEKS}
    out["moneyness"] = moneyness
    return out


def _moneyness(strike: float, underlying: float | None, band: float, is_call: bool) -> str | None:
    if underlying is None:
        return None                                    # sous-jacent inconnu → moneyness indécidable
    if abs(strike - underlying) <= band:
        return "ATM"
    itm = strike < underlying if is_call else strike > underlying
    return "ITM" if itm else "OTM"


def build_options_chain(raw_expirations: list[dict], underlying, atm_band: float,
                        max_expirations: int, max_strikes: int) -> dict:
    """Construit la chaîne : `{underlying, atm_strike, expirations: [{expiry, dte, atm_strike,
    rows: [{strike, call, put}]}]}`. `call`/`put` = `{iv, delta, gamma, vanna, charm, moneyness}`.
    Rows triés strike croissant ; expirations triées DTE croissant (bornées) ; strikes bornés aux
    plus proches du sous-jacent."""
    u = float(underlying) if _finite(underlying) else None

    exps = []
    for e in raw_expirations:
        if not isinstance(e, dict):
            continue
        raw_strikes = e.get("strikes") if isinstance(e.get("strikes"), list) else []
        rows = []
        for s in raw_strikes:
            if not isinstance(s, dict) or not _finite(s.get("strike")):
                continue                               # fail-closed : strike non-fini → ligne ignorée
            k = float(s["strike"])
            rows.append({"strike": k,
                         "call": _leg(s.get("call"), _moneyness(k, u, atm_band, True)),
                         "put": _leg(s.get("put"), _moneyness(k, u, atm_band, False))})
        # borne les strikes aux plus proches du sous-jacent (les plus pertinents), puis trie
        if max_strikes > 0 and len(rows) > max_strikes:
            ref = u if u is not None else (rows[len(rows) // 2]["strike"] if rows else 0.0)
            rows = sorted(rows, key=lambda r: abs(r["strike"] - ref))[:max_strikes]
        rows.sort(key=lambda r: r["strike"])
        atm_k = min((r["strike"] for r in rows), key=lambda k: abs(k - u)) if (u is not None and rows) else None
        exps.append({"expiry": e.get("expiry"),
                     "dte": float(e["dte"]) if _finite(e.get("dte")) else None,
                     "atm_strike": atm_k, "rows": rows})

    # expirations triées par DTE croissant (None en dernier), bornées aux plus proches
    exps.sort(key=lambda x: (x["dte"] is None, x["dte"] if x["dte"] is not None else 0.0))
    if max_expirations > 0:
        exps = exps[:max_expirations]
    atm_strike = exps[0]["atm_strike"] if exps else None
    return {"underlying": u, "atm_strike": atm_strike, "expirations": exps}


def build_term_structure(raw_points: list[dict], flat_eps: float) -> dict:
    """Ordonne la structure de volatilité par échéance (jours) et classe l'état : CONTANGO
    (front < back), BACKWARDATION (front > back), FLAT (|Δ| ≤ eps). `< 2` points finis → état None
    (jamais un faux régime, §3). Retourne `{points, state, front_back_spread}`."""
    pts = []
    for p in raw_points:
        if isinstance(p, dict) and _finite(p.get("days")) and _finite(p.get("value")):
            pts.append({"tenor": p.get("tenor"), "days": float(p["days"]), "value": float(p["value"])})
    pts.sort(key=lambda p: p["days"])
    state, spread = None, None
    if len(pts) >= 2:
        spread = pts[-1]["value"] - pts[0]["value"]    # back − front
        state = "FLAT" if abs(spread) <= flat_eps else "CONTANGO" if spread > 0 else "BACKWARDATION"
    return {"points": pts, "state": state, "front_back_spread": spread}
