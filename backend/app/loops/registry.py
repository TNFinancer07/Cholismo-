"""Les cinq boucles du terminal — DÉCLARÉES (D-073).

Ce fichier ne câble rien : il déclare. Un superviseur monté sur ce registre seul rapporte
`NOT_IMPLEMENTED` sur les cinq lignes, ce qui est **la vérité** à ce stade du build (les corps
de L2/L3/L4 arrivent avec le Pont Options ; L1/L5 existent déjà sous une autre forme et seront
migrées sans mélanger refactor et feature — Loop 3).

Déclarer avant de câbler n'est pas un stub : le critère retenu est « un lecteur peut-il
confondre ceci avec du code de production validé ? ». Ici la réponse est non — le statut le dit
en toutes lettres, et `all_healthy` reste `false`.

| Boucle | Cadence | Criticité | Disette | Source de la valeur |
|---|---|---|---|---|
| `core.tick` | 0,25 s | HOT | FAIL_CLOSED | `config.FAST_TICK_SECONDS` (existant) |
| `options.sync` | 5 s | WARM | DEGRADE | `options_worker.py` |
| `o5.kurtosis` | 60 s | COLD | FAIL_CLOSED | barres ES 1 min (`o5TailRisk.ts`) |
| `gates.eval` | événementiel | WARM | FAIL_CLOSED | armement (`decisionLog.ts`) |
| `ui.broadcast` | 0,25 s | WARM | HOLD_LAST | cadence SSE existante |

**Trois décisions structurantes portées par ce registre :**

1. **`gates.eval` est ÉVÉNEMENTIELLE.** Elle se déclenche sur détection de setup par
   `evaluateLsr()`, jamais sur une horloge. Une L4 périodique réévaluerait le PASSÉ — c'est
   exactement le piège de cadence corrigé en D-052. Conséquence assumée : son silence n'est
   pas une panne (un matin sans setup est un matin normal), donc elle n'a pas de seuil de
   péremption et ne peut pas passer `STALLED`.
2. **`o5.kurtosis` est COLD et hors du fil principal.** Le calcul des moments d'ordre 4 sur
   120 rendements est du CPU synchrone : exécuté dans la boucle, il gèle `core.tick` avant tout
   point d'attente (piège Python nommé en tête de `RUNTIME_LOOPS.md`). Son tick devra déporter
   le calcul (`asyncio.to_thread`) — le budget ci-dessous borne l'attente, il ne rend pas le
   calcul non bloquant.
3. **`options.sync` DÉGRADE, elle ne bloque pas.** Le Pont Options est consultatif (mode G2) :
   un fournisseur muet doit ramener le poids options à zéro et marquer le signal dégradé,
   jamais empêcher un trade que les 30 contrôles déterministes ont autorisé. C'est la même
   doctrine que le poids Macro non calibré (`CLAUDE §8`).
"""
from __future__ import annotations

from .. import config
from .contract import Cadence, Criticality, LoopSpec, StarvePolicy

CORE_TICK = LoopSpec(
    name="core.tick",
    cadence=Cadence.PERIODIC,
    period_s=config.FAST_TICK_SECONDS,
    criticality=Criticality.HOT,
    tick_budget_s=config.HOT_PATH_BUDGET_SECONDS,
    heartbeat_stale_s=config.ENGINE_HEARTBEAT_MAX_AGE,
    starve=StarvePolicy.FAIL_CLOSED,
    purpose="Ticks ES, carnet MBO, fenêtres d'order flow, détection de sweep LSR.",
)

OPTIONS_SYNC = LoopSpec(
    name="options.sync",
    cadence=Cadence.PERIODIC,
    period_s=config.OPTIONS_SYNC_PERIOD_SECONDS,
    criticality=Criticality.WARM,
    tick_budget_s=config.OPTIONS_VENDOR_TIMEOUT_SECONDS,
    heartbeat_stale_s=config.OPTIONS_CONTEXT_TTL_SECONDS,
    starve=StarvePolicy.DEGRADE,
    purpose="Consomme le contexte options publié dans Redis par options_worker.py "
            "(GEX local, murs, gamma zero, Net Premium Drift).",
)

O5_KURTOSIS = LoopSpec(
    name="o5.kurtosis",
    cadence=Cadence.PERIODIC,
    # Cadence d'ÉCHANTILLONNAGE, PAS la largeur de barre (D-077) : cadencée à 60 s, la boucle
    # verrait chaque bucket une seule fois et la moindre gigue sauterait une minute — fabriquant
    # un `O5_DATA_GAP` qui ne dit rien du marché et tout de notre ordonnanceur.
    period_s=config.O5_SAMPLE_PERIOD_SECONDS,
    criticality=Criticality.COLD,
    tick_budget_s=config.O5_TICK_BUDGET_SECONDS,
    heartbeat_stale_s=config.O5_HEARTBEAT_STALE_SECONDS,
    starve=StarvePolicy.FAIL_CLOSED,
    purpose="Échantillonne le dernier print ES, clôt une barre par minute, et recalcule "
            "l'excess kurtosis À LA CLÔTURE — calcul déporté hors du fil principal (O5).",
)

GATES_EVAL = LoopSpec(
    name="gates.eval",
    cadence=Cadence.EVENT_DRIVEN,
    period_s=None,
    criticality=Criticality.WARM,
    tick_budget_s=config.GATES_TICK_BUDGET_SECONDS,
    heartbeat_stale_s=None,
    starve=StarvePolicy.FAIL_CLOSED,
    purpose="Évalue O1-O5 sur armement (mode G2 : journalise, ne bloque jamais) et écrit "
            "l'entrée de journal.",
)

UI_BROADCAST = LoopSpec(
    name="ui.broadcast",
    cadence=Cadence.PERIODIC,
    period_s=config.FAST_TICK_SECONDS,
    criticality=Criticality.WARM,
    tick_budget_s=config.UI_BROADCAST_BUDGET_SECONDS,
    heartbeat_stale_s=config.ENGINE_HEARTBEAT_MAX_AGE,
    starve=StarvePolicy.HOLD_LAST,
    purpose="Diffusion SSE segmentée par cadence — canaux rapide, lent, et options.",
)


def default_specs() -> tuple[LoopSpec, ...]:
    """Les cinq boucles, dans l'ordre du flux : donnée → calcul → évaluation → diffusion."""
    return (CORE_TICK, OPTIONS_SYNC, O5_KURTOSIS, GATES_EVAL, UI_BROADCAST)
