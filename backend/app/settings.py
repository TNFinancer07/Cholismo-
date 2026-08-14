"""Two-tier parameter engine (brainstorm « Paramètres », D-023).

GLOBAL sets the default rule; SPECIFIC (per execution strategy) inherits it and may
override — with hard invariants enforced HERE, server-side, never by the UI:

  * AUTORITÉ parameters are displayed but LOCKED (409): the unified-signal weights,
    Phase 0 thresholds, calibration targets… come verbatim from PRD/reference and are
    not knobs. Only PLACEHOLDER / cockpit parameters are editable.
  * Risk-capped parameters are REDUCE-ONLY at the specific tier: an override may lower
    the resolved global, never exceed it (422). The hierarchy protects capital by
    construction, not by discipline.
  * Guarded parameters require an explicit acknowledgement (428) when moved below
    their guard threshold (« baisser le seuil pour trader plus »).
  * In LIVE mode every write is locked (423) unless the caller passes an explicit
    unlock flag — no émotion-driven re-tuning mid-session.

Every change is an APPEND-ONLY SettingEvent (SQLite, same RAISE ABORT triggers as the
decision log): current config is a projection, history and presets come for free.
The resolved map is cached in-process so the engine hot path reads a dict, never SQLite.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from . import config
from .event_store import EventStore, get_store

GLOBAL_SCOPE = "GLOBAL"
# Specific scopes = the two REAL Sony execution strategies (reference/sony/*).
SPECIFIC_SCOPES = ("SVS", "MEAN_REVERSION")


class Param:
    __slots__ = ("key", "domain", "label", "control", "unit", "default", "minimum",
                 "maximum", "choices", "locked", "authority", "reduce_only",
                 "guard_below", "guard_message", "scoped")

    def __init__(self, key: str, domain: str, label: str, control: str = "number",
                 unit: str = "", default: Any = None, minimum: Optional[float] = None,
                 maximum: Optional[float] = None, choices: Optional[list[str]] = None,
                 locked: bool = False, authority: str = "", reduce_only: bool = False,
                 guard_below: Optional[float] = None, guard_message: str = "",
                 scoped: bool = False):
        self.key = key
        self.domain = domain
        self.label = label
        self.control = control
        self.unit = unit
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.choices = choices or []
        self.locked = locked
        self.authority = authority
        self.reduce_only = reduce_only
        self.guard_below = guard_below
        self.guard_message = guard_message
        self.scoped = scoped

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "domain": self.domain, "label": self.label,
                "control": self.control, "unit": self.unit, "default": self.default,
                "minimum": self.minimum, "maximum": self.maximum, "choices": self.choices,
                "locked": self.locked, "authority": self.authority,
                "reduce_only": self.reduce_only, "guard_below": self.guard_below,
                "scoped": self.scoped}


# Domains mirror the brainstorm: signal (A), risk (B), alerts (C), ai (D), live (Mode Live).
CATALOG: dict[str, Param] = {p.key: p for p in [
    # --- A · Seuils du signal — the AUTORITÉ core is displayed, not editable ---
    Param("signal.weight_structure", "signal", "Pondération Structure", unit="%",
          default=config.WEIGHT_STRUCTURE * 100, locked=True, authority="PRD §0 — AUTORITÉ"),
    Param("signal.weight_order_flow", "signal", "Pondération Order Flow", unit="%",
          default=config.WEIGHT_ORDER_FLOW * 100, locked=True, authority="PRD §0 — AUTORITÉ"),
    Param("signal.weight_macro", "signal", "Pondération Macro", unit="%",
          default=config.WEIGHT_MACRO * 100, locked=True,
          authority="PRD §0 — AUTORITÉ (poids → 0 tant que A3 NON CALIBRÉ)"),
    Param("signal.weight_sentiment", "signal", "Pondération Sentiment", unit="%",
          default=config.WEIGHT_SENTIMENT * 100, locked=True, authority="PRD §0 — AUTORITÉ"),
    Param("signal.weight_quality", "signal", "Pondération Qualité", unit="%",
          default=config.WEIGHT_QUALITY * 100, locked=True, authority="PRD §0 — AUTORITÉ"),
    Param("signal.chop_crit", "signal", "CHOP critique (veto Phase 0)", default=config.CHOP_CRIT,
          locked=True, authority="TASKS §2.3 — AUTORITÉ"),
    Param("signal.vix_crit", "signal", "VIX critique (veto Phase 0)", default=config.VIX_CRIT,
          locked=True, authority="TASKS §2.3 — AUTORITÉ"),
    Param("decision.arm_threshold", "signal", "Seuil d'armement fenêtre C3", unit="/100",
          default=config.DECISION_ARM_THRESHOLD, minimum=0, maximum=100,
          authority="PLACEHOLDER D-008", guard_below=50,
          guard_message="Sous 50, la fenêtre C3 s'arme sur des signaux faibles — "
                        "confirmer explicitement (piège « baisser le seuil pour trader plus »)."),

    # --- B · Risk management — caps consumed by the RECAP cockpit, reduce-only ---
    Param("risk.max_r_per_session", "risk", "Risque max par session", unit="R",
          default=3.0, minimum=0.5, maximum=10, reduce_only=True, scoped=True,
          authority="PLACEHOLDER D-023 — consommé par la jauge RECAP"),
    Param("risk.max_drawdown_r_day", "risk", "Drawdown max journalier", unit="R",
          default=2.0, minimum=0.5, maximum=10, reduce_only=True, scoped=True,
          authority="PLACEHOLDER D-023 — consommé par la jauge RECAP"),
    Param("risk.sizing_lock_pct", "risk", "Sizing verrouillé (calibration)", unit="%",
          default=config.SIZING_LOCK_PCT, locked=True, authority="CLAUDE §1 — AUTORITÉ"),
    Param("risk.r_unit_usd", "risk", "Valeur d'un R", unit="$",
          default=config.R_UNIT_USD, minimum=1, maximum=100000,
          authority="PLACEHOLDER D-018"),
    Param("risk.streak_audit_threshold", "risk", "Audit forcé après N pertes",
          default=config.STREAK_AUDIT_THRESHOLD, locked=True, authority="PRD §C2 — AUTORITÉ"),

    # --- C · Alertes — consumed by the Mode Live view ---
    Param("alerts.cooldown_seconds", "alerts", "Anti-spam (délai mini entre alertes)",
          unit="s", default=30, minimum=0, maximum=600, scoped=True,
          authority="PLACEHOLDER D-023"),
    Param("alerts.sound_enabled", "alerts", "Son sur passage ROUGE", control="bool",
          default=False, authority="PLACEHOLDER D-023"),

    # --- D · IA — cadence/coût bornés et loggés (CLAUDE §7) ---
    Param("ai.groq_timeout_ms", "ai", "Budget Groq Phase 0 (advisory)", unit="ms",
          default=config.GROQ_TIMEOUT_SECONDS * 1000, locked=True,
          authority="CLAUDE §7 — AUTORITÉ (< 100 ms, fail-closed)"),
    Param("ai.claude_scoring_period_seconds", "ai", "Période scoring Claude", unit="s",
          default=config.CLAUDE_SCORING_PERIOD_SECONDS, minimum=60, maximum=3600,
          authority="PLACEHOLDER — hors hot path (CLAUDE §2.8)"),
    Param("ai.gemini_audit_every_n_trades", "ai", "Audit Gemini tous les N trades",
          default=config.GEMINI_AUDIT_EVERY_N_TRADES, locked=True,
          authority="CLAUDE §7 — AUTORITÉ"),

    # --- Mode Live — cadence of the deterministic reading cycle ---
    Param("live.cycle_seconds", "live", "Cycle lecture marché (fenêtre active)", unit="s",
          default=180, minimum=30, maximum=1800, authority="PLACEHOLDER D-023"),
    Param("live.cycle_offwindow_seconds", "live", "Cycle lecture marché (hors fenêtre)",
          unit="s", default=600, minimum=60, maximum=3600, authority="PLACEHOLDER D-023"),
]}


class SettingsError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class _Resolved:
    """In-process cache of the projection — the hot path reads a dict, never SQLite."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seq = -1
        self.overrides: dict[tuple[str, str], Any] = {}  # (key, scope) -> value


