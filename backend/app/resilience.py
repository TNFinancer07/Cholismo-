"""Carte de sensibilité à la ruine — slippage × taux de réussite (D-102).

**Ce n'est PAS une prédiction du risque de ruine du compte.** Le taux de réussite réel du LSR est
**inconnu** — c'est précisément ce que la calibration doit mesurer (`CLAUDE §10`). Une matrice
qui annoncerait « votre risque de ruine est de 12 % » présenterait une hypothèse comme une mesure,
ce que `§3` interdit.

Ce que la carte dit, et c'est utile : **comment le risque de ruine varie selon l'hypothèse**. Elle
répond à « à partir de quel taux de réussite le compte tient-il ? » et « combien coûte un tick de
slippage ? » — deux questions dont les réponses ne dépendent pas de connaître le vrai taux.

Chaque cellule est donc étiquetée `HYPOTHESIS`, et la structure entière porte
`kind: "sensitivity_map"`. Aucun champ ne s'appelle « probabilité de ruine du compte ».

---

**Ce qui est réel dans ce calcul, et ce qui est posé.**

RÉEL — vient de la configuration du compte, pas d'une idée : capital initial, drawdown maximal,
perte journalière maximale (`ApexEodPreset`), et l'unité R (`R_UNIT_USD`).

POSÉ — les deux axes de la carte, qui sont l'objet même de l'exploration : taux de réussite et
slippage. Ils ne prétendent à rien.

**Le modèle de trade est volontairement pauvre** : +1R gagné au TP, −1R perdu au stop. Un modèle
riche (scale-out, stops variables, corrélation intra-journée) donnerait des nombres plus précis
sur des hypothèses tout aussi inconnues — de la fausse précision. Le modèle est écrit dans la
sortie (`model`), pour qu'on sache ce qu'on lit.

**Le slippage ne frappe QUE la perte** (canon §9, corrigé en D-107) : l'entrée est LIMITE et le TP
est LIMITE — un ordre limite est rempli à son prix ou pas du tout, il ne glisse pas. Seule la
sortie au stop part au marché. Le retrancher des deux côtés, comme le faisait la première version,
surestimait le coût sur les gagnants.

**Déterministe.** Graine fixée par défaut : deux lectures de la même carte doivent donner les
mêmes nombres, sinon l'opérateur croirait voir une évolution là où il ne voit que du bruit.
"""
from __future__ import annotations

import random
from typing import Any, Optional

from . import config
from .risk_sizer import APEX_EOD_50K, ApexEodPreset

#: Axes de la carte. Quatre valeurs chacun — la grille 4×4 de la maquette. Ce sont des
#: HYPOTHÈSES explorées, jamais des estimations.
WIN_RATES = (0.35, 0.45, 0.55, 0.65)
SLIPPAGE_TICKS = (0.0, 0.5, 1.0, 2.0)

#: MES : 1 tick = 1.25 $ (5 $/point ÷ 4). Valeur de contrat, pas une hypothèse.
MES_TICK_USD = 1.25

DEFAULT_TRADES = 50          # l'horizon du challenge (`CLAUDE §1` : 50+ trades)
DEFAULT_SIMS = 2000
DEFAULT_SEED = 12345


