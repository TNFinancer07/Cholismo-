"""Moteur Black-Scholes : pricing, Grecques, inversion d'IV (D-044).

Tarification européenne Black-Scholes-Merton (sans dividende, `v1 provisional`) et extraction des
Grecques, plus l'inversion numérique de la volatilité implicite. Sert la chaîne d'options OMON
(D-039), qui jusqu'ici ne faisait que RELAYER les Grecques de la source : ici elles sont CALCULÉES,
donc identiques pour les deux opérateurs et testables.

Notes de conception :
- **Conventions de Grecques figées ici** pour que l'affichage ne les réinvente jamais : `theta` par
  AN (diviser par 365 pour un « par jour »), `vega` pour une variation de vol de **1.0** (diviser
  par 100 pour « par point de % »), `vanna` = ∂Delta/∂σ.
- **IV : Newton-Raphson** (départ Brenner-Subrahmanyam) avec **repli BISSECTION** dès que Newton
  sort des bornes ou stagne — le vega tend vers 0 sur les options très ITM/OTM et Newton y diverge.
  Bissection sur `[1e-6, 5.0]`, donc bornée et **déterministe**.
- **Pur** (aucun état caché, aucun LLM), hors hot path (§7).

**Bornes de magnitude — le contrat central.** La FINITUDE des entrées ne suffit pas : en float64,
ce sont les MAGNITUDES qui cassent, et chaque rupture lève une exception plutôt que de produire un
`inf` inoffensif. Les quatre points de rupture connus :
| Expression | Rupture | Seuil |
|---|---|---|
| `K·e^{−rT}` | `OverflowError` | `r·T ≲ −710` |
| `σ·√T` | annulation par underflow → division par zéro | produit `< ~1e-308` |
| `ln(S/K)` | `ValueError` (domaine) | `S/K` sous-déborde à `0` |
| `pdf/(S·σ·√T)` (gamma) | dénominateur sous-débordé → division par zéro | produit `< ~1e-308` |
Chacune retombe sur `None`, **par Grecque** : une Grecque indéfinie ne vaut jamais `0.0` (qui se
lirait comme une mesure réelle) ni `inf`. Le prix est lui aussi validé fini avant d'être renvoyé.
Deux balayages exhaustifs (18 230 combinaisons de magnitudes) verrouillent ce contrat en test.

FAIL-CLOSED (§3) : entrée non-finie, `S ≤ 0`, `K ≤ 0`, `T ≤ 0`, `σ ≤ 0`, type d'option inconnu →
`None`. Prix de marché hors bornes d'arbitrage (sous la valeur intrinsèque, ou au-dessus de `S`
pour un call / `K` pour un put) → `None` : une donnée aberrante ne produit JAMAIS une vol inventée.
Prix collé à l'intrinsèque → `None` aussi : sans valeur temps, la vol n'est pas identifiable.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_IV_LO, _IV_HI = 1e-6, 5.0          # bornes de recherche de la vol (bissection)
_NEWTON_ITERS, _BISECT_ITERS = 24, 80
_IV_TOL = 1e-9
_GREEK_KEYS = ("delta", "gamma", "theta", "vega", "vanna")


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _is_kind(k: Any) -> bool:
    """Type d'option reconnu. Un `kind` inconnu est une donnée invalide, pas un défaut par défaut."""
    return k in ("call", "put")


def _core(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float, float] | None:
    """`(d1, d2, K·e^{−rT})` ou `None` si le modèle est numériquement indéfini.

    Applique les trois premières bornes de magnitude du tableau en tête de module (`e^{−rT}`,
    `σ·√T`, `ln(S/K)`) : chacune retombe sur `None` (§3) au lieu de lever."""
    try:
        vol_t = sigma * math.sqrt(T)
        if not (math.isfinite(vol_t) and vol_t > 0):
            return None                                # σ·√T annulé (underflow) ou dégénéré
        ratio = S / K
        if not (math.isfinite(ratio) and ratio > 0):
            return None                                # S/K sous-déborde ou explose
        d1 = (math.log(ratio) + (r + 0.5 * sigma * sigma) * T) / vol_t
        disc = K * math.exp(-r * T)
        if not (math.isfinite(d1) and math.isfinite(disc)):
            return None
        return d1, d1 - vol_t, disc
    except (OverflowError, ValueError, ZeroDivisionError):
        return None