_cache = _Resolved()


def _replay(store: EventStore) -> None:
    events = store.setting_events()
    overrides: dict[tuple[str, str], Any] = {}
    presets: dict[str, dict] = {}
    for e in events:
        if e["action"] == "set" and e["key"] in CATALOG:
            overrides[(e["key"], e["scope"] or GLOBAL_SCOPE)] = e["value"]
        elif e["action"] == "revert" and e["key"]:
            overrides.pop((e["key"], e["scope"] or GLOBAL_SCOPE), None)
        elif e["action"] == "preset_save" and e["name"]:
            presets[e["name"]] = e["value"] or {}
        elif e["action"] in ("preset_apply", "import"):
            payload = e["value"] if e["action"] == "import" else presets.get(e["name"] or "", {})
            overrides = {}
            for item in (payload or {}).get("overrides", []):
                if item.get("key") in CATALOG:
                    overrides[(item["key"], item.get("scope") or GLOBAL_SCOPE)] = item.get("value")
    _cache.overrides = overrides
    _cache.seq = events[-1]["seq"] if events else 0


def _ensure(store: Optional[EventStore] = None) -> None:
    store = store or get_store()
    with _cache.lock:
        if _cache.seq < 0:
            _replay(store)


def invalidate() -> None:
    with _cache.lock:
        _cache.seq = -1


