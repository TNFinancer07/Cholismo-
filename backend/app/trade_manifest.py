"""TradeManifest — contrat-pont entre le moteur LSR v1.2 et Cholismo (D-045).

Le moteur **Liquidity Sweep Reversion** est un moteur TypeScript AUTONOME, externe à ce dépôt :
`evaluateLsr()` applique Phase 0 (F1–F8), les gates order flow (B1–B4), la géométrie (A1/A2/A3)
puis le RiskSizer, et rend un plan. Ce module en **sérialise la sortie APPROUVÉE** dans un objet
stable — le `TradeManifest` — que le backend peut journaliser et que le frontend peut afficher.

**§2.1 — CE MODULE NE PASSE JAMAIS D'ORDRE.** Le manifeste est une **PROPOSITION** : la machine
compose le ticket, l'humain tranche (Go/No-Go). C'est l'unique divergence assumée d'avec le doc
d'intégration LSR, dont le driver d'exemple fait `broker.submit(plan.executionPlan)` : Cholismo,
en tant que driver, ne le fait pas et ne peut pas le faire. Aucune fonction ici n'ouvre de socket,
n'appelle de courtier ni ne déclenche d'exécution. « Semi-automatique » = automatique jusqu'au
ticket, manuel au déclenchement.

**Nommage camelCase — exception délibérée et bornée (§5).** Le ContextSchema est intégralement
snake_case (81 champs, miroir TS identique). Ce manifeste ne fait PAS partie du ContextSchema : il
naît côté TypeScript, dans le moteur LSR, et arrive tel quel au frontend. Le garder camelCase de
bout en bout supprime toute couche de traduction sur le seul contrat qui traverse les trois mondes
(moteur LSR → Python → UI). Le §5 reste respecté sur le fond : identifiants **en anglais**.

**Horloge INJECTÉE, jamais lue.** Comme le moteur LSR (« `now` et `state` sont injectés »), aucune
fonction ici ne lit l'heure système : la péremption est une comparaison déterministe, donc testable
et rejouable à l'identique.

FAIL-CLOSED (§3) — un ticket incohérent ne doit jamais atteindre l'écran :
- statut ≠ `APPROVED` → aucun manifeste (un plan rejeté par les gates n'est pas relayé) ;
- toute grandeur non finie, mal typée ou absente → aucun manifeste, jamais une valeur inventée ;
- taille de position non entière strictement positive → aucun manifeste ;
- **géométrie incohérente** (stop du mauvais côté de l'entrée, TP du mauvais côté, niveau collé à
  l'entrée) → aucun manifeste. Le moteur teste déjà ce cas ; la frontière le revérifie plutôt que
  de faire confiance à l'amont ;
- horloge non finie → traitée comme périmée (le doute ne rend jamais un ticket actionnable).

`v1 provisional` — la forme du plan LSR lue ici (`status`, `instrument`, `direction`,
`executionPlan.{entryType,entryPrice,stopLoss,takeProfit,contracts}`) est reconstituée depuis le doc
d'intégration LSR v1.2, le `types.ts` du moteur n'étant pas dans ce dépôt. À figer contre la source
dès qu'elle y entre : seul `_execution_fields()` changerait.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

DEFAULT_TTL_MS = 3000        # expiration automatique du signal — v1 provisional (cf. DECISIONS D-045)

# Le moteur raisonne en LONG/SHORT (géométrie) ; le manifeste parle BUY/SELL (ticket).
_DIRECTIONS = {"LONG": "BUY", "BUY": "BUY", "SHORT": "SELL", "SELL": "SELL"}
_NO_REASON = "LSR — motif non fourni par le moteur"


def _finite(x: Any) -> bool:
    """Nombre RÉEL et fini. `bool` exclu : `True` n'est pas un prix (§3)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _finite_float(x: Any) -> float:
    if not _finite(x):
        raise ValueError("valeur non finie")
    return float(x)


class EntryPlan(BaseModel):
    """Entrée du ticket. `price` = prix limite (LIMIT) ou prix de référence observé (MARKET)."""
    type: Literal["LIMIT", "MARKET"]
    price: float

    _finite_price = field_validator("price")(_finite_float)


class RiskPlan(BaseModel):
    """Bornes de risque. `positionSize` en contrats — strictement positif, sinon le ticket n'a
    pas de sens et ne doit pas exister (§3)."""
    stopLoss: float
    takeProfit: float
    positionSize: int = Field(gt=0)

    _finite_levels = field_validator("stopLoss", "takeProfit")(_finite_float)