def _valid(S: Any, K: Any, T: Any, r: Any, sigma: Any) -> bool:
    return (_finite(S) and _finite(K) and _finite(T) and _finite(r) and _finite(sigma)
            and S > 0 and K > 0 and T > 0 and sigma > 0)


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: Any) -> float | None:
    """Prix Black-Scholes européen, ou `None` si un paramètre rend le modèle indéfini (§3)."""
    if not _valid(S, K, T, r, sigma) or not _is_kind(kind):
        return None
    core = _core(S, K, T, r, sigma)
    if core is None:
        return None
    d1, d2, disc = core
    price = (S * _norm_cdf(d1) - disc * _norm_cdf(d2)) if kind == "call" \
        else (disc * _norm_cdf(-d2) - S * _norm_cdf(-d1))
    return price if math.isfinite(price) else None      # jamais un inf/NaN présenté comme un prix


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: Any) -> dict:
    """Grecques (conventions en tête de module). Chaque valeur vaut `None` si indéfinie — on ne
    renvoie jamais 0.0 pour « inconnu », qui se lirait comme une mesure réelle (§3)."""
    if not _valid(S, K, T, r, sigma) or not _is_kind(kind):
        return dict.fromkeys(_GREEK_KEYS)
    core = _core(S, K, T, r, sigma)
    if core is None:
        return dict.fromkeys(_GREEK_KEYS)
    d1, d2, disc = core
    sqrt_t = math.sqrt(T)
    pdf = _norm_pdf(d1)

    def g(fn) -> float | None:
        """Une Grecque, ou `None` si son calcul est numériquement indéfini. L'évaluation est
        ISOLÉE par Grecque : chaque formule a son propre dénominateur (cf. `gamma` dans le tableau
        des bornes en tête de module), donc l'une peut être indéfinie pendant que les autres
        restent exactes. Indéfinie → `None`, jamais `0.0` ni `inf` (§3)."""
        try:
            v = fn()
        except (OverflowError, ValueError, ZeroDivisionError):
            return None
        return v if math.isfinite(v) else None

    delta = g(lambda: _norm_cdf(d1) if kind == "call" else _norm_cdf(d1) - 1.0)
    theta = g(lambda: (-S * pdf * sigma / (2.0 * sqrt_t))
              + (-r * disc * _norm_cdf(d2) if kind == "call" else r * disc * _norm_cdf(-d2)))
    return {
        "delta": delta,
        "gamma": g(lambda: pdf / (S * sigma * sqrt_t)),
        "theta": theta,                                  # par an
        "vega": g(lambda: S * pdf * sqrt_t),             # pour σ + 1.0
        "vanna": g(lambda: -pdf * d2 / sigma),           # ∂Delta/∂σ
    }