def value(key: str, scope: Optional[str] = None) -> Any:
    """Resolved value: specific override -> global override -> catalog default."""
    _ensure()
    param = CATALOG[key]
    if scope and (key, scope) in _cache.overrides:
        return _cache.overrides[(key, scope)]
    if (key, GLOBAL_SCOPE) in _cache.overrides:
        return _cache.overrides[(key, GLOBAL_SCOPE)]
    return param.default


def _tier(key: str, scope: str) -> str:
    if scope != GLOBAL_SCOPE and (key, scope) in _cache.overrides:
        return "override"
    if (key, GLOBAL_SCOPE) in _cache.overrides:
        return "global" if scope != GLOBAL_SCOPE else "override"
    return "default"


def payload(store: Optional[EventStore] = None) -> dict[str, Any]:
    """Full settings view: catalog + resolved values per scope + provenance badge."""
    store = store or get_store()
    _ensure(store)
    rows = []
    for param in CATALOG.values():
        scopes = {GLOBAL_SCOPE: {"value": value(param.key, None),
                                 "tier": _tier(param.key, GLOBAL_SCOPE)}}
        if param.scoped:
            for scope in SPECIFIC_SCOPES:
                scopes[scope] = {"value": value(param.key, scope),
                                 "tier": _tier(param.key, scope)}
        rows.append({**param.as_dict(), "scopes": scopes})
    presets = {}
    for e in store.setting_events():
        if e["action"] == "preset_save" and e["name"]:
            presets[e["name"]] = e["ts"]
    return {
        "parameters": rows,
        "specific_scopes": list(SPECIFIC_SCOPES),
        "overrides_count": len(_cache.overrides),
        "presets": [{"name": n, "ts": ts} for n, ts in sorted(presets.items())],
    }


def history(store: Optional[EventStore] = None, limit: int = 50) -> list[dict[str, Any]]:
    store = store or get_store()
    return list(reversed(store.setting_events()))[:limit]


def export_overrides() -> dict[str, Any]:
    _ensure()
    return {"version": 1, "exported_ts": time.time(),
            "overrides": [{"key": k, "scope": s, "value": v}
                          for (k, s), v in sorted(_cache.overrides.items())]}


