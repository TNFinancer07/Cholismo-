"""LSR v1.2 — frontières de compte + gates F2 et F3-ATR (D-071).

Port de `lsr-engine/src/frontiers.ts` et des deux règles Phase 0 que le Python ne savait pas
prononcer. Tout est PUR : compte et mesures en entrée, verdict en sortie — aucune horloge lue,
aucun état retenu, aucun ordre passé (§2.1).

**Convention de signe** : les planchers sont des NIVEAUX d'équité, les grandeurs exposées sont
POSITIVES (marge de perte restante). Une frontière ne descend jamais sous zéro : sous le plancher
il ne reste pas « moins que rien » à risquer, il ne reste rien.

**La divergence corrigée ici.** `risk_sizer.compute_buffer` calcule `equity − (day_start − DLL)`.
Sur une matinée GAGNANTE ce terme vaut `DLL + profit` — il dépasse le DLL. La référence, elle,
plafonne l'allocation quotidienne au DLL quoi qu'il arrive : `max(0, DLL − perte_du_jour)`. À
+500 $ sur un Apex 50K, le Python allouait donc `1500/5 = 300 $` de risque là où la référence
alloue `1000/5 = 200 $` — **50 % de plus, précisément après une bonne matinée**. C'est
`frontiere_jour_restante` qui fait foi pour le sizing depuis D-071.

`compute_buffer` SURVIT, et ce n'est pas un doublon : il est SIGNÉ, donc il sait dire « tu es
passé SOUS la ligne » (−500) là où la frontière bornée dirait « tu es dessus » (0). L'un affiche,
l'autre dimensionne ; un test verrouille le fait qu'ils ne peuvent pas se contredire sur la seule
question qui compte — reste-t-il de quoi trader ?
"""
from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel

#: Part de la frontière du JOUR au-delà de laquelle la séance est finie (`f2CircuitThreshold`).
F2_CIRCUIT_THRESHOLD = 0.8
#: Expansion d'ATR au-delà de laquelle on ne trade plus (`f3AtrMultiplier`).
F3_ATR_MULTIPLIER = 1.5


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class AccountFrontiers(BaseModel):
    """Grandeurs de risque DÉRIVÉES du compte, toutes positives.

    `frontiere_jour_initiale` est figée à l'ouverture (dénominateur honnête de F2 : la comparer à
    la frontière courante donnerait toujours 100 %). `frontiere_jour_restante` est ce qui reste
    réellement — c'est elle que le RiskSizer divise par 5."""
    perte_jour: float
    frontiere_jour_initiale: float
    frontiere_jour_restante: float


def derive_account_frontiers(account: Any) -> AccountFrontiers:
    """Port de `deriveAccountFrontiers`. Ne lève jamais : une grandeur non finie produit une
    frontière NULLE (donc un refus en aval), pas une exception ni un nombre inventé (§3)."""
    for champ in ("current_equity", "day_start_equity", "drawdown_floor", "daily_loss_limit"):
        if not _finite(getattr(account, champ, None)):
            return AccountFrontiers(perte_jour=0.0, frontiere_jour_initiale=0.0,
                                    frontiere_jour_restante=0.0)
    equity = float(account.current_equity)
    day_start = float(account.day_start_equity)
    floor = float(account.drawdown_floor)
    dll = float(account.daily_loss_limit)

    room_ouverture = day_start - floor
    room_maintenant = equity - floor
    perte_jour = max(0.0, day_start - equity)

    # Le DLL borne l'allocation du jour DANS LES DEUX SENS : une matinée gagnante ne l'augmente
    # pas. C'est LA correction de D-071 — `equity − (day_start − DLL)` y ajoutait le profit.
    initiale = max(0.0, min(room_ouverture, dll))
    restante_du_jour = max(0.0, dll - perte_jour)
    restante = max(0.0, min(room_maintenant, restante_du_jour))
    return AccountFrontiers(perte_jour=perte_jour, frontiere_jour_initiale=initiale,
                            frontiere_jour_restante=restante)


def f2_daily_circuit_breaker(frontiers: AccountFrontiers) -> Optional[str]:
    """F2 — la séance est FINIE au-delà de `F2_CIRCUIT_THRESHOLD` de la frontière du jour.

    Sans cette règle, on continue à trader avec 200 $ de marge sur 1 000 : le sizer accepte
    (il trouvera toujours un contrat à 2.50 $), la discipline non. Une frontière initiale nulle
    ou négative coupe aussi — il n'y a pas de « 80 % de zéro » à calculer, il y a une séance qui
    n'aurait pas dû s'ouvrir."""
    if frontiers.frontiere_jour_initiale <= 0:
        return "F2_DAILY_CIRCUIT_BREAKER"
    if frontiers.perte_jour >= F2_CIRCUIT_THRESHOLD * frontiers.frontiere_jour_initiale:
        return "F2_DAILY_CIRCUIT_BREAKER"
    return None


def f3_atr_blocked(atr_fast: Any, atr_slow: Any,
                   multiplier: float = F3_ATR_MULTIPLIER) -> bool:
    """F3-ATR — `True` si la volatilité est en expansion ANORMALE, ou si on ne peut pas le dire.

    FAIL-CLOSED, et le piège est précis : `None > None` est faux, donc une comparaison naïve
    laisserait passer un ATR **absent** comme s'il avait été mesuré et jugé calme. La référence
    traite explicitement ce cas en blocage (`if (!(atrFast > 0) || !(atrSlow > 0)) return true`),
    et c'est le seul choix compatible avec « no signal without data » (§3). Un ATR nul ou négatif
    n'est pas une volatilité nulle : c'est un flux cassé."""
    if not (_finite(atr_fast) and atr_fast > 0):
        return True
    if not (_finite(atr_slow) and atr_slow > 0):
        return True
    return float(atr_fast) > float(atr_slow) * multiplier
