"""Feature — Moniteur de chaîne d'options (OMON) + Term Structure de volatilité (D-039).

Approche figée AVANT implémentation (Loop 1 étape 3) :
- `build_options_chain` : agrège la chaîne (Calls/Puts) par EXPIRATION puis par STRIKE, portant
  IV + Grecques (delta, gamma, vanna, charm). MONEYNESS déterministe vs sous-jacent + bande ATM :
  CALL ITM si strike < sous-jacent, ATM si |strike−U| ≤ bande, OTM sinon ; PUT en miroir. Strikes
  triés croissants ; expirations triées par DTE croissant, bornées ; strikes bornés aux plus
  proches du sous-jacent. `atm_strike` = strike le plus proche du sous-jacent.
- `build_term_structure` : ordonne la structure par échéance (jours), classe l'état CONTANGO
  (front < back), BACKWARDATION (front > back), FLAT (|Δ| ≤ eps).
- FAIL-CLOSED (§3) : strike non-fini → ligne ignorée ; IV/grecque non-finie → None (jamais
  inventée) ; sous-jacent non-fini → moneyness None ; < 2 échéances → état None.
- OBSERVATION seule (§2.1).
"""
from app.options_chain import build_options_chain, build_term_structure


def _leg(iv, delta, gamma, vanna, charm):
    return {"iv": iv, "delta": delta, "gamma": gamma, "vanna": vanna, "charm": charm}


def _row(strike, c=None, p=None):
    return {"strike": strike, "call": c or _leg(0.2, 0.5, 0.01, 0.0, 0.0),
            "put": p or _leg(0.2, -0.5, 0.01, 0.0, 0.0)}


def _exp(expiry, dte, rows):
    return {"expiry": expiry, "dte": dte, "strikes": rows}


def _chain(raw, underlying=5000.0, band=6.0, max_exp=6, max_strikes=40):
    return build_options_chain(raw, underlying, band, max_exp, max_strikes)


def _rows(chain, i=0):
    return {r["strike"]: r for r in chain["expirations"][i]["rows"]}


# ---------- chaîne d'options ----------

def test_classifies_moneyness_itm_atm_otm():
    raw = [_exp("E1", 30, [_row(4900), _row(5000), _row(5100)])]
    rows = _rows(_chain(raw, underlying=5000, band=6))
    assert rows[4900]["call"]["moneyness"] == "ITM" and rows[4900]["put"]["moneyness"] == "OTM"
    assert rows[5000]["call"]["moneyness"] == "ATM" and rows[5000]["put"]["moneyness"] == "ATM"
    assert rows[5100]["call"]["moneyness"] == "OTM" and rows[5100]["put"]["moneyness"] == "ITM"


def test_atm_strike_is_closest_to_underlying():
    raw = [_exp("E1", 30, [_row(5000), _row(5025)])]
    assert _chain(raw, underlying=5012)["expirations"][0]["atm_strike"] == 5000   # |12| < |13|


def test_greeks_are_computed_not_relayed_when_iv_is_usable():
    """CHANGEMENT DE CONTRAT (D-044) : les Grecques ne sont plus RELAYÉES depuis la source mais
    CALCULÉES par le moteur — c'est tout l'objet du livrable, et c'est ce qui les rend identiques
    pour les deux opérateurs. L'IV source, elle, est conservée telle quelle. La provenance est
    explicite pour que l'écart avec les valeurs du feed ne soit jamais une surprise (§3)."""
    raw = [_exp("E1", 30, [_row(5000, c=_leg(0.19, 0.55, 0.012, 0.3, -0.1))])]
    call = _rows(_chain(raw))[5000]["call"]
    assert call["iv"] == 0.19                       # IV source conservée
    assert call["greeks_source"] == "SOURCE_IV"
    assert call["delta"] != 0.55                    # recalculé, pas relayé
    assert 0.0 < call["delta"] < 1.0 and call["gamma"] > 0.0
    assert call["theta"] is not None and call["vega"] is not None   # absents de la source


def test_rows_sorted_by_strike_ascending():
    raw = [_exp("E1", 30, [_row(5100), _row(4900), _row(5000)])]
    strikes = [r["strike"] for r in _chain(raw)["expirations"][0]["rows"]]
    assert strikes == [4900, 5000, 5100]


def test_expirations_sorted_by_dte_and_capped():
    raw = [_exp("E3", 60, [_row(5000)]), _exp("E1", 7, [_row(5000)]), _exp("E2", 30, [_row(5000)])]
    exps = _chain(raw, max_exp=2)["expirations"]
    assert [e["dte"] for e in exps] == [7, 30]           # les 2 plus proches, triées


def test_strikes_capped_keeps_closest_to_underlying():
    rows = [_row(5000 + i * 25) for i in range(-10, 11)]  # 21 strikes autour de 5000
    raw = [_exp("E1", 30, rows)]
    out = _chain(raw, underlying=5000, max_strikes=5)["expirations"][0]["rows"]
    strikes = [r["strike"] for r in out]
    assert len(strikes) == 5 and strikes == [4950, 4975, 5000, 5025, 5050]  # 5 plus proches, triés