def _ruin_probability(*, win_rate: float, slippage_ticks: float, preset: ApexEodPreset,
                      r_usd: float, tick_usd: float, trades: int, sims: int,
                      rng: random.Random) -> float:
    """Part des trajectoires qui touchent une limite de compte avant la fin de l'horizon.

    « Ruine » = drawdown maximal atteint **ou** limite de perte journalière franchie — les deux
    tuent un compte prop firm, et n'en retenir qu'une flatterait le résultat.
    """
    # CANON D'EXÉCUTION (D-107) : entrée LIMITE + bracket OCO, TP LIMITE fixe. Un ordre limite
    # ne subit PAS de slippage — il est rempli à son prix ou pas du tout. Seule la sortie au
    # STOP part au marché et paie le slippage. La première version le retranchait des DEUX côtés,
    # ce qui surestimait le coût sur les gagnants et sous-estimait donc la robustesse.
    cost = slippage_ticks * tick_usd
    gain, loss = r_usd, -(r_usd + cost)
    floor = -preset.max_drawdown
    ruined = 0

    for _ in range(sims):
        equity = 0.0
        day_loss = 0.0
        for k in range(trades):
            # UN tirage, UN résultat, appliqué aux deux compteurs. Redériver le résultat du signe
            # de l'équité (première version) donnait un P&L journalier sans rapport avec les
            # trades — la limite journalière ne mordait jamais.
            resultat = gain if rng.random() < win_rate else loss
            equity += resultat
            day_loss += resultat
            # Journée de ~5 trades — borne de regroupement, pas une prédiction de cadence.
            if (k + 1) % 5 == 0:
                day_loss = 0.0
            if equity <= floor or day_loss <= -preset.daily_loss_limit:
                ruined += 1
                break
    return ruined / sims if sims else 0.0


def sensitivity_map(*, preset: Optional[ApexEodPreset] = None, trades: int = DEFAULT_TRADES,
                    sims: int = DEFAULT_SIMS, seed: Optional[int] = DEFAULT_SEED,
                    r_usd: Optional[float] = None,
                    tick_usd: float = MES_TICK_USD) -> dict[str, Any]:
    """Carte 4×4 `slippage × taux de réussite`. Toujours calculable — elle n'a besoin d'AUCUNE
    donnée historique, puisqu'elle explore des hypothèses. C'est ce qui la distingue de la
    matrice de calibration, qui refuse de chiffrer sous échantillon insuffisant.

    Une carte de sensibilité sans données n'est pas un faux : elle ne prétend rien sur le passé.
    """
    p = preset or APEX_EOD_50K
    r = r_usd if r_usd is not None else config.R_UNIT_USD
    rng = random.Random(seed)

    cells = []
    for slip in SLIPPAGE_TICKS:
        row = []
        for wr in WIN_RATES:
            row.append({
                "win_rate": wr,
                "slippage_ticks": slip,
                "ruin_probability": round(_ruin_probability(
                    win_rate=wr, slippage_ticks=slip, preset=p, r_usd=r, tick_usd=tick_usd,
                    trades=trades, sims=sims, rng=rng), 4),
                # Chaque cellule le redit : sans cela, un tableau extrait de son contexte se
                # lirait comme une mesure.
                "status": "HYPOTHESIS",
            })
        cells.append(row)

    return {
        "kind": "sensitivity_map",
        "disclaimer": ("Carte de SENSIBILITÉ : chaque cellule suppose un taux de réussite. "
                       "Le taux réel du LSR est INCONNU — c'est ce que la calibration mesure. "
                       "Aucune cellule n'est une prédiction du risque de ce compte."),
        "axes": {"slippage_ticks": list(SLIPPAGE_TICKS), "win_rate": list(WIN_RATES)},
        "cells": cells,
        "model": {
            "description": ("gain fixe +1R au TP LIMITE (sans slippage), perte fixe −1R au STOP "
                            "au marché (slippage retranché) — canon §9"),
            "r_usd": r, "tick_usd": tick_usd, "trades": trades, "sims": sims, "seed": seed,
            "ruin": "drawdown maximal atteint OU limite de perte journalière franchie",
            "day_grouping_trades": 5,
        },
        "account": {"label": p.label, "initial_capital": p.initial_capital,
                    "max_drawdown": p.max_drawdown, "daily_loss_limit": p.daily_loss_limit},
    }


