"""Règles de protection LSR F6 / F7 / A5b — et l'état d'exécution, en PROJECTION (D-094).

Ce sont les règles qui empêchent de *mal* trader : verrou après deux pertes (F6), fenêtre
anti-FOMO (F7), confluence renforcée au premier trade de séance (A5b). Leur absence est
silencieuse — rien ne casse, on trade juste plus mal — ce qui les rend coûteuses à omettre.

---

**Pourquoi une projection, et pas un champ.**

`lsr-engine/src/types.ts` définit `LsrRuntimeState` et le fait circuler : chaque évaluation rend
un `nextState` que l'appelant doit reporter. C'est légitime en TypeScript, où le moteur est une
fonction pure appelée en boucle.

Ici ce serait une **faute**. `CLAUDE §2.5` : la décision est un event immuable, l'issue est un
event ultérieur qui la référence, et « l'état courant » est une **projection**. Un
`consecutive_losses` stocké quelque part serait une seconde vérité, qui dériverait de la première
au premier redémarrage, au premier import de réconciliation, au premier event rejoué. On ne le
stocke donc nulle part : on le **recalcule** depuis le journal, à chaque évaluation.

Le coût est réel (relire les events à chaque appel) et assumé : ces règles ne sont pas dans le
hot path sous-seconde, elles s'évaluent à l'armement d'un setup.

**Unités.** Millisecondes, comme le TS, pour que le verrou de parité compare des nombres
comparables. Le journal, lui, horodate en secondes — la conversion vit ici et nulle part ailleurs.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import config
from .event_store import EventStore

#: Journée de séance = journée civile de l'opérateur. Convention déjà en place (`recap.py`,
#: `live_mode.py`) ; en réintroduire une seconde ferait diverger deux définitions de « aujourd'hui ».
MTL = ZoneInfo("America/Montreal")

#: Motifs de refus — mêmes chaînes que `RejectReason` du TS, verrouillées par le test de parité.
F6_COOLDOWN_ACTIVE = "F6_COOLDOWN_ACTIVE"
F7_FOMO_TIMEOUT = "F7_FOMO_TIMEOUT"
F7_RESUBMIT_LOCKOUT = "F7_RESUBMIT_LOCKOUT"
A5B_FIRST_TRADE_CONFLUENCE = "A5B_FIRST_TRADE_CONFLUENCE"

_ENGINE_DIR = pathlib.Path(__file__).resolve().parents[2] / "lsr-engine" / "src"


def ts_engine_source(name: str) -> str:
    """Source TS du moteur LSR v1.2, lue depuis `lsr-engine/src/`.

    Distincte de `options_gates.ts_reference_source`, qui lit le Fast Engine v1.7 dans
    `/reference/v2/fast-engine/` : deux paquets, deux autorités. Les confondre ferait vérifier la
    parité contre le mauvais fichier — un verrou qui ne mord pas.
    """
    path = _ENGINE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"source TS du moteur LSR introuvable : {path}")
    return path.read_text(encoding="utf-8")


def session_date(now_ms: float) -> str:
    """`AAAA-MM-JJ` dans le fuseau de l'opérateur."""
    return datetime.fromtimestamp(now_ms / 1000.0, tz=MTL).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class LsrRuntimeState:
    """Photo de l'état d'exécution à un instant, dérivée du journal. **Immuable** : on n'en
    modifie pas un champ, on en reprojette une autre.

    `campaign_stop_until` (F8) est ABSENT de cette structure, délibérément : F8 dépend des
    `AccountFrontiers` (drawdown de campagne), qui ne sont pas dans le journal des décisions. Un
    champ toujours à `None` se lirait « campagne saine » alors qu'il signifierait « non mesuré » —
    c'est exactement la confusion que `CLAUDE §3` interdit. Il apparaîtra quand F8 sera porté.
    """

    session_date: str
    consecutive_losses: int
    trades_today: int
    lockout_until_ms: Optional[float]
    #: Vide et documenté : voir `rejected_setup_ids` plus bas. Ce n'est pas « aucun refus », c'est
    #: « aucun refus n'est ENREGISTRÉ ». Le drapeau dit lequel des deux.
    rejected_setup_ids: tuple[str, ...] = ()
    resubmit_tracking_available: bool = False


def _ts_ms(event: dict[str, Any]) -> Optional[float]:
    ts = event.get("ts")
    try:
        return float(ts) * 1000.0 if ts is not None else None
    except (TypeError, ValueError):
        return None