def _validate(param: Param, scope: str, raw: Any, ack_guard: bool) -> Any:
    if param.locked:
        raise SettingsError(409, f"« {param.label} » est AUTORITÉ ({param.authority}) — non modifiable")
    if scope != GLOBAL_SCOPE and not param.scoped:
        raise SettingsError(422, f"« {param.label} » est un paramètre global uniquement")
    if scope != GLOBAL_SCOPE and scope not in SPECIFIC_SCOPES:
        raise SettingsError(422, f"scope inconnu : {scope}")

    if param.control == "bool":
        if not isinstance(raw, bool):
            raise SettingsError(422, f"« {param.label} » attend un booléen")
        return raw
    if param.control == "choice":
        if raw not in param.choices:
            raise SettingsError(422, f"« {param.label} » ∈ {param.choices}")
        return raw
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise SettingsError(422, f"« {param.label} » attend un nombre") from None
    if param.minimum is not None and val < param.minimum:
        raise SettingsError(422, f"« {param.label} » ≥ {param.minimum}")
    if param.maximum is not None and val > param.maximum:
        raise SettingsError(422, f"« {param.label} » ≤ {param.maximum}")
    if param.reduce_only and scope != GLOBAL_SCOPE:
        ceiling = float(value(param.key, None))
        if val > ceiling:
            raise SettingsError(
                422, f"le spécifique ne peut que RÉDUIRE : {val:g} {param.unit} > plafond "
                     f"global {ceiling:g} {param.unit} (protection par construction)")
    if param.guard_below is not None and val < param.guard_below and not ack_guard:
        raise SettingsError(428, f"garde-fou : {param.guard_message or param.label} "
                                 f"(< {param.guard_below:g}) — renvoyer avec ack_guard=true")
    return val


def check_live_lock(mode: str, unlock_live: bool) -> None:
    """Read-only in LIVE session unless explicitly unlocked (brainstorm §cross)."""
    if mode == "LIVE" and not unlock_live:
        raise SettingsError(423, "Paramètres en LECTURE SEULE pendant une session LIVE — "
                                 "déverrouillage explicite requis (unlock_live=true)")


def set_value(key: str, raw: Any, scope: Optional[str], operator: str,
              ack_guard: bool = False, store: Optional[EventStore] = None) -> dict[str, Any]:
    store = store or get_store()
    if key not in CATALOG:
        raise SettingsError(404, f"paramètre inconnu : {key}")
    scope = scope or GLOBAL_SCOPE
    _ensure(store)
    val = _validate(CATALOG[key], scope, raw, ack_guard)
    event = store.append_setting("set", key=key, scope=scope, value=val, operator=operator)
    invalidate()
    return event


def revert(key: str, scope: Optional[str], operator: str,
           store: Optional[EventStore] = None) -> dict[str, Any]:
    """« Revenir au global » (ou au défaut) — removes one override, history keeps it."""
    store = store or get_store()
    if key not in CATALOG:
        raise SettingsError(404, f"paramètre inconnu : {key}")
    event = store.append_setting("revert", key=key, scope=scope or GLOBAL_SCOPE,
                                 operator=operator)
    invalidate()
    return event


def save_preset(name: str, operator: str, store: Optional[EventStore] = None) -> dict[str, Any]:
    store = store or get_store()
    name = name.strip().upper()[:24]
    if not name:
        raise SettingsError(422, "nom de preset vide")
    event = store.append_setting("preset_save", name=name, value=export_overrides(),
                                 operator=operator)
    invalidate()
    return event


def apply_preset(name: str, operator: str, store: Optional[EventStore] = None) -> dict[str, Any]:
    store = store or get_store()
    known = {e["name"] for e in store.setting_events() if e["action"] == "preset_save"}
    if name not in known:
        raise SettingsError(404, f"preset inconnu : {name}")
    event = store.append_setting("preset_apply", name=name, operator=operator)
    invalidate()
    return event


def import_overrides(payload_in: dict[str, Any], operator: str,
                     store: Optional[EventStore] = None) -> dict[str, Any]:
    store = store or get_store()
    overrides = payload_in.get("overrides")
    if not isinstance(overrides, list):
        raise SettingsError(422, "import invalide : champ overrides manquant")
    _ensure(store)
    # Full validation BEFORE the event is written — nothing half-applied.
    for item in overrides:
        key = item.get("key")
        if key not in CATALOG:
            raise SettingsError(422, f"import : paramètre inconnu {key}")
        _validate(CATALOG[key], item.get("scope") or GLOBAL_SCOPE, item.get("value"),
                  ack_guard=True)
    event = store.append_setting("import", value={"overrides": overrides}, operator=operator)
    invalidate()
    return event