def test_fail_closed_non_finite_strike_skipped():
    raw = [_exp("E1", 30, [_row(float("nan")), _row(5000)])]
    assert list(_rows(_chain(raw))) == [5000]


def test_fail_closed_non_finite_greek_becomes_none():
    raw = [_exp("E1", 30, [_row(5000, c=_leg(float("nan"), 0.5, float("inf"), 0.0, 0.0))])]
    call = _rows(_chain(raw))[5000]["call"]
    assert call["iv"] is None and call["gamma"] is None and call["delta"] == 0.5


def test_underlying_non_finite_moneyness_none():
    raw = [_exp("E1", 30, [_row(5000)])]
    out = build_options_chain(raw, float("nan"), 6.0, 6, 40)
    assert out["underlying"] is None
    assert out["expirations"][0]["rows"][0]["call"]["moneyness"] is None


def test_empty_chain():
    out = _chain([])
    assert out["expirations"] == []


# ---------- term structure ----------

def _pt(tenor, days, value):
    return {"tenor": tenor, "days": days, "value": value}


def test_term_structure_ordered_by_days():
    raw = [_pt("VIX3M", 93, 20), _pt("VIX9D", 9, 16), _pt("VIX", 30, 18), _pt("VIX6M", 186, 21)]
    ts = build_term_structure(raw, 0.1)
    assert [p["tenor"] for p in ts["points"]] == ["VIX9D", "VIX", "VIX3M", "VIX6M"]


def test_contango_front_below_back():
    raw = [_pt("VIX9D", 9, 15), _pt("VIX", 30, 18), _pt("VIX3M", 93, 21)]
    ts = build_term_structure(raw, 0.1)
    assert ts["state"] == "CONTANGO" and ts["front_back_spread"] == 6


def test_backwardation_front_above_back():
    raw = [_pt("VIX9D", 9, 30), _pt("VIX", 30, 24), _pt("VIX3M", 93, 20)]
    assert build_term_structure(raw, 0.1)["state"] == "BACKWARDATION"


def test_flat_within_epsilon():
    raw = [_pt("VIX9D", 9, 18.0), _pt("VIX3M", 93, 18.05)]
    assert build_term_structure(raw, 0.1)["state"] == "FLAT"


def test_term_structure_filters_non_finite():
    raw = [_pt("VIX9D", 9, float("nan")), _pt("VIX", 30, 18), _pt("VIX3M", 93, 21)]
    ts = build_term_structure(raw, 0.1)
    assert [p["tenor"] for p in ts["points"]] == ["VIX", "VIX3M"] and ts["state"] == "CONTANGO"


def test_term_structure_insufficient_points_state_none():
    assert build_term_structure([_pt("VIX", 30, 18)], 0.1)["state"] is None
    assert build_term_structure([], 0.1)["state"] is None


# ---------- /devil (D-039) : conditions limites ----------

import math  # noqa: E402


def test_underlying_zero_or_negative_moneyness_none():
    # sous-jacent ≤ 0 = donnée corrompue (un indice ne vaut jamais 0/négatif) → moneyness None,
    # jamais classé contre un 0 bidon (fail-closed §3).
    raw = [_exp("E1", 30, [_row(5000)])]
    for bad in (0.0, -5.0):
        out = build_options_chain(raw, bad, 6.0, 6, 40)
        assert out["underlying"] is None
        assert out["expirations"][0]["rows"][0]["call"]["moneyness"] is None


def test_giant_chain_bounded_and_finite():
    rows = [_row(3000 + i * 5) for i in range(600)]           # 600 strikes
    raw = [_exp("E1", 30, rows)]
    got = _chain(raw, underlying=5000, max_strikes=13)["expirations"][0]["rows"]
    assert len(got) == 13 and all(math.isfinite(r["strike"]) for r in got)  # 13 plus proches


def test_dte_non_finite_becomes_none_no_crash():
    raw = [{"expiry": "E1", "dte": float("nan"), "strikes": [_row(5000)]}]
    assert _chain(raw)["expirations"][0]["dte"] is None       # dte NaN → None (tri non cassé)


def test_corrupted_expirations_skipped():
    good = {"strike": 5000, "call": _leg(0.2, 0.5, 0.01, 0, 0), "put": _leg(0.2, -0.5, 0.01, 0, 0)}
    raw = [
        "pas un dict",                                        # échéance non-dict → ignorée
        {"expiry": "E1", "dte": 30, "strikes": "boom"},       # strikes non-liste → vide
        {"expiry": "E2", "dte": 7, "strikes": ["x", good]},   # entrée non-dict écartée
    ]
    by_exp = {e["expiry"]: e for e in _chain(raw)["expirations"]}
    assert by_exp["E1"]["rows"] == []
    assert [r["strike"] for r in by_exp["E2"]["rows"]] == [5000]


def test_non_list_raw_returns_empty():
    assert build_options_chain(None, 5000, 6.0, 6, 40)["expirations"] == []
    assert build_options_chain("boom", 5000, 6.0, 6, 40)["expirations"] == []
    assert build_term_structure(None, 0.1)["state"] is None
    assert build_term_structure("boom", 0.1)["points"] == []