def slippage_cost_in_win_rate_points(carte: dict[str, Any]) -> dict[str, Any]:
    """Combien de POINTS de taux de réussite coûte un tick de slippage, à risque de ruine égal.

    C'est l'affirmation que la maquette v17 avance en note (« un tick coûte environ 5 points de
    taux de réussite »). Elle n'y est **pas calculée** — elle est écrite en dur. Ici on la mesure
    sur la carte.

    Méthode : à 0 et à 1 tick, on cherche le plus petit taux de réussite de la grille dont le
    risque de ruine passe sous 50 %, et on rend l'écart.

    **Un écart de 0 ne signifie PAS « le slippage est gratuit »** : il signifie « le coût est plus
    petit que le pas de la grille ». Rendre `0.0` sec ferait lire une absence de coût là où il y a
    une absence de résolution — le statut le dit explicitement.
    """
    def seuil(slip: float) -> Optional[float]:
        for row in carte.get("cells", []):
            if not row or row[0]["slippage_ticks"] != slip:
                continue
            for cell in row:
                if cell["ruin_probability"] < 0.5:
                    return float(cell["win_rate"])
        return None

    axes = carte.get("axes", {}).get("win_rate") or []
    pas = round((max(axes) - min(axes)) * 100 / (len(axes) - 1), 1) if len(axes) > 1 else None
    a, b = seuil(0.0), seuil(1.0)
    if a is None or b is None:
        return {"status": "NOT_MEASURABLE", "points": None, "grid_step_points": pas,
                "detail": "aucun taux de la grille ne passe sous 50 % de ruine"}
    ecart = round((b - a) * 100, 1)
    if ecart == 0.0:
        return {"status": "BELOW_GRID_RESOLUTION", "points": None, "grid_step_points": pas,
                "detail": (f"le coût d'un tick est inférieur au pas de la grille "
                           f"({pas} points) — non nul, non résolu")}
    return {"status": "MEASURED", "points": ecart, "grid_step_points": pas,
            "detail": "écart mesuré entre les seuils de ruine à 0 et 1 tick"}


# ---------------------------------------------------------------------------------------------
# Biais du survivant (D-103)
# ---------------------------------------------------------------------------------------------
#
# Calculer le DD95 sur les seules trajectoires **survivantes** écarte les pires cas **par
# construction** : celles qui ont explosé ne sont plus dans l'échantillon dont on tire le
# quantile. Le nombre obtenu est plus flatteur, et il ne dit pas qu'il l'est.
#
# Le terminal publie donc TOUJOURS le chiffre toutes trajectoires, le chiffre survivantes, et
# l'ÉCART entre les deux. C'est l'écart qui est l'information : il mesure de combien on se
# mentirait en ne regardant que les survivants.
#
# Contrairement à la carte de sensibilité, ce calcul part de données RÉELLES — les R-multiples
# réconciliés. Il refuse donc de chiffrer sous échantillon insuffisant (§3), là où la carte,
# qui n'explore que des hypothèses, est toujours calculable.

def _max_drawdown_r(path: list[float]) -> float:
    """Drawdown maximal d'une trajectoire, en R. Positif par convention (0 = jamais en perte)."""
    pic = 0.0
    equity = 0.0
    pire = 0.0
    for r in path:
        equity += r
        pic = max(pic, equity)
        pire = max(pire, pic - equity)
    return pire


