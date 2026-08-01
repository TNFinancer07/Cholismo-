"""La cascade commune aux cinq dimensions — D-057.

Ce que devient une série brute entre l'API et le score. La mécanique est PARTAGÉE par les cinq
dimensions, et le poids final ne dépend d'aucune d'elles (il vient du quadrant Bridgewater) :

    z_i   = (x_i − μ_252) / σ_252          # fenêtre en OBSERVATIONS, ddof=1
    div_i = z_i(base) − z_i(quote)         # divergence, pas niveau absolu
    D     = tanh( Σ w_i · div_i ) × timing_factor

Les specs tirent trois conséquences pratiques de cette formule ; elles sont la raison d'être de
chaque garde ci-dessous.

1. **Il faut de la profondeur, pas de la fraîcheur.** 252 points avant de produire quoi que ce
   soit. Sous la fenêtre, on ne rend pas un z-score « approximatif » — on ne rend rien (§3).
2. **La divergence annule les biais COMMUNS.** Corollaire rarement dit : un biais présent d'un
   seul côté ne disparaît pas et se lit comme du SIGNAL. C'est exactement le cas du PMI de D1
   (composite d'enquêtes Fed régionales contre indice de sentiment large) — le module ne peut
   pas le corriger, seulement ne pas l'aggraver.
3. **`tanh` écrase les extrêmes.** Utile contre les queues épaisses, mais une donnée aberrante
   non filtrée en amont ne se voit PAS dans le score final : elle s'y noie. D'où le signalement
   `outlier` **au niveau du z-score** — jamais un écrêtage silencieux, qui déciderait à la place
   de l'opérateur (§2.1).

Module PUR : aucune horloge, aucune I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

# Plancher d'écart-type. Sans lui, une série presque plate fabrique des z-scores de plusieurs
# milliers qui dominent toute la somme pondérée — le « piège du z-score » signalé pour le σ du
# BEER. v1 provisional (PLACEHOLDER §11).
MIN_SIGMA = 1e-6
# Au-delà, on SIGNALE. La valeur reste rendue telle quelle : écrêter serait corriger la donnée
# à la place de celui qui décide. v1 provisional.
OUTLIER_CAP = 5.0
# Tolérance sur la somme des poids : la matrice du quadrant somme à 1.00 par construction.
_WEIGHT_SUM_TOL = 1e-6


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class ZScoreResult:
    value: Optional[float]
    n: int                       # observations effectivement utilisées
    window: int
    mean: Optional[float]
    sigma: Optional[float]
    outlier: bool = False
    motif: str = ""              # vide si calculé — sinon, pourquoi pas (§3)


@dataclass(frozen=True)
class CascadeResult:
    score: Optional[float]
    raw: Optional[float]
    contributions: tuple[tuple[str, float], ...] = ()
    missing: tuple[str, ...] = ()
    motif: str = ""


def zscore(values: Sequence[Any], *, window: int) -> ZScoreResult:
    """z-score de la DERNIÈRE observation sur les `window` dernières, écart-type d'échantillon.

    La fenêtre est exprimée en OBSERVATIONS, jamais en jours calendaires : « un z-score sur
    252 jours n'a pas de sens sur une série trimestrielle »."""
    if not isinstance(window, int) or isinstance(window, bool) or window < 2:
        return ZScoreResult(None, 0, window if isinstance(window, int) else 0, None, None,
                            motif="fenêtre invalide — au moins 2 observations sont nécessaires")
    series = list(values) if isinstance(values, (list, tuple)) else []
    if len(series) < window:
        return ZScoreResult(None, len(series), window, None, None,
                            motif=f"profondeur insuffisante : {len(series)} observations pour une "
                                  f"fenêtre de {window} — le z-score n'existe pas encore")
    tail = series[-window:]
    if not all(_finite(v) for v in tail):
        return ZScoreResult(None, window, window, None, None,
                            motif="valeur non finie dans la fenêtre — série non exploitable")
    tail = [float(v) for v in tail]
    mean = sum(tail) / window
    variance = sum((v - mean) ** 2 for v in tail) / (window - 1)
    sigma = math.sqrt(variance)
    if not math.isfinite(sigma) or sigma < MIN_SIGMA:
        return ZScoreResult(None, window, window, mean, sigma,
                            motif="écart-type nul ou sous le plancher — une série plate n'a pas "
                                  "de z-score, elle a une division par zéro")
    value = (tail[-1] - mean) / sigma
    if not math.isfinite(value):
        return ZScoreResult(None, window, window, mean, sigma, motif="z-score non fini")
    return ZScoreResult(value, window, window, mean, sigma, outlier=abs(value) > OUTLIER_CAP)


def divergence(z_base: Any, z_quote: Any) -> Optional[float]:
    """`div = z(base) − z(quote)`. Une jambe manquante ne produit pas une divergence à moitié
    vraie : elle n'en produit aucune."""
    if not _finite(z_base) or not _finite(z_quote):
        return None
    out = float(z_base) - float(z_quote)
    return out if math.isfinite(out) else None


def aggregate(divergences: Mapping[str, Any], weights: Mapping[str, Any], *,
              timing_factor: Any = 1.0) -> CascadeResult:
    """`D = tanh(Σ w_i · div_i) × timing_factor`.

    Une composante manquante **n'est pas renormalisée** sur les présentes : cela changerait le
    sens de la mesure sans le dire — un D1 amputé du PMI (0.30, le plus gros poids) se lirait
    comme un D1 complet. Fail-closed : on rend `None` et on NOMME ce qui manque (§3)."""
    if not isinstance(weights, Mapping) or not weights:
        return CascadeResult(None, None, motif="aucun poids fourni")
    if not all(_finite(w) for w in weights.values()):
        return CascadeResult(None, None, motif="poids non finis")
    total = sum(float(w) for w in weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOL:
        return CascadeResult(None, None,
                             motif=f"les poids ne somment pas à 1.00 (somme = {total:.4f}) — "
                                   "une composante a été perdue en route")
    if not _finite(timing_factor) or float(timing_factor) <= 0.0:
        return CascadeResult(None, None,
                             motif="timing_factor absent ou invalide — le multiplicateur ne "
                                   "peut pas être deviné")
    source = divergences if isinstance(divergences, Mapping) else {}
    missing = tuple(sorted(k for k in weights if not _finite(source.get(k))))
    if missing:
        return CascadeResult(None, None, missing=missing,
                             motif=f"composante(s) absente(s) : {', '.join(missing)} — le score "
                                   "n'est pas renormalisé sur les présentes")
    contributions = tuple((k, float(weights[k]) * float(source[k])) for k in weights)
    raw = sum(c for _, c in contributions)
    if not math.isfinite(raw):
        return CascadeResult(None, None, contributions=contributions,
                             motif="somme pondérée non finie")
    score = math.tanh(raw) * float(timing_factor)
    if not math.isfinite(score):
        return CascadeResult(None, raw, contributions=contributions, motif="score non fini")
    return CascadeResult(score=score, raw=raw, contributions=contributions)
