"""Feature — Moteur Black-Scholes : pricing, Grecques, inversion d'IV (D-044, tranche 1).

Approche figée AVANT implémentation (Loop 1 étape 3) :
- **Pricing** Black-Scholes-Merton européen (call/put), taux `r`, sans dividende (v1 provisional) ;
- **Grecques** : Delta, Gamma, Theta (par AN), Vega (par point de vol, càd pour σ+1.0), Vanna
  (∂Delta/∂σ). Conventions figées ici pour que l'affichage ne les réinvente jamais ;
- **IV** par **Newton-Raphson** (départ Brenner-Subrahmanyam) avec **repli BISSECTION** quand Newton
  diverge (vega ≈ 0 : options très ITM/OTM) — jamais un `NaN` renvoyé comme une vol ;
- **FAIL-CLOSED (§3)** : entrée non-finie, `S ≤ 0`, `K ≤ 0`, `T ≤ 0`, `σ ≤ 0` → `None` ; prix de
  marché **sous la valeur intrinsèque** ou au-dessus des bornes d'arbitrage → `None` (donnée
  aberrante, on ne fabrique pas de vol) ;
- **batch** (`price_chain`) : enrichit une chaîne entière en un appel, chaque ligne isolée — une
  ligne corrompue n'invalide jamais les autres.

Valeurs de référence (manuel) : S=100, K=100, T=1, r=0.05, σ=0.20 →
call 10.4506 · put 5.5735 · delta_call 0.63683 · gamma 0.018762 · vega 37.524 · theta_call −6.414 ·
vanna −0.28143.
"""
import itertools
import math

from app.black_scholes import bs_greeks, bs_price, implied_vol, price_chain

S, K, T, R, SIG = 100.0, 100.0, 1.0, 0.05, 0.20
TOL = 1e-3


def test_call_price_reference():
    assert abs(bs_price(S, K, T, R, SIG, "call") - 10.4506) < TOL


def test_put_price_reference():
    assert abs(bs_price(S, K, T, R, SIG, "put") - 5.5735) < TOL


def test_put_call_parity():
    c = bs_price(S, K, T, R, SIG, "call")
    p = bs_price(S, K, T, R, SIG, "put")
    assert abs((c - p) - (S - K * math.exp(-R * T))) < 1e-9


def test_greeks_reference_call():
    g = bs_greeks(S, K, T, R, SIG, "call")
    assert abs(g["delta"] - 0.63683) < TOL
    assert abs(g["gamma"] - 0.018762) < 1e-6
    assert abs(g["vega"] - 37.524) < 1e-2
    assert abs(g["theta"] - (-6.414)) < 1e-2
    assert abs(g["vanna"] - (-0.28143)) < TOL


def test_delta_put_is_call_delta_minus_one():
    c = bs_greeks(S, K, T, R, SIG, "call")["delta"]
    p = bs_greeks(S, K, T, R, SIG, "put")["delta"]
    assert abs((c - 1.0) - p) < 1e-9


def test_gamma_and_vega_identical_for_call_and_put():
    c, p = bs_greeks(S, K, T, R, SIG, "call"), bs_greeks(S, K, T, R, SIG, "put")
    assert abs(c["gamma"] - p["gamma"]) < 1e-12 and abs(c["vega"] - p["vega"]) < 1e-12


def test_implied_vol_round_trip():
    for sig in (0.05, 0.2, 0.75, 2.0):
        price = bs_price(S, K, T, R, sig, "call")
        assert abs(implied_vol(price, S, K, T, R, "call") - sig) < 1e-6


def test_implied_vol_round_trip_put_and_off_the_money():
    for strike in (60.0, 100.0, 150.0):
        price = bs_price(S, strike, 0.5, R, 0.35, "put")
        assert abs(implied_vol(price, S, strike, 0.5, R, "put") - 0.35) < 1e-6


