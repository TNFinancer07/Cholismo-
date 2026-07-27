"""Couche Compte & RiskSizer — frontières de risque prop-firm EOD (D-047).

Port Python de la couche compte du moteur LSR v1.2 (`frontiers.ts`/`risksizer.ts`, externe au
dépôt). Trois idées, toutes FAIL-CLOSED :

1. **Le capital tradable n'est PAS l'équité — c'est la DISTANCE VERS LA MORT.**
   `buffer = min(equity − drawdown_floor, equity − (day_start − DLL))` : la plus proche des deux
   frontières (plancher de campagne / limite de perte du jour) est la seule qui compte. Sur un
   Apex 50K EOD à l'ouverture : `min(2500, 1000) = 1000` → le DLL est la frontière contraignante
   (conséquence de sizing du doc LSR : mécaniquement plus serré qu'une firme sans DLL).

2. **Règle stricte du 1/5e** : risque alloué au prochain trade = `buffer / 5` (doc v1.1,
   `bufferDivisor`). Contrats = `floor(risque / (ticks_de_stop × valeur_tick))` — floor, jamais
   d'arrondi vers le haut : on ne s'endette pas d'un demi-contrat d'optimisme.

3. **F8 coupe-circuit** : taille < 1 OU buffer ≤ 0 → `REJECTED / INSUFFICIENT_BUFFER`. Entrée
   corrompue (non-finie, ticks ≤ 0, valeur de tick ≤ 0) → `REJECTED / INVALID_INPUT`.
   **ZÉRO exception** : la fonction rend toujours un `SizerResult`, jamais elle ne lève — le
   chemin d'échec est une donnée, pas un crash.

**F1 STRUCTUREL** : le modèle Apex « Intraday Trail » (seuil qui suit le pic d'équité en temps
réel, non-réalisé inclus) est INCOMPATIBLE avec LSR — ici il est non-représentable par
construction : `account_type` n'admet que les modèles EOD. Le `drawdown_floor` est STATIQUE en
intraday (EOD Trail : le seuil ne se recalcule qu'à la clôture — ce recalcul est le travail du
driver de fin de session, hors de cette couche).

Fonctions PURES et déterministes : compte + géométrie en entrée, résultat en sortie — aucune
horloge lue, aucun état retenu, aucun ordre passé (§2.1). Les montants du preset `APEX_EOD_50K`
sont des ordres de grandeur publics **À VÉRIFIER le jour de l'achat** (doc LSR ; depuis mars 2026
Apex ne propose plus de reset — un breach impose le rachat d'une évaluation : F8 a une valeur
monétaire directe).
"""
from __future__ import annotations

import math
from typing import Any, Literal, Optional

from pydantic import BaseModel

from . import config

# Spécifications contractuelles CME (constantes d'échange, non calibrables).
INSTRUMENT_SPECS: dict[str, dict[str, float]] = {
    "MES": {"tick_size": 0.25, "tick_value": 1.25},
    "MNQ": {"tick_size": 0.25, "tick_value": 0.5},
}


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class AccountState(BaseModel):
    """État STATELESS du compte au moment de l'évaluation — fourni par le driver, jamais lu ici.
    Seuls les modèles EOD sont représentables (F1 structurel) : `drawdown_floor` est donc
    STATIQUE en intraday, et `daily_loss_limit` pause la journée sans tuer le compte."""
    account_type: Literal["EOD_TRAILING", "EOD_STATIC"] = "EOD_TRAILING"
    current_equity: float
    day_start_equity: float
    drawdown_floor: float
    daily_loss_limit: float


class SizerResult(BaseModel):
    """Sortie du RiskSizer — toujours rendue, jamais levée. `contracts` n'existe QUE sur
    APPROVED (jamais un 0 déguisé en taille, §3)."""
    status: Literal["APPROVED", "REJECTED"]
    reason: str = ""
    contracts: Optional[int] = None
    buffer: Optional[float] = None
    risk_allowed: Optional[float] = None


class ApexEodPreset(BaseModel):
    """Montants publics, sujets à changement — À VÉRIFIER sur le site Apex le jour de l'achat."""
    label: str
    initial_capital: float
    max_drawdown: float
    daily_loss_limit: float
    profit_target: float