class TradeManifest(BaseModel):
    """Proposition de trade validée par LSR — **enregistrée et affichée, jamais exécutée** (§2.1).

    `timestamp` et `timeToLiveMs` sont en millisecondes ; la péremption se calcule contre une
    horloge passée en argument (jamais lue), voir `is_expired`."""
    id: str
    timestamp: int
    instrument: str
    direction: Literal["BUY", "SELL"]
    reason: str
    entry: EntryPlan
    risk: RiskPlan
    timeToLiveMs: int = Field(default=DEFAULT_TTL_MS, gt=0)

    @property
    def expires_at_ms(self) -> int:
        return self.timestamp + self.timeToLiveMs

    def is_expired(self, now_ms: Any) -> bool:
        """Périmé dès que l'échéance est ATTEINTE (borne incluse). Horloge non finie → périmé :
        un doute sur l'heure ne laisse jamais un ticket actionnable (§3)."""
        if not _finite(now_ms):
            return True
        return now_ms >= self.expires_at_ms

    def remaining_ms(self, now_ms: Any) -> int:
        """Millisecondes restantes, bornées à 0 — jamais de compte à rebours négatif à l'écran."""
        if not _finite(now_ms):
            return 0
        return max(0, int(self.expires_at_ms - now_ms))


def _execution_fields(plan: dict) -> Optional[tuple[str, float, float, float, int]]:
    """Extrait `(entryType, entryPrice, stopLoss, takeProfit, contracts)` du plan LSR.

    Point de couture unique avec le moteur (`v1 provisional`, cf. docstring du module) : si sa
    forme évolue, seule cette fonction bouge. Tout champ absent, mal typé ou non fini → `None`."""
    ex = plan.get("executionPlan")
    if not isinstance(ex, dict):
        return None
    entry_type = ex.get("entryType")
    if entry_type not in ("LIMIT", "MARKET"):
        return None
    prices = [ex.get(k) for k in ("entryPrice", "stopLoss", "takeProfit")]
    if not all(_finite(p) for p in prices):
        return None
    contracts = ex.get("contracts")
    # `bool` est un `int` en Python — un `True` relayé ne doit pas devenir « 1 contrat » (§3).
    if not isinstance(contracts, int) or isinstance(contracts, bool) or contracts <= 0:
        return None
    entry, stop, target = (float(p) for p in prices)
    return entry_type, entry, stop, target, contracts


def _geometry_holds(direction: str, entry: float, stop: float, target: float) -> bool:
    """Le stop protège-t-il vraiment, le TP est-il vraiment devant ? Niveau collé à l'entrée =
    incohérent (stop à distance nulle, TP à gain nul). Revérifié ici même si le moteur le teste."""
    if direction == "BUY":
        return stop < entry < target
    return target < entry < stop


def manifest_from_lsr_plan(plan: Any, now_ms: Any,
                           ttl_ms: int = DEFAULT_TTL_MS) -> Optional[TradeManifest]:
    """Émetteur semi-automatique : sérialise un plan LSR **APPROUVÉ** en `TradeManifest`.

    Rend `None` — jamais un ticket dégradé — dès que quoi que ce soit cloche (voir les règles
    fail-closed en tête de module). Aucun ordre n'est passé (§2.1) : l'appelant journalise et
    affiche, l'humain tranche.

    L'`id` est le SHA-1 tronqué du contenu sérialisé : rejouer le même plan à la même
    milliseconde redonne le même identifiant (idempotence, utile face à un journal append-only),
    tandis qu'un contenu ou un instant différent en produit un autre."""
    if not isinstance(plan, dict) or not _finite(now_ms) or not isinstance(now_ms, int):
        return None
    if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or ttl_ms <= 0:
        return None
    if plan.get("status") != "APPROVED":
        return None                                  # rejeté par Phase 0 / les gates → non relayé

    direction = _DIRECTIONS.get(plan.get("direction"))  # type: ignore[arg-type]
    if direction is None:
        return None
    instrument = plan.get("instrument")
    if not isinstance(instrument, str) or not instrument:
        return None

    fields = _execution_fields(plan)
    if fields is None:
        return None
    entry_type, entry, stop, target, contracts = fields
    if not _geometry_holds(direction, entry, stop, target):
        return None

    reason = plan.get("reason")
    payload = {
        "timestamp": now_ms, "instrument": instrument, "direction": direction,
        "reason": reason if isinstance(reason, str) and reason else _NO_REASON,
        "entry": {"type": entry_type, "price": entry},
        "risk": {"stopLoss": stop, "takeProfit": target, "positionSize": contracts},
        "timeToLiveMs": ttl_ms,
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return TradeManifest(id=digest, **payload)