def test_implied_vol_itm_falls_back_to_bisection():
    # ITM marqué : vega faible, Newton peut sortir des bornes → le repli bissection converge
    price = bs_price(S, 60.0, 0.5, R, 0.4, "call")
    iv = implied_vol(price, S, 60.0, 0.5, R, "call")
    assert iv is not None and abs(iv - 0.4) < 1e-3


def test_implied_vol_none_when_price_carries_no_time_value():
    """IDENTIFIABILITÉ : sur une option très ITM, la valeur temps est nulle EN FLOAT64 — le prix est
    bit-identique pour σ = 0.1 et σ = 0.4. Aucun algorithme ne peut retrouver σ : renvoyer un nombre
    fabriquerait une précision absente de la donnée (§3), donc `None`."""
    p_lo = bs_price(S, 20.0, 0.25, R, 0.1, "call")
    p_hi = bs_price(S, 20.0, 0.25, R, 0.4, "call")
    assert p_lo == p_hi                                  # le prix ne porte AUCUNE information de vol
    assert implied_vol(p_hi, S, 20.0, 0.25, R, "call") is None


# ---------- FAIL-CLOSED (§3) : jamais une vol ni une grecque fabriquée ----------


def test_price_none_on_invalid_inputs():
    for args in ((0.0, K, T, R, SIG), (S, 0.0, T, R, SIG), (S, K, 0.0, R, SIG),
                 (S, K, T, R, 0.0), (S, K, -1.0, R, SIG), (S, K, T, R, -0.2)):
        assert bs_price(*args, "call") is None


def test_price_none_on_non_finite():
    nan, inf = float("nan"), float("inf")
    assert bs_price(nan, K, T, R, SIG, "call") is None
    assert bs_price(S, inf, T, R, SIG, "call") is None
    assert bs_price(S, K, T, nan, SIG, "call") is None


def test_price_none_on_unknown_kind():
    assert bs_price(S, K, T, R, SIG, "straddle") is None
    assert bs_greeks(S, K, T, R, SIG, None)["delta"] is None


def test_greeks_all_none_when_undefined():
    g = bs_greeks(S, K, 0.0, R, SIG, "call")            # échéance atteinte → indéfini
    assert all(g[k] is None for k in ("delta", "gamma", "theta", "vega", "vanna"))


def test_implied_vol_none_below_intrinsic():
    # prix sous la valeur intrinsèque = violation d'arbitrage → donnée aberrante, pas de vol
    intrinsic = S - K * math.exp(-R * T)
    assert implied_vol(intrinsic - 1.0, S, K, T, R, "call") is None


def test_implied_vol_none_above_upper_bound():
    assert implied_vol(S + 1.0, S, K, T, R, "call") is None      # call > S : impossible
    assert implied_vol(K + 1.0, S, K, T, R, "put") is None        # put > K : impossible


def test_implied_vol_none_on_non_finite_or_invalid():
    for bad in (float("nan"), float("inf"), -1.0):
        assert implied_vol(bad, S, K, T, R, "call") is None
    assert implied_vol(10.0, S, K, 0.0, R, "call") is None        # T ≤ 0


def test_implied_vol_deterministic():
    price = bs_price(S, 110.0, 0.75, R, 0.28, "call")
    assert implied_vol(price, S, 110.0, 0.75, R, "call") == implied_vol(price, S, 110.0, 0.75, R, "call")


# ---------- batch sur la chaîne (« vectorisé » : un appel, chaque ligne isolée) ----------


def test_price_chain_enriches_rows():
    # prix COHÉRENTS avec l'arbitrage (générés par le modèle) : un prix sous l'intrinsèque serait
    # une donnée aberrante et donnerait `None`, ce que teste `..._aberrant_price_yields_none_iv`.
    rows = [{"strike": k, "expiry_years": 0.5,
             "call_price": bs_price(S, k, 0.5, R, 0.25, "call"),
             "put_price": bs_price(S, k, 0.5, R, 0.25, "put")} for k in (90.0, 100.0)]
    out = price_chain(rows, underlying=S, r=R)
    assert len(out) == 2
    for row in out:
        assert abs(row["call"]["iv"] - 0.25) < 1e-6 and row["call"]["delta"] is not None
        assert abs(row["put"]["iv"] - 0.25) < 1e-6 and row["put"]["vega"] is not None