def implied_vol(price: Any, S: float, K: float, T: float, r: float, kind: Any) -> float | None:
    """Volatilité implicite par Newton-Raphson, repli bissection. `None` si la donnée de marché est
    aberrante (hors bornes d'arbitrage) ou si aucune racine n'est trouvée dans `[1e-6, 5.0]`."""
    if not (_finite(price) and _finite(S) and _finite(K) and _finite(T) and _finite(r)
            and S > 0 and K > 0 and T > 0 and price >= 0) or not _is_kind(kind):
        return None
    try:
        disc = K * math.exp(-r * T)
    except OverflowError:
        return None                                   # r·T ingérable → aucune borne calculable
    if not math.isfinite(disc):
        return None
    # bornes d'arbitrage : sous l'intrinsèque ou au-dessus du plafond → donnée aberrante (§3)
    if kind == "call":
        lo_bound, hi_bound = max(0.0, S - disc), S
    else:
        lo_bound, hi_bound = max(0.0, disc - S), disc
    if price < lo_bound - 1e-12 or price > hi_bound + 1e-12:
        return None
    # IDENTIFIABILITÉ : un prix collé à la valeur intrinsèque ne porte AUCUNE valeur temps, donc
    # aucune information de volatilité — sur une option très ITM le prix est bit-identique pour
    # σ = 0.1 et σ = 0.4. Renvoyer un nombre reviendrait à fabriquer une précision absente de la
    # donnée : on renvoie `None` (§3). Seuil à quelques ULP de l'échelle du contrat.
    if price - lo_bound <= max(1e-12, 1e-14 * max(S, K)):
        return None

    def diff(sig: float) -> float:
        p = bs_price(S, K, T, r, sig, kind)
        return math.inf if p is None else p - price

    # Newton-Raphson depuis l'approximation Brenner-Subrahmanyam
    sigma = max(_IV_LO, min(_IV_HI, math.sqrt(2.0 * math.pi / T) * price / S))
    for _ in range(_NEWTON_ITERS):
        f = diff(sigma)
        if not math.isfinite(f):
            break
        if abs(f) < _IV_TOL:
            return sigma
        vega = bs_greeks(S, K, T, r, sigma, kind)["vega"]
        if vega is None or not math.isfinite(vega) or vega < 1e-8:
            break                                     # vega ≈ 0 → Newton diverge : on bascule
        step = f / vega
        nxt = sigma - step
        if not math.isfinite(nxt) or nxt <= _IV_LO or nxt >= _IV_HI:
            break                                     # sortie de bornes : on bascule
        if abs(nxt - sigma) < _IV_TOL:
            return nxt
        sigma = nxt

    # Repli BISSECTION : bornée, déterministe, insensible au vega nul
    lo, hi = _IV_LO, _IV_HI
    f_lo, f_hi = diff(lo), diff(hi)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None                                   # pas de changement de signe → aucune racine
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        f_mid = diff(mid)
        if not math.isfinite(f_mid):
            return None
        if abs(f_mid) < _IV_TOL or (hi - lo) < _IV_TOL:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def _leg(price: Any, S: float, K: float, T: float, r: float, kind: str) -> dict:
    """Une patte enrichie : IV inversée depuis le prix de marché, puis Grecques À CETTE IV. IV
    introuvable → toutes les Grecques `None` (on ne price pas sur une vol inventée, §3)."""
    iv = implied_vol(price, S, K, T, r, kind)
    if iv is None:
        return {"iv": None, **dict.fromkeys(_GREEK_KEYS)}
    return {"iv": iv, **bs_greeks(S, K, T, r, iv, kind)}


def price_chain(rows: Sequence[Any] | None, underlying: float, r: float) -> list[dict]:
    """Enrichit une chaîne ENTIÈRE en un appel (batch) : pour chaque `{strike, expiry_years,
    call_price, put_price}`, l'IV implicite et les Grecques des deux pattes.

    Chaque ligne est traitée ISOLÉMENT : une ligne corrompue (non-dict, strike/échéance non-finis)
    est écartée seule et n'invalide jamais le reste de la chaîne (§3). Sous-jacent invalide →
    chaîne vide, car aucune moneyness ni aucun prix n'a de sens sans lui."""
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) \
            or not (_finite(underlying) and underlying > 0) or not _finite(r):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        K, T = row.get("strike"), row.get("expiry_years")
        if not (_finite(K) and _finite(T) and K > 0 and T > 0):
            continue
        out.append({
            "strike": float(K), "expiry_years": float(T),
            "call": _leg(row.get("call_price"), underlying, float(K), float(T), r, "call"),
            "put": _leg(row.get("put_price"), underlying, float(K), float(T), r, "put"),
        })
    return out
