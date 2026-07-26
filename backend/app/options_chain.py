"""Chaîne d'options (OMON) + Term Structure de volatilité (D-039, enrichie D-044).

`build_options_chain` agrège la chaîne OBSERVÉE (§2.1) — Calls/Puts par EXPIRATION puis par STRIKE —
classe la MONEYNESS de façon déterministe vs le sous-jacent, et **enrichit chaque patte via le
moteur Black-Scholes** (`black_scholes.py`) : IV inversée du prix de marché, puis les six Grecques
(delta, gamma, theta, vega, vanna, charm). `build_term_structure` ordonne la structure de volatilité
(VIX9D/VIX/VIX3M/VIX6M) et en classe l'état (CONTANGO / BACKWARDATION / FLAT).

**Provenance des Grecques — jamais implicite (D-044).** Un calcul ne doit pas passer pour une donnée
de marché, ni l'inverse (§3). Chaque patte porte donc `greeks_source` :
| Valeur | Entrée disponible | Ce que portent les Grecques |
|---|---|---|
| `INVERTED` | un PRIX de marché | IV inversée (Newton-Raphson) + les six Grecques à cette IV |
| `SOURCE_IV` | pas de prix exploitable, mais une IV source | Grecques à l'IV source, **IV conservée telle quelle** |
| `RELAY` | ni prix ni IV utilisables | valeurs source relayées ; ce que la source ne porte pas reste `None` |
Un prix hors bornes d'arbitrage (négatif, sous l'intrinsèque, non-fini) fait **échouer l'inversion**
et retomber sur `SOURCE_IV` — jamais sur une vol fabriquée. La provenance se décide **patte par
patte** : une même ligne peut porter un call `RELAY` et un put `INVERTED`, et l'affichage doit en
tenir compte pour ne pas mentir.

Purs et déterministes (aucun LLM, aucun état caché). FAIL-CLOSED (§3) : strike non-fini → ligne
ignorée ; IV/grecque non-finie → None (jamais inventée) ; sous-jacent non-fini → moneyness None ;
DTE absent → aucun calcul possible (relais) ; < 2 échéances → état None. Les seuils (bande ATM,
eps FLAT) et le taux sans risque sont **v1 provisional** (config)."""
from __future__ import annotations

import math

from .black_scholes import bs_greeks, implied_vol

_GREEKS = ("iv", "delta", "gamma", "theta", "vega", "vanna", "charm")
_MODEL = ("delta", "gamma", "theta", "vega", "vanna", "charm")   # calculées par le moteur


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _leg(raw: dict, moneyness: str | None, kind: str,
         S: float | None, K: float, T: float | None, r: float) -> dict:
    """Une patte (call ou put), enrichie par le moteur Black-Scholes (D-044).

    La `greeks_source` est TOUJOURS explicite — un calcul ne doit jamais passer pour une donnée de
    marché, ni l'inverse (§3) :
    - `INVERTED`  : un PRIX de marché est présent → IV inversée (Newton-Raphson) puis les six
      Grecques calculées à cette IV. Chemin autoritaire ;
    - `SOURCE_IV` : pas de prix exploitable mais une IV source → Grecques calculées à cette IV
      (l'IV source est conservée telle quelle, on ne la réécrit pas) ;
    - `RELAY`     : ni prix ni IV utilisables → valeurs source relayées telles quelles, et les
      Grecques que la source ne porte pas restent `None` (jamais un faux zéro).
    Grecque non-finie → `None` dans tous les cas (fail-closed §3)."""
    src = raw if isinstance(raw, dict) else {}
    out = {g: (float(src[g]) if _finite(src.get(g)) else None) for g in _GREEKS}
    out["moneyness"] = moneyness
    out["greeks_source"] = "RELAY"

    computable = S is not None and _finite(T) and T > 0
    if not computable:
        return out

    iv = implied_vol(src.get("price"), S, K, T, r, kind) if _finite(src.get("price")) else None
    if iv is not None:
        out["iv"] = iv
        out["greeks_source"] = "INVERTED"
    elif out["iv"] is not None and out["iv"] > 0:
        iv = out["iv"]                                  # repli : IV de la source, conservée telle quelle
        out["greeks_source"] = "SOURCE_IV"
    else:
        return out                                      # rien à quoi accrocher un calcul → relais

    for g, v in bs_greeks(S, K, T, r, iv, kind).items():
        if g in _MODEL:
            out[g] = v                                  # `None` si la Grecque est indéfinie (§3)
    return out