def test_price_chain_isolates_corrupt_rows():
    rows = [None, "boom", {"strike": float("nan"), "expiry_years": 0.5, "call_price": 5.0},
            {"strike": 100.0, "expiry_years": 0.5, "call_price": 6.0, "put_price": 4.5}]
    out = price_chain(rows, underlying=S, r=R)
    assert len(out) == 1 and out[0]["strike"] == 100.0     # seule la ligne saine survit


def test_price_chain_aberrant_price_yields_none_iv_not_crash():
    rows = [{"strike": 100.0, "expiry_years": 0.5, "call_price": 0.001, "put_price": 999.0}]
    out = price_chain(rows, underlying=S, r=R)
    assert out[0]["call"]["iv"] is None and out[0]["put"]["iv"] is None   # aberrant → None


def test_price_chain_empty_and_non_list():
    assert price_chain([], underlying=S, r=R) == []
    assert price_chain(None, underlying=S, r=R) == []
    assert price_chain([{"strike": 100.0, "expiry_years": 0.5, "call_price": 6.0}],
                       underlying=0.0, r=R) == []        # sous-jacent invalide → rien


# ---------- Pathologies de marché extrêmes : bornes de magnitude ----------
# RÈGLE : le module promet `None` sur donnée invalide (§3) — il ne doit JAMAIS lever. La finitude
# des entrées n'y suffit pas : ce sont les MAGNITUDES qui cassent (cf. le tableau des bornes en tête
# de `black_scholes.py`). Ces tests verrouillent chaque point de rupture connu.


def test_devil_extreme_rate_does_not_raise():
    # r·T très négatif → `math.exp` déborde (OverflowError), pas un simple inf
    assert bs_price(S, K, T, -1000.0, SIG, "call") is None
    assert bs_greeks(S, K, T, -1000.0, SIG, "call")["delta"] is None
    assert implied_vol(10.0, S, K, T, -1000.0, "call") is None


def test_devil_vol_time_underflow_does_not_raise():
    # σ·√T s'annule par underflow → division par zéro sur d1
    assert bs_price(S, K, 1e-300, R, 1e-300, "call") is None
    assert bs_greeks(S, K, 1e-300, R, 1e-300, "call")["gamma"] is None


def test_devil_moneyness_ratio_underflow_does_not_raise():
    # S/K sous-déborde à 0 → `math.log(0)` lève ValueError
    assert bs_price(1e-300, 1e308, T, R, SIG, "call") is None
    assert bs_greeks(1e-300, 1e308, T, R, SIG, "put")["vega"] is None


def test_devil_absurd_sigma_stays_finite():
    # σ = 1000 : le call vaut le sous-jacent, jamais un NaN
    p = bs_price(S, K, T, R, 1000.0, "call")
    assert p is not None and math.isfinite(p) and abs(p - S) < 1e-6
    g = bs_greeks(S, K, T, R, 1000.0, "call")
    assert all(v is None or math.isfinite(v) for v in g.values())


def test_devil_negative_rates_are_valid_market_data():
    # taux négatifs = réalité de marché (EUR/CHF), pas une aberration : on price normalement
    put = bs_price(S, K, T, -0.5, SIG, "put")
    call = bs_price(S, K, T, -0.5, SIG, "call")
    assert put is not None and call is not None
    assert abs((call - put) - (S - K * math.exp(0.5 * T))) < 1e-9      # parité tient


