"""L2 `options.sync` — consommateur du contexte options (D-075).

`workers/options_worker.py` est un service **AUTONOME** : sa propre docstring pose le
découplage total (« un redémarrage ou une panne du serveur qui sert le terminal ne doit jamais
affecter ce worker, et inversement »). Ce module ne le pilote donc pas — il **consomme** ce
qu'il publie dans `options:context:latest`.

**Port Python d'`optionsContext.ts`**, verrou de parité compris (doctrine D-072 : un test LIT
le TypeScript et échoue si les deux côtés divergent — voir `tests/test_options_context.py`).

**La règle de conception non négociable, reprise telle quelle.** Le fichier TS la justifie par
la mesure : une lecture locale coûte ~0,02 µs, le moindre saut asynchrone ~130× plus, un
aller-retour Redis un ou deux ordres de grandeur au-delà. **Au moment de la décision on lit une
variable en mémoire, jamais le réseau.** `snapshot()` est donc synchrone, pure sur `now`, et ne
peut pas bloquer par construction. Le rafraîchissement vit dans la boucle L2, hors du chemin de
décision.

**Une divergence ASSUMÉE avec le TS** — un `computedAt` daté du FUTUR. Le TS calcule
`age = now − computedAt`, obtient un négatif, le compare à un seuil positif, et conclut `OK` :
fail-OPEN sur une désync d'horloge. Ce dépôt a déjà payé cette leçon (D-050/D-048) et refuse
une donnée du futur. L'âge négatif reste **visible** dans la projection — on ne maquille pas la
désync, on refuse seulement de la traiter comme de la fraîcheur.

**Pourquoi `refresh()` LÈVE au lieu de renvoyer un booléen.** Un rafraîchissement silencieux
ferait battre L2 : le superviseur l'afficherait `RUNNING` alors qu'aucune donnée n'arrive —
précisément le mensonge que D-073 existe pour empêcher. Un échec doit être compté par la
boucle ; après `OPTIONS_CONTEXT_TTL_SECONDS` sans succès, L2 passe `STALLED` et ça se voit.
Le cache, lui, n'est **jamais** corrompu par une lecture ratée : la dernière valeur bonne reste
et vieillit naturellement vers `STALE`.

Ce module ne DÉCIDE rien (§2.1) : il expose un contexte que les gates O1-O4 liront en mode
consultatif (G2). Sa politique de disette est `DEGRADE` — un fournisseur muet ramène le poids
options à zéro, il n'empêche jamais un trade que les contrôles déterministes ont autorisé.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from . import config

log = logging.getLogger("cholismo.options_context")

#: Verrouillés par test contre `optionsContext.ts` ET `workers/options_worker.py` : une clé qui
#: diverge ne casse aucun test unitaire, elle produit juste un terminal éternellement
#: `UNAVAILABLE` face à un worker qui publie correctement.
OPTIONS_CONTEXT_KEY = "options:context:latest"
OPTIONS_UPDATE_CHANNEL = "options:context:updated"


class ContextHealth(str, Enum):
    """Miroir exact de `SnapshotHealth` (optionsContext.ts)."""
    OK = "OK"
    STALE = "STALE"
    VENDOR_DOWN = "VENDOR_DOWN"
    UNAVAILABLE = "UNAVAILABLE"


class OptionsContextUnavailable(Exception):
    """Échec de rafraîchissement. `reason` distingue les causes, parce qu'elles n'appellent pas
    la même intervention : `redis_error` (infra), `key_missing` (worker pas démarré),
    `malformed` (worker qui publie du bruit)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}{': ' + detail if detail else ''}")
        self.reason = reason