def _moneyness(strike: float, underlying: float | None, band: float, is_call: bool) -> str | None:
    if underlying is None:
        return None                                    # sous-jacent inconnu → moneyness indécidable
    if abs(strike - underlying) <= band:
        return "ATM"
    itm = strike < underlying if is_call else strike > underlying
    return "ITM" if itm else "OTM"


def build_options_chain(raw_expirations: list[dict], underlying, atm_band: float,
                        max_expirations: int, max_strikes: int, r: float = 0.0) -> dict:
    """Construit la chaîne : `{underlying, atm_strike, expirations: [{expiry, dte, atm_strike,
    rows: [{strike, call, put}]}]}`. `call`/`put` = `{iv, delta, gamma, vanna, charm, moneyness}`.
    Rows triés strike croissant ; expirations triées DTE croissant (bornées) ; strikes bornés aux
    plus proches du sous-jacent."""
    # sous-jacent ≤ 0 = corrompu (un indice ne vaut jamais 0/négatif) → indécidable, moneyness None
    u = float(underlying) if (_finite(underlying) and underlying > 0) else None
    if not isinstance(raw_expirations, list):
        raw_expirations = []                           # /devil : raw non-liste → jamais un crash (§3)

    exps = []
    for e in raw_expirations:
        if not isinstance(e, dict):
            continue
        raw_strikes = e.get("strikes") if isinstance(e.get("strikes"), list) else []
        dte = float(e["dte"]) if _finite(e.get("dte")) else None
        T = dte / 365.0 if (dte is not None and dte > 0) else None   # DTE → années
        rows_by_k: dict[float, dict] = {}              # dédup par strike (clé React unique en aval)
        for s in raw_strikes:
            if not isinstance(s, dict) or not _finite(s.get("strike")):
                continue                               # fail-closed : strike non-fini → ligne ignorée
            k = float(s["strike"])
            rows_by_k[k] = {"strike": k,               # strike dupliqué → dernière occurrence gagne
                            "call": _leg(s.get("call"), _moneyness(k, u, atm_band, True),
                                         "call", u, k, T, r),
                            "put": _leg(s.get("put"), _moneyness(k, u, atm_band, False),
                                        "put", u, k, T, r)}
        rows = list(rows_by_k.values())
        # borne les strikes aux plus proches du sous-jacent (les plus pertinents), puis trie
        if max_strikes > 0 and len(rows) > max_strikes:
            ref = u if u is not None else (rows[len(rows) // 2]["strike"] if rows else 0.0)
            rows = sorted(rows, key=lambda r: abs(r["strike"] - ref))[:max_strikes]
        rows.sort(key=lambda r: r["strike"])
        atm_k = min((r["strike"] for r in rows), key=lambda k: abs(k - u)) if (u is not None and rows) else None
        exps.append({"expiry": e.get("expiry"), "dte": dte,
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
    for p in (raw_points if isinstance(raw_points, list) else []):   # /devil : raw non-liste → vide
        if isinstance(p, dict) and _finite(p.get("days")) and _finite(p.get("value")):
            pts.append({"tenor": p.get("tenor"), "days": float(p["days"]), "value": float(p["value"])})
    pts.sort(key=lambda p: p["days"])
    state, spread = None, None
    if len(pts) >= 2:
        spread = pts[-1]["value"] - pts[0]["value"]    # back − front
        state = "FLAT" if abs(spread) <= flat_eps else "CONTANGO" if spread > 0 else "BACKWARDATION"
    return {"points": pts, "state": state, "front_back_spread": spread}