def test_devil_ultra_short_expiry_greeks_finite():
    # T = 1 seconde : gamma explose, vega s'effondre — mais TOUT reste fini (jamais inf/NaN)
    g = bs_greeks(S, K, 1.0 / 31_536_000, R, SIG, "call")
    assert all(v is not None and math.isfinite(v) for v in g.values())
    assert g["gamma"] > 1.0 and 0.0 < g["vega"] < 1.0                  # explosif mais borné


def test_devil_aberrant_strikes_finite():
    for strike in (10.0 * S, 0.01 * S, 1e6, 1e-6):
        p = bs_price(S, strike, T, R, SIG, "call")
        assert p is not None and math.isfinite(p) and p >= 0.0


def test_devil_iv_on_put_call_parity_violation():
    # prix incohérents entre les deux pattes : chacun est jugé sur SES bornes d'arbitrage
    call = bs_price(S, K, T, R, SIG, "call")
    assert implied_vol(call, S, K, T, R, "put") is None or \
        implied_vol(call, S, K, T, R, "put") > 0          # jamais un NaN, jamais une exception


def test_devil_price_chain_survives_crash_inducing_rows():
    """GARANTIE D'INTÉGRATION : une ligne aux paramètres explosifs ne doit pas emporter la chaîne."""
    good = {"strike": 100.0, "expiry_years": 0.5,
            "call_price": bs_price(S, 100.0, 0.5, R, 0.25, "call"),
            "put_price": bs_price(S, 100.0, 0.5, R, 0.25, "put")}
    rows = [{"strike": 1e308, "expiry_years": 1e-300, "call_price": 1.0},
            {"strike": 1e-300, "expiry_years": 1e300, "call_price": 1.0}, good]
    out = price_chain(rows, underlying=S, r=R)
    assert len(out) == 3                                   # aucune ligne perdue, aucune exception
    assert abs(out[-1]["call"]["iv"] - 0.25) < 1e-6        # la ligne saine reste exacte
    for row in out[:2]:
        assert row["call"]["iv"] is None                   # les aberrantes → None, pas un nombre


def test_devil_price_chain_extreme_rate_does_not_raise():
    rows = [{"strike": 100.0, "expiry_years": 1.0, "call_price": 5.0}]
    out = price_chain(rows, underlying=S, r=-1000.0)
    assert len(out) == 1 and out[0]["call"]["iv"] is None


def test_devil_exhaustive_magnitude_sweep_never_raises_nor_emits_non_finite():
    """BALAYAGE EXHAUSTIF des magnitudes : le contrat (« jamais lever, jamais émettre inf/NaN »)
    doit tenir sur TOUTE combinaison, pas seulement sur les cas qu'on a su imaginer — un garde posé
    sur le noyau ne protège pas les formules de Grecques, qui ont chacune leur dénominateur."""
    vals = [1e-300, 1e-8, 0.01, 1.0, 100.0, 1e8, 1e300]
    rates = [-1000.0, -0.5, 0.0, 0.05, 1e6]
    sigs = [1e-300, 1e-8, 0.2, 1000.0, 1e300]
    for s, k, t, r, sig, kind in itertools.product(vals, vals, vals, rates, sigs, ("call", "put")):
        price = bs_price(s, k, t, r, sig, kind)                  # ne doit jamais lever
        assert price is None or math.isfinite(price)
        for v in bs_greeks(s, k, t, r, sig, kind).values():
            assert v is None or math.isfinite(v)


def test_devil_exhaustive_iv_sweep_never_raises_nor_emits_absurd_vol():
    for s, k, t, r, price, kind in itertools.product(
            [1e-8, 100.0, 1e300], [1e-8, 100.0, 1e300], [1e-300, 1.0, 1e300],
            [-1000.0, -0.5, 0.0, 0.05, 1e6], [0.0, 1e-9, 50.0, 1e300], ("call", "put")):
        iv = implied_vol(price, s, k, t, r, kind)                # ne doit jamais lever
        assert iv is None or (math.isfinite(iv) and iv > 0)