@dataclass(frozen=True)
class OptionsContextSnapshot:
    health: ContextHealth
    raw: Optional[dict[str, Any]]
    age_s: Optional[float]


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class OptionsContextReader:
    """Lit `options:context:latest` en tâche de fond ; sert un instantané mémoire à la décision."""

    def __init__(self, redis: Any = None, *, url: Optional[str] = None,
                 clock: Optional[Callable[[], float]] = None,
                 stale_threshold_s: Optional[float] = None):
        if redis is None:
            import redis.asyncio as aioredis
            redis = aioredis.from_url(url or config.REDIS_URL, decode_responses=True)
        self._redis = redis
        self._clock = clock or time.time
        self._stale_s = (stale_threshold_s if stale_threshold_s is not None
                         else config.OPTIONS_CONTEXT_TTL_SECONDS)
        self._cache: Optional[dict[str, Any]] = None
        self._failing = False

    # -- le tick de L2 : la SEULE I/O de ce module --

    async def refresh(self) -> bool:
        """Un cycle de L2. Lève `OptionsContextUnavailable` si aucun contexte exploitable n'a pu
        être obtenu — c'est ce qui permet à la boucle de compter l'échec plutôt que de battre
        dans le vide."""
        try:
            raw = await self._redis.get(OPTIONS_CONTEXT_KEY)
        except Exception as exc:
            raise self._fail("redis_error", type(exc).__name__) from exc
        if raw is None:
            # Clé absente = worker pas démarré, ou TTL de 90 s expiré sans republication. Les
            # deux sont la même chose du point de vue du terminal : pas de contexte options.
            raise self._fail("key_missing")
        parsed = self._parse(raw)
        if parsed is None:
            raise self._fail("malformed")
        self._cache = parsed
        if self._failing:
            self._failing = False
            log.info("contexte options rétabli (source=%s)", parsed.get("sourceVendor", "?"))
        return True

    def _fail(self, reason: str, detail: str = "") -> OptionsContextUnavailable:
        """Journalise une fois par ÉPISODE, pas à chaque tick : à 5 s de cadence, une panne d'une
        heure produirait 720 lignes identiques et on apprendrait à les ignorer (hygiène D-046,
        même parade que la régression d'horloge du `lsr_driver`)."""
        if not self._failing:
            self._failing = True
            log.warning("contexte options indisponible (%s%s) — le dernier contexte connu "
                        "vieillit vers STALE, aucune valeur n'est inventée",
                        reason, f", {detail}" if detail else "")
        return OptionsContextUnavailable(reason, detail)

    def _parse(self, raw: str) -> Optional[dict[str, Any]]:
        """Un message malformé n'écrase JAMAIS le cache (comportement du TS, gardé tel quel)."""
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        # `computedAt` est la seule donnée dont TOUT dépend : sans elle, aucune fraîcheur n'est
        # calculable, donc aucune décision de santé honnête n'est possible.
        if "status" not in parsed or not _finite(parsed.get("computedAt")):
            return None
        return parsed

    # -- lecture de décision : SYNCHRONE, pure, zéro I/O --

    def snapshot(self, now: Optional[float] = None) -> OptionsContextSnapshot:
        """Ne fait aucun appel réseau et ne lève jamais. C'est ce qui la rend appelable depuis le
        chemin d'armement sans y introduire de latence (§7)."""
        now = self._clock() if now is None else now
        cache = self._cache
        if cache is None:
            return OptionsContextSnapshot(ContextHealth.UNAVAILABLE, None, None)
        age = now - (cache["computedAt"] / 1000.0)
        if cache.get("status") == "VENDOR_DOWN":
            # Donnée FRAÎCHE qui dit « je n'ai pas de donnée ». La confondre avec `OK` ferait
            # passer des murs absents pour des murs mesurés.
            return OptionsContextSnapshot(ContextHealth.VENDOR_DOWN, cache, age)
        # `age < 0` = horodatage du FUTUR → divergence assumée avec le TS (voir docstring).
        if age < 0 or age > self._stale_s:
            return OptionsContextSnapshot(ContextHealth.STALE, cache, age)
        return OptionsContextSnapshot(ContextHealth.OK, cache, age)

    # -- projection pour le canal SSE `options` --

    def to_event(self, now: Optional[float] = None) -> dict[str, Any]:
        """Ce qui part sur le canal. Aucune valeur n'est fabriquée : sans contexte, les niveaux
        sortent à `None` et la carte de GEX vide — jamais un 0 qui se lirait comme une mesure."""
        snap = self.snapshot(now)
        raw = snap.raw or {}
        drift = raw.get("netDriftCrossover") or {}
        return {
            "health": snap.health.value,
            "age_s": snap.age_s,
            "computed_at": raw.get("computedAt"),
            "source_vendor": raw.get("sourceVendor"),
            "gex_local_by_strike": raw.get("gexLocalByStrike") or {},
            "gamma_zero_es": raw.get("gammaZeroEs"),
            "put_wall_es": raw.get("putWallEs"),
            "call_wall_es": raw.get("callWallEs"),
            "conversion_factor_used": raw.get("conversionFactorUsed"),
            "net_drift": {
                "direction": drift.get("direction"),
                "ts": drift.get("ts"),
                # O4 reste `O4_SOURCE_UNCONFIRMED` tant que ce drapeau est faux : la source
                # Net Premium Drift n'est confirmée que sur QQQ, pas SPY/SPX. Prérequis externe
                # documenté (COMMANDS.md), pas un bug — donc rendu LISIBLE plutôt que masqué.
                "source_confirmed": bool(drift.get("sourceConfirmed", False)),
            },
            "stale_threshold_s": self._stale_s,
        }

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:
            log.exception("fermeture du client Redis du contexte options en échec")