def test_term_structure_giant_and_duplicate_days():
    raw = [_pt(f"T{i}", i % 5, 15 + (i % 7)) for i in range(1000)]  # jours dupliqués, 1000 points
    ts = build_term_structure(raw, 0.1)
    assert len(ts["points"]) == 1000 and ts["state"] in ("CONTANGO", "BACKWARDATION", "FLAT")


def test_duplicate_strikes_deduped_last_wins():
    # strike dupliqué = donnée corrompue → 1 seule ligne (clé React unique en aval), dernier gagne
    raw = [_exp("E1", 30, [_row(5000, c=_leg(0.10, 0.5, 0.01, 0, 0)),
                           _row(5000, c=_leg(0.22, 0.6, 0.02, 0, 0))])]
    rows = _chain(raw)["expirations"][0]["rows"]
    assert len(rows) == 1 and rows[0]["call"]["iv"] == 0.22   # dédup, dernière occurrence


def test_many_expirations_capped_keeps_nearest_dte():
    raw = [_exp(f"E{i}", i * 3, [_row(5000)]) for i in range(50)]  # 50 échéances (DTE 0..147)
    out = _chain(raw, max_exp=4)["expirations"]
    assert [e["dte"] for e in out] == [0, 3, 6, 9]                 # 4 plus proches, triées


# ---------- D-044 tranche 2 : enrichissement par le moteur Black-Scholes ----------
# La source ne porte pas Theta/Vega et son IV n'est pas inversée. L'enrichissement est ADDITIF et
# sa PROVENANCE est explicite, pour ne jamais présenter un calcul comme une donnée de marché (§3) :
#   INVERTED  — prix de marché présent → IV inversée (Newton-Raphson) puis TOUTES les Grecques ;
#   SOURCE_IV — pas de prix mais une IV source → Grecques calculées à cette IV ;
#   RELAY     — ni prix ni IV exploitables → valeurs source relayées telles quelles.

from app.black_scholes import bs_price          # noqa: E402

_U, _R = 5000.0, 0.045


def _enriched(strikes, dte=30):
    """Chaîne d'UNE échéance passée au moteur (taux `_R`), pour éprouver l'enrichissement."""
    return build_options_chain([{"expiry": "W1", "dte": dte, "strikes": strikes}],
                               _U, 6.0, 4, 20, r=_R)


def test_enrich_inverts_iv_from_market_price():
    t = 30 / 365
    k = 5000.0
    row = {"strike": k,
           "call": {"price": bs_price(_U, k, t, _R, 0.23, "call")},
           "put": {"price": bs_price(_U, k, t, _R, 0.23, "put")}}
    call = _enriched([row])["expirations"][0]["rows"][0]["call"]
    assert call["greeks_source"] == "INVERTED"
    assert abs(call["iv"] - 0.23) < 1e-6
    for g in ("delta", "gamma", "theta", "vega", "vanna", "charm"):
        assert call[g] is not None


def test_enrich_computes_greeks_from_source_iv_when_no_price():
    row = {"strike": 5000.0, "call": {"iv": 0.19}, "put": {"iv": 0.20}}
    call = _enriched([row])["expirations"][0]["rows"][0]["call"]
    assert call["greeks_source"] == "SOURCE_IV"
    assert call["iv"] == 0.19                       # l'IV source est conservée telle quelle
    assert call["theta"] is not None and call["vega"] is not None


def test_enrich_relays_when_neither_price_nor_iv():
    row = {"strike": 5000.0, "call": {"delta": 0.55, "gamma": 0.012}, "put": {}}
    call = _enriched([row])["expirations"][0]["rows"][0]["call"]
    assert call["greeks_source"] == "RELAY"
    assert call["delta"] == 0.55 and call["gamma"] == 0.012
    assert call["theta"] is None and call["vega"] is None      # jamais un faux zéro (§3)


def test_enrich_aberrant_price_falls_back_not_fabricates():
    # prix sous l'intrinsèque : l'inversion échoue → on ne fabrique pas de vol
    row = {"strike": 4000.0, "call": {"price": 1.0, "iv": 0.21}, "put": {}}
    call = _enriched([row])["expirations"][0]["rows"][0]["call"]
    assert call["greeks_source"] == "SOURCE_IV"      # repli sur l'IV source, inversion abandonnée
    assert call["iv"] == 0.21


def test_enrich_needs_dte_to_compute():
    # sans DTE, aucune échéance → aucun calcul possible, mais pas de crash : relais
    row = {"strike": 5000.0, "call": {"price": 300.0}, "put": {}}
    call = _enriched([row], dte=None)["expirations"][0]["rows"][0]["call"]
    assert call["greeks_source"] == "RELAY" and call["theta"] is None


def test_enrich_all_legs_carry_the_six_greek_keys():
    row = {"strike": 5000.0, "call": {"iv": 0.2}, "put": {}}
    for leg in ("call", "put"):
        out = _enriched([row])["expirations"][0]["rows"][0][leg]
        for key in ("iv", "delta", "gamma", "theta", "vega", "vanna", "charm",
                    "moneyness", "greeks_source"):
            assert key in out