def project_runtime_state(store: EventStore, *, now_ms: float) -> LsrRuntimeState:
    """Reprojette l'état d'exécution depuis le journal append-only.

    `consecutive_losses` est compté **dans la séance courante uniquement**. Une série de pertes
    d'hier ne verrouille pas ce matin : F6 protège d'un enchaînement à chaud, pas d'une mauvaise
    semaine — c'est F8 (campagne) qui porte l'horizon long, et il n'est pas encore porté.
    """
    today = session_date(now_ms)

    decisions = {d["id"]: d for d in store.events("DecisionEvent")}
    trades_today = sum(
        1 for d in decisions.values()
        if d.get("decision") == "GO"
        and (ms := _ts_ms(d)) is not None and session_date(ms) == today)

    # Série de pertes : on remonte les issues de la séance, de la plus récente à la plus ancienne,
    # et on s'arrête à la première non-perte. Une issue dont la décision est inconnue est ignorée
    # plutôt que comptée — un orphelin ne doit ni verrouiller ni déverrouiller.
    streak = 0
    last_loss_ms: Optional[float] = None
    for outcome in reversed(store.events("OutcomeEvent")):
        ms = _ts_ms(outcome)
        if ms is None or session_date(ms) != today:
            continue
        if outcome.get("decision_id") not in decisions:
            continue
        if outcome.get("outcome") != "LOSS":
            break
        streak += 1
        if last_loss_ms is None:
            last_loss_ms = ms

    lockout_until_ms = None
    if streak >= config.LSR_F6_CONSECUTIVE_LOSS_TRIGGER and last_loss_ms is not None:
        lockout_until_ms = last_loss_ms + config.LSR_F6_COOLDOWN_MS

    return LsrRuntimeState(
        session_date=today,
        consecutive_losses=streak,
        trades_today=trades_today,
        lockout_until_ms=lockout_until_ms,
        # F7-resubmit : AUCUN event du journal n'enregistre le refus d'un setup identifié.
        # `DecisionEvent` porte un `window_id`, pas un `setup_id`, et le journal des setups ne
        # connaît que `setup_armed` / `setup_outcome`. Rendre un tuple vide en le présentant comme
        # « rien n'a été refusé » serait un faux — d'où le drapeau explicite.
        rejected_setup_ids=(),
        resubmit_tracking_available=False,
    )


# --------------------------------------------------------------------------------------------
# Les règles. Chacune rend un motif de refus ou `None` — jamais un booléen : « refusé » sans le
# motif n'est pas actionnable pour l'opérateur, et le journal en a besoin.
# --------------------------------------------------------------------------------------------

def f6_cooldown(state: LsrRuntimeState, now_ms: float) -> Optional[str]:
    """Verrou après `LSR_F6_CONSECUTIVE_LOSS_TRIGGER` pertes consécutives."""
    if state.lockout_until_ms is not None and now_ms < state.lockout_until_ms:
        return F6_COOLDOWN_ACTIVE
    return None


def f7_fomo(sweep_ts_ms: Optional[float], now_ms: float) -> Optional[str]:
    """Un sweep trop vieux n'est plus un setup, c'est une course après le prix.

    Sans horodatage de sweep, on **refuse** (fail-closed §3) : ne pas savoir depuis quand le
    setup existe n'est pas la même chose que savoir qu'il est frais.
    """
    if sweep_ts_ms is None:
        return F7_FOMO_TIMEOUT
    if now_ms - sweep_ts_ms > config.LSR_F7_FOMO_WINDOW_MS:
        return F7_FOMO_TIMEOUT
    return None


def f7_resubmit(setup_id: Optional[str], state: LsrRuntimeState) -> Optional[str]:
    """Re-soumission d'un setup déjà refusé.

    **Inerte tant que `resubmit_tracking_available` est faux**, et c'est délibéré : la règle n'a
    pas de source d'events. La brancher sur une liste toujours vide donnerait une gate qui passe
    toujours — un feu vert décoratif, indiscernable d'une règle qui fonctionne. Elle refusera le
    jour où un event de refus existera, pas avant.
    """
    if not state.resubmit_tracking_available:
        return None
    if setup_id is not None and setup_id in state.rejected_setup_ids:
        return F7_RESUBMIT_LOCKOUT
    return None


def has_confluence(coincides_with_vpoc: Any, secondary_reference: Any) -> bool:
    """Confluence au sens du TS : VPOC **et** une référence secondaire nommée."""
    return bool(coincides_with_vpoc) and secondary_reference not in (None, "", "NONE")


def a5b_first_trade_confluence(state: LsrRuntimeState, *, coincides_with_vpoc: Any,
                               secondary_reference: Any) -> Optional[str]:
    """Premier trade de la séance : confluence renforcée obligatoire.

    La règle ne mord qu'à `trades_today == 0`. C'est le trade où l'on a le moins d'information sur
    la séance et le plus d'envie d'en prendre un.
    """
    if state.trades_today == 0 and not has_confluence(coincides_with_vpoc, secondary_reference):
        return A5B_FIRST_TRADE_CONFLUENCE
    return None