APEX_EOD_50K = ApexEodPreset(label="Apex EOD Trail 50K (À VÉRIFIER)", initial_capital=50_000.0,
                             max_drawdown=2_500.0, daily_loss_limit=1_000.0,
                             profit_target=3_000.0)


def apex_eod_account(preset: ApexEodPreset, current_equity: Optional[float] = None,
                     day_start_equity: Optional[float] = None) -> AccountState:
    """Construit l'état d'un compte Apex EOD depuis un preset. Défauts : compte neuf."""
    equity = current_equity if current_equity is not None else preset.initial_capital
    day_start = day_start_equity if day_start_equity is not None else equity
    return AccountState(account_type="EOD_TRAILING", current_equity=equity,
                        day_start_equity=day_start,
                        drawdown_floor=preset.initial_capital - preset.max_drawdown,
                        daily_loss_limit=preset.daily_loss_limit)


def compute_buffer(account: AccountState) -> float:
    """La distance vers la mort : la plus PROCHE des deux frontières (plancher de campagne,
    limite de perte du jour). Peut être négative (breach) — l'appelant tranche via F8."""
    to_floor = account.current_equity - account.drawdown_floor
    to_dll = account.current_equity - (account.day_start_equity - account.daily_loss_limit)
    return min(to_floor, to_dll)


def size_position(account: AccountState, stop_distance_ticks: Any, tick_value: Any,
                  buffer_divisor: int = config.RISK_BUFFER_DIVISOR) -> SizerResult:
    """Dimensionne le prochain trade — règle du 1/5e sur le buffer, floor strict, F8 fail-closed.
    Rend TOUJOURS un `SizerResult` (zéro exception) : entrée corrompue → `INVALID_INPUT` ;
    buffer ≤ 0 ou taille < 1 → `INSUFFICIENT_BUFFER`."""
    if not all(_finite(v) for v in (account.current_equity, account.day_start_equity,
                                    account.drawdown_floor, account.daily_loss_limit)):
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    # Grandeurs de compte NULLES/NÉGATIVES = corruption de flux, pas une frontière de risque :
    # aucun compte prop réel ne porte ça. Piège précis : un floor NÉGATIF (corrompu) ÉLARGIRAIT
    # le buffer (to_floor = equity − (−500) = 50 500…) — la corruption deviendrait du levier.
    if account.current_equity <= 0 or account.day_start_equity <= 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    if account.daily_loss_limit <= 0 or account.drawdown_floor < 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    if not _finite(stop_distance_ticks) or stop_distance_ticks <= 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    if not _finite(tick_value) or tick_value <= 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    if not isinstance(buffer_divisor, int) or isinstance(buffer_divisor, bool) or buffer_divisor <= 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")

    buffer = compute_buffer(account)
    if buffer <= 0:
        return SizerResult(status="REJECTED", reason="INSUFFICIENT_BUFFER",
                           buffer=buffer, risk_allowed=None)
    risk_allowed = buffer / buffer_divisor
    risk_per_contract = float(stop_distance_ticks) * float(tick_value)
    contracts = math.floor(risk_allowed / risk_per_contract)
    if contracts < 1:
        return SizerResult(status="REJECTED", reason="INSUFFICIENT_BUFFER",
                           buffer=buffer, risk_allowed=risk_allowed)
    # Plafond de PLAUSIBILITÉ (v1 provisional) : une équité corrompue (1e308…) produit un buffer
    # fini, un risque fini, et un floor() astronomique — un ticket à 10^306 contrats serait
    # parfaitement COHÉRENT pour la garde D-045 (elle vérifie l'ordre des niveaux, pas la
    # vraisemblance d'une taille). Au-delà du plafond, la taille n'est pas un signal (§3).
    if contracts > config.RISK_MAX_CONTRACTS:
        return SizerResult(status="REJECTED", reason="SIZE_SANITY_CAP",
                           buffer=buffer, risk_allowed=risk_allowed)
    return SizerResult(status="APPROVED", contracts=contracts,
                       buffer=buffer, risk_allowed=risk_allowed)
