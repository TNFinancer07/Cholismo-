"""Journal de trading (reference/journal/tradingjournal.html — D-022).

Grammar of the reference app, mapped onto the terminal's event-sourcing:
- a trade sheet is a DRAFT (Redis, freely editable/deletable) until the operator
  « Clôture & verrouille » — locking APPENDS an immutable `trade_locked` entry (SQLite,
  same RAISE(ABORT) guards as the Decision Log). No unlock, no edit after lock.
- pre/post-session sentiment lives in Redis and is frozen into the `session_closed` entry.
- aggregates (R cumulé, winrate, erreurs A/B/C, friction #2) are PROJECTIONS over locked
  entries. Lockout (2 pertes consécutives → pause 24 h, couche KillSwitch) is DERIVED,
  never stored.
- n8n webhooks: trade_closed / session_closed, async, logged — never in the hot path.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .event_store import EventStore

log = logging.getLogger("cholismo.journal")

STRATEGIES = {
    "SVS": {"label": "SVS v3.0 — Structural Vacuum Squeeze", "operator": "SONY",
            "seuil": 88, "accent": "sony"},
    "MEAN_REVERSION": {"label": "Mean Reversion — Piège d'Absorption v5.8", "operator": "SONY",
                       "seuil": 80, "accent": "sony"},
    "YOUSSEF_MACRO": {"label": "Macro Systématique — Youssef", "operator": "YOUSSEF",
                      "seuil": None, "accent": "youssef"},
}

EXIT_TYPES = ["SL technique", "SL temporel", "SL contextuel", "Règle CVD",
              "Cible / R atteint", "Break-even auto +1.5R", "Sortie précoce CVD"]
PALIERS = ["Aucun", "0.5R", "1R", "1.5R", "2R"]
ERREURS = ["A", "B", "C"]

# Sorties « précoces » à justifier — la friction #2 du document de référence.
EARLY_EXITS = {"Sortie précoce CVD", "SL temporel", "SL contextuel"}

DRAFT_FIELDS = {
    "direction", "trigger_price", "exit_price", "chop", "vix", "nq_es_corr",
    "score_global", "taille_finale_pct", "type_sortie", "palier_profit_atteint",
    "sortie_justifiee", "sl_distance_respectee", "resultat_r", "erreur_type",
    "conviction", "validation_n4", "etat_emotionnel", "these", "notes",
}


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def validate_lock(draft: dict[str, Any]) -> list[str]:
    """Minimal closure discipline: a locked sheet must be a usable lesson."""
    problems = []
    if draft.get("direction") not in ("LONG", "SHORT"):
        problems.append("direction manquante (LONG/SHORT)")
    if draft.get("type_sortie") not in EXIT_TYPES:
        problems.append("type de sortie manquant (hiérarchie §06)")
    if draft.get("resultat_r") is None:
        problems.append("résultat R manquant")
    if draft.get("sl_distance_respectee") is None:
        problems.append("« distance SL respectée ? » non renseigné")
    if draft.get("sl_distance_respectee") is False and draft.get("erreur_type") != "A":
        problems.append("SL non respecté ⇒ erreur Type A automatique (règle absolue §07)")
    if draft.get("type_sortie") in EARLY_EXITS and draft.get("sortie_justifiee") is None:
        problems.append("sortie précoce : justification requise (friction #2)")
    return problems


def aggregates(store: EventStore) -> dict[str, Any]:
    """Projection over locked trades — the numbers of the « Historique & agrégats » view."""
    trades = store.journal_entries("trade_locked")
    days: dict[str, dict[str, Any]] = {}
    total = {"trades": 0, "r_total": 0.0, "wins": 0,
             "err_a": 0, "err_b": 0, "err_c": 0,
             "early_evaluated": 0, "early_unjustified": 0}
    for t in trades:
        r = float(t.get("resultat_r") or 0.0)
        day = day_of(t["ts"])
        d = days.setdefault(day, {"day": day, "trades": 0, "r_total": 0.0, "wins": 0})
        d["trades"] += 1
        d["r_total"] = round(d["r_total"] + r, 2)
        total["trades"] += 1
        total["r_total"] = round(total["r_total"] + r, 2)
        if r > 0:
            d["wins"] += 1
            total["wins"] += 1
        err = t.get("erreur_type")
        if err in ERREURS:
            total[f"err_{err.lower()}"] += 1
        if t.get("type_sortie") in EARLY_EXITS:
            total["early_evaluated"] += 1
            if t.get("sortie_justifiee") is False:
                total["early_unjustified"] += 1
    total["winrate_pct"] = (round(100.0 * total["wins"] / total["trades"], 1)
                            if total["trades"] else None)
    total["friction2_pct"] = (round(100.0 * total["early_unjustified"] / total["early_evaluated"], 1)
                              if total["early_evaluated"] else None)
    total["days"] = len(days)
    return {"total": total,
            "by_day": sorted(days.values(), key=lambda d: d["day"], reverse=True)}


def derive_lockout(store: EventStore, now: Optional[float] = None) -> dict[str, Any]:
    """KillSwitch layer (MR §01b) : 2 pertes consécutives → pause 24 h. DERIVED state."""
    now = now if now is not None else time.time()
    trades = store.journal_entries("trade_locked")
    streak, last_ts = 0, None
    for t in reversed(trades):
        r = t.get("resultat_r")
        if r is not None and float(r) < 0:
            streak += 1
            last_ts = last_ts or t["ts"]
        else:
            break
    active = streak >= 2 and last_ts is not None and now < last_ts + 24 * 3600
    return {"active": active, "consecutive_losses": streak,
            "until_ts": (last_ts + 24 * 3600) if active else None,
            "rule": "2 pertes consécutives → pause 24 h (KillSwitch)"}


async def fire_webhook(cfg: dict[str, Any], event: str, payload: dict[str, Any],
                       store: EventStore) -> None:
    """Async n8n webhook (trade_closed / session_closed) — logged, never blocking."""
    if not cfg.get("enabled") or not cfg.get("url"):
        return

    async def _send() -> None:
        started = time.time()
        try:
            headers = {"content-type": "application/json"}
            if cfg.get("api_key"):
                headers["X-API-Key"] = cfg["api_key"]
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(cfg["url"], json={"event": event, **payload},
                                        headers=headers)
            store.log_ai_call("n8n", f"journal_{event}", f"HTTP_{res.status_code}",
                              latency_ms=(time.time() - started) * 1000)
        except Exception as exc:
            store.log_ai_call("n8n", f"journal_{event}", f"FAIL_{type(exc).__name__}",
                              latency_ms=(time.time() - started) * 1000)

    asyncio.get_running_loop().create_task(_send())