def _percentile(values: list[float], q: float) -> Optional[float]:
    """Percentile par interpolation linéaire. `None` sur liste vide — jamais 0, qui se lirait
    « aucun drawdown »."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    bas = int(pos)
    haut = min(bas + 1, len(ordered) - 1)
    frac = pos - bas
    return ordered[bas] + (ordered[haut] - ordered[bas]) * frac


def survivor_bias(r_multiples: list[float], *, preset: Optional[ApexEodPreset] = None,
                  r_usd: Optional[float] = None, sims: int = DEFAULT_SIMS,
                  seed: Optional[int] = DEFAULT_SEED,
                  min_sample: Optional[int] = None) -> dict[str, Any]:
    """DD95 toutes trajectoires vs survivantes, et l'écart entre les deux.

    Rééchantillonnage bootstrap des R-multiples RÉCONCILIÉS. « Survivante » = trajectoire dont le
    drawdown maximal n'a jamais atteint la limite du compte, convertie en R.

    Sous `min_sample` observations → `NOT_ENOUGH_DATA` et **aucun nombre** : un DD95 sur trois
    trades décrirait ces trois trades, pas un risque.
    """
    p = preset or APEX_EOD_50K
    r = r_usd if r_usd is not None else config.R_UNIT_USD
    seuil_n = min_sample if min_sample is not None else config.MC_MIN_TRADES
    echantillon = [float(x) for x in r_multiples if isinstance(x, (int, float))]

    ruine_r = p.max_drawdown / r if r else None
    base = {"kind": "survivor_bias", "n_reconciled": len(echantillon),
            "min_sample": seuil_n, "ruin_threshold_r": ruine_r}

    if len(echantillon) < seuil_n or not ruine_r:
        return {**base, "status": "NOT_ENOUGH_DATA", "dd95_all": None,
                "dd95_survivors": None, "bias_r": None, "survival_rate": None,
                "detail": (f"{len(echantillon)} R-multiples réconciliés, {seuil_n} requis — "
                           "un DD95 sous ce seuil décrirait l'échantillon, pas un risque")}

    rng = random.Random(seed)
    n = len(echantillon)
    tous: list[float] = []
    survivants: list[float] = []
    for _ in range(sims):
        path = [echantillon[rng.randrange(n)] for _ in range(n)]
        dd = _max_drawdown_r(path)
        tous.append(dd)
        if dd < ruine_r:
            survivants.append(dd)

    dd_all = _percentile(tous, 0.95)
    dd_surv = _percentile(survivants, 0.95)
    taux = len(survivants) / sims if sims else None
    # AUCUNE trajectoire n'a péri → l'ensemble des survivantes EST l'ensemble complet, et l'écart
    # vaut structurellement zéro. Le publier comme « biais mesuré à 0 » ferait lire « pas de biais »
    # là où il faut lire « rien n'a été exclu, donc rien à biaiser ». Même leçon que
    # BELOW_GRID_RESOLUTION (D-102) : une absence de mesure n'est pas une mesure nulle.
    if taux is not None and taux >= 1.0:
        return {
            **base, "status": "NO_RUIN_OBSERVED",
            "dd95_all": round(dd_all, 3) if dd_all is not None else None,
            "dd95_survivors": round(dd_surv, 3) if dd_surv is not None else None,
            "bias_r": None, "survival_rate": taux,
            "model": {"resample": "bootstrap", "sims": sims, "seed": seed, "path_length": n,
                      "survivor": "drawdown maximal resté sous la limite du compte"},
            "detail": ("aucune trajectoire n'atteint la limite du compte sur cet horizon : "
                       "l'ensemble survivant est l'ensemble complet, il n'y a pas de biais à "
                       "mesurer (et non : un biais nul)"),
        }
    return {
        **base,
        "status": "OK",
        "dd95_all": round(dd_all, 3) if dd_all is not None else None,
        "dd95_survivors": round(dd_surv, 3) if dd_surv is not None else None,
        # L'information n'est pas le DD95, c'est l'ÉCART : de combien on se mentirait en ne
        # regardant que les survivants.
        "bias_r": (round(dd_all - dd_surv, 3)
                   if dd_all is not None and dd_surv is not None else None),
        "survival_rate": round(taux, 4) if taux is not None else None,
        "model": {"resample": "bootstrap", "sims": sims, "seed": seed, "path_length": n,
                  "survivor": "drawdown maximal resté sous la limite du compte"},
        "detail": ("Le DD95 des SURVIVANTES écarte les pires cas par construction. "
                   "L'écart mesure de combien on se mentirait en ne regardant qu'elles."),
    }
