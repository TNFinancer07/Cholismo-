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

3. **F8 coupe-circuit — trois raisons de rejet, ZÉRO exception** (la fonction rend toujours un
   `SizerResult`, jamais elle ne lève — le chemin d'échec est une donnée, pas un crash) :
   - `INSUFFICIENT_BUFFER` : taille < 1 OU buffer ≤ 0 — jamais un « ordre de 0 contrat » ;
   - `INVALID_INPUT` : entrée corrompue — non-finie, ticks ≤ 0, valeur de tick ≤ 0, grandeurs de
     compte nulles/négatives (un floor NÉGATIF élargirait le buffer : la corruption deviendrait
     du levier, trouvé au /devil) ;
   - `SIZE_SANITY_CAP` : taille > `RISK_MAX_CONTRACTS` (plafond de plausibilité v1 provisional —
     une équité corrompue mais finie produit un `floor()` astronomique parfaitement cohérent
     pour la garde D-045, qui vérifie l'ordre des niveaux, pas la vraisemblance d'une taille).
   `contracts` n'existe QUE sur APPROVED (invariant balayé en test : APPROVED ⟺ contrats ≥ 1).

**F1 STRUCTUREL** : le modèle Apex « Intraday Trail » (seuil qui suit le pic d'équité en temps
réel, non-réalisé inclus) est INCOMPATIBLE avec LSR — ici il est non-représentable par
construction : `account_type` n'admet que les modèles EOD. Le `drawdown_floor` est STATIQUE en
intraday (EOD Trail : le seuil ne se recalcule qu'à la clôture — ce recalcul est le travail du
driver de fin de session, hors de cette couche).

**Couture avec le pipeline LSR (T2)** : `size_plan(plan, account)` dérive le stop en ticks de la
GÉOMÉTRIE du plan D-046 (`|entrée − stop| / tick_size`, une seule source de vérité) et rend un
NOUVEAU plan aux contrats remplacés — l'engine ne l'appelle qu'avec un compte FRAIS fourni par
`account_provider.py` (sans compte : aucune émission).

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
    # REQUIS, sans défaut (D-068) : le plafond « 1 % du capital » du moteur de référence ne peut
    # pas se calculer sans lui. Le rendre optionnel laisserait construire un compte dont le
    # sizer retomberait EN SILENCE sur `buffer / 5` — exactement la divergence qu'on corrige.
    initial_capital: float
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
    return AccountState(account_type="EOD_TRAILING", initial_capital=preset.initial_capital,
                        current_equity=equity, day_start_equity=day_start,
                        drawdown_floor=preset.initial_capital - preset.max_drawdown,
                        daily_loss_limit=preset.daily_loss_limit)


def compute_buffer(account: AccountState) -> float:
    """La distance vers la mort : la plus PROCHE des deux frontières (plancher de campagne,
    limite de perte du jour). Peut être négative (breach) — l'appelant tranche via F8."""
    to_floor = account.current_equity - account.drawdown_floor
    to_dll = account.current_equity - (account.day_start_equity - account.daily_loss_limit)
    return min(to_floor, to_dll)


def account_view(account: Optional[AccountState],
                 reference_stop_ticks: int = None,          # type: ignore[assignment]
                 instrument: str = None) -> dict:           # type: ignore[assignment]
    """Projection d'AFFICHAGE de l'état de compte (Zone C HUD, D-051) — PURE, aucune horloge.

    Porte de quoi rendre la « distance vers la mort » lisible d'un coup d'œil :
    - `buffer` courant ET **`buffer_initial`** = le buffer À L'OUVERTURE du jour
      (`min(day_start − floor, DLL)`) — dénominateur HONNÊTE et SANS ÉTAT de la jauge : ni une
      constante (fausse dès le 2e jour), ni le buffer courant (qui donnerait toujours 100 %) ;
    - `day_pnl` = equity − day_start ;
    - `next_ticket` : la taille que porterait le PROCHAIN ticket sur un stop de RÉFÉRENCE
      (3 ticks MES par défaut) — affichage préventif, l'opérateur voit sa capacité avant l'alerte ;
    - `status` : celui du RiskSizer (APPROVED / INSUFFICIENT_BUFFER / INVALID_INPUT /
      SIZE_SANITY_CAP) ou **DISCONNECTED** si aucun compte.

    FAIL-CLOSED (§3) : `account is None` → tout à `None`, `status=DISCONNECTED`, `is_stale=True`.
    Le port D-047 rend `None` pour PÉRIMÉ **et** pour DÉCONNECTÉ : on n'invente pas une
    distinction que le contrat ne porte pas — un seul état honnête, « pas de vue exploitable ».
    Une grandeur non finie n'est JAMAIS affichée (None), même si le reste de l'état est lisible."""
    ticks = (reference_stop_ticks if reference_stop_ticks is not None
             else config.RISK_REFERENCE_STOP_TICKS)
    inst = instrument if instrument is not None else config.LSR_INSTRUMENT
    spec = INSTRUMENT_SPECS.get(inst)
    empty = {k: None for k in ("current_equity", "day_start_equity", "drawdown_floor",
                               "daily_loss_limit", "buffer", "buffer_initial", "day_pnl")}
    if account is None or spec is None:
        return {**empty, "status": "DISCONNECTED", "is_stale": True,
                "next_ticket": {"instrument": inst, "stop_ticks": ticks, "contracts": None,
                                "risk_allowed": None, "status": "DISCONNECTED"}}

    result = size_position(account, stop_distance_ticks=ticks, tick_value=spec["tick_value"])
    fields = {k: (float(v) if _finite(v) else None) for k, v in (
        ("current_equity", account.current_equity),
        ("day_start_equity", account.day_start_equity),
        ("drawdown_floor", account.drawdown_floor),
        ("daily_loss_limit", account.daily_loss_limit))}
    buffer_now = compute_buffer(account) if all(v is not None for v in fields.values()) else None
    # buffer à l'OUVERTURE : le même calcul, l'équité prise au day_start (jour à sa naissance)
    buffer_open = (min(account.day_start_equity - account.drawdown_floor,
                       account.daily_loss_limit)
                   if all(v is not None for v in fields.values()) else None)
    day_pnl = (account.current_equity - account.day_start_equity
               if fields["current_equity"] is not None and fields["day_start_equity"] is not None
               else None)
    return {
        **fields,
        "buffer": buffer_now if _finite(buffer_now) else None,
        "buffer_initial": buffer_open if _finite(buffer_open) else None,
        "day_pnl": day_pnl if _finite(day_pnl) else None,
        "is_stale": False,
        "status": result.status if result.status == "APPROVED" else result.reason,
        "next_ticket": {"instrument": inst, "stop_ticks": ticks, "contracts": result.contracts,
                        "risk_allowed": result.risk_allowed,
                        "status": result.status if result.status == "APPROVED" else result.reason},
    }


def size_plan(plan: Any, account: AccountState) -> Optional[dict]:
    """Dimensionne un plan LSR APPROVED (contrat D-045/046) via la règle du 1/5e — le stop en
    ticks est dérivé de la GÉOMÉTRIE du plan (`|entrée − stop| / tick_size`), jamais fourni à
    part (une seule source de vérité). Rend un NOUVEAU plan aux contrats remplacés (l'entrée
    n'est jamais mutée), ou None : sizer en rejet (F8/corruption), instrument hors
    `INSTRUMENT_SPECS`, plan malformé — silence, jamais un ticket dégradé (§3)."""
    if not isinstance(plan, dict):
        return None
    spec = INSTRUMENT_SPECS.get(plan.get("instrument"))  # type: ignore[arg-type]
    ex = plan.get("executionPlan")
    if spec is None or not isinstance(ex, dict):
        return None
    entry, stop = ex.get("entryPrice"), ex.get("stopLoss")
    if not (_finite(entry) and _finite(stop)):
        return None
    stop_ticks = abs(entry - stop) / spec["tick_size"]
    result = size_position(account, stop_distance_ticks=stop_ticks,
                           tick_value=spec["tick_value"])
    if result.status != "APPROVED":
        return None
    return {**plan, "executionPlan": {**ex, "contracts": result.contracts}}


def size_position(account: AccountState, stop_distance_ticks: Any, tick_value: Any,
                  buffer_divisor: int = config.RISK_BUFFER_DIVISOR) -> SizerResult:
    """Dimensionne le prochain trade — règle du 1/5e sur le buffer, floor strict, F8 fail-closed.
    Rend TOUJOURS un `SizerResult` (zéro exception) : entrée corrompue → `INVALID_INPUT` ;
    buffer ≤ 0 ou taille < 1 → `INSUFFICIENT_BUFFER`."""
    if not all(_finite(v) for v in (account.initial_capital, account.current_equity,
                                    account.day_start_equity, account.drawdown_floor,
                                    account.daily_loss_limit)):
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    # Grandeurs de compte NULLES/NÉGATIVES = corruption de flux, pas une frontière de risque :
    # aucun compte prop réel ne porte ça. Piège précis : un floor NÉGATIF (corrompu) ÉLARGIRAIT
    # le buffer (to_floor = equity − (−500) = 50 500…) — la corruption deviendrait du levier.
    if account.current_equity <= 0 or account.day_start_equity <= 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    if account.daily_loss_limit <= 0 or account.drawdown_floor < 0:
        return SizerResult(status="REJECTED", reason="INVALID_INPUT")
    # Un capital nul ou négatif ferait un plafond nul ou NÉGATIF : le `min()` traverserait alors
    # le floor et la corruption deviendrait un refus systématique — ou du levier à l'envers.
    if account.initial_capital <= 0:
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
    # Formule EXACTE du moteur de référence (`risksizer.ts`) : `min(0.01 × capital, buffer / 5)`.
    # Les deux termes sont des frontières distinctes — le buffer protège du breach, le plafond
    # protège d'un sizing qui grossit avec le compte. Le plus SERRÉ des deux gagne (D-068).
    risk_allowed = min(config.RISK_FRACTION_OF_CAPITAL * account.initial_capital,
                       buffer / buffer_divisor)
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
