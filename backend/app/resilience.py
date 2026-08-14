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

**Le modèle de trade est volontairement pauvre** : R fixe gagné, 1R perdu, slippage retranché des
deux côtés. Un modèle riche (scale-out, stops variables, corrélation intra-journée) donnerait des
nombres plus précis sur des hypothèses tout aussi inconnues — de la fausse précision. Le modèle
est écrit dans la sortie (`model`), pour qu'on sache ce qu'on lit.

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
    cost = slippage_ticks * tick_usd
    gain, loss = r_usd - cost, -(r_usd + cost)
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
            "description": "gain fixe +1R, perte fixe −1R, slippage retranché des deux côtés",
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
