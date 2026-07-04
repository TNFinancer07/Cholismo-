"""Execution reconciliation (MVP — PRD §Réconciliation).

NinjaTrader CSV import -> match fills to DecisionEvents by timestamp + instrument ->
append ReconEvents (+OutcomeEvents for matched fills). Behavioral proof requires linking
terminal decisions to real executions: a GO without a fill, or a fill without a GO, is
flagged matched=false. Nothing is ever updated — only appended.
"""
from __future__ import annotations

import csv
import io
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from . import config
from .event_store import EventStore

# Tolerant header aliases (NinjaTrader "Trades" grid export and close variants).
_ALIASES = {
    "instrument": {"instrument", "symbol", "instrument name"},
    "entry_time": {"entry time", "entrytime", "time", "entry_time", "open time"},
    "profit": {"profit", "pnl", "profit ($)", "net profit", "profit currency"},
    "r_multiple": {"r", "r multiple", "r_multiple", "rmultiple"},
    "qty": {"qty", "quantity", "size"},
}

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %I:%M:%S %p",
                 "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def _map_columns(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        norm = _norm_header(header)
        for key, aliases in _ALIASES.items():
            if key not in mapping and norm in aliases:
                mapping[key] = idx
    return mapping


def _parse_money(raw: str) -> Optional[float]:
    raw = raw.strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^\d.,\-]", "", raw.strip("()"))
    if cleaned.count(",") and cleaned.count("."):
        cleaned = cleaned.replace(",", "")           # 1,234.56
    elif cleaned.count(","):
        cleaned = cleaned.replace(",", ".")          # 12,50
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative else value


def _parse_time(raw: str, tz_offset_minutes: int) -> Optional[float]:
    raw = raw.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{9,13}(\.\d+)?", raw):  # epoch seconds or millis
        ts = float(raw)
        return ts / 1000.0 if ts > 1e12 else ts
    for fmt in _TIME_FORMATS:
        try:
            dt = datetime.strptime(raw.split(".")[0], fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp() - tz_offset_minutes * 60
        except ValueError:
            continue
    return None


def _norm_instrument(raw: str) -> str:
    # "ES 09-26" / "ES SEP26" / "EURUSD" -> root symbol
    return re.split(r"[\s_-]", raw.strip().upper())[0]


def parse_ninjatrader_csv(data: bytes, tz_offset_minutes: int = 0) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return []
    mapping = _map_columns(rows[0])
    if "instrument" not in mapping or "entry_time" not in mapping:
        raise ValueError("CSV NinjaTrader : colonnes 'Instrument' et 'Entry time' introuvables")
    fills = []
    for row in rows[1:]:
        def cell(key: str) -> str:
            idx = mapping.get(key)
            return row[idx] if idx is not None and idx < len(row) else ""
        ts = _parse_time(cell("entry_time"), tz_offset_minutes)
        if ts is None:
            continue
        profit = _parse_money(cell("profit"))
        r_cell = cell("r_multiple").strip()
        r_multiple = _parse_money(r_cell) if r_cell else None
        if r_multiple is None and profit is not None:
            r_multiple = round(profit / config.R_UNIT_USD, 3)  # PLACEHOLDER unit — D-018
        fills.append({"instrument": _norm_instrument(cell("instrument")),
                      "entry_ts": ts, "profit": profit, "r_multiple": r_multiple})
    return fills


def reconcile(store: EventStore, fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Match GO decisions <-> fills within RECON_MATCH_WINDOW_SECONDS on same instrument."""
    decisions = [d for d in store.events("DecisionEvent") if d.get("decision") == "GO"]
    already_reconciled = {r.get("decision_id") for r in store.events("ReconEvent")
                          if r.get("decision_id")}
    candidates = [d for d in decisions if d["id"] not in already_reconciled]

    matched, used_fill_idx = [], set()
    for decision in candidates:
        best_idx, best_gap = None, None
        for idx, fill in enumerate(fills):
            if idx in used_fill_idx:
                continue
            if fill["instrument"] != _norm_instrument(decision.get("instrument") or ""):
                continue
            gap = abs(fill["entry_ts"] - decision["ts"])
            if gap <= config.RECON_MATCH_WINDOW_SECONDS and (best_gap is None or gap < best_gap):
                best_idx, best_gap = idx, gap
        if best_idx is not None:
            used_fill_idx.add(best_idx)
            matched.append((decision, fills[best_idx], best_gap))

    now = time.time()
    summary = {"matched": 0, "go_without_fill": 0, "fill_without_go": 0, "outcomes": 0}

    for decision, fill, gap in matched:
        store.append("ReconEvent", {
            "decision_id": decision["id"], "fill_source": "ninjatrader",
            "matched": True, "gap_seconds": round(gap, 1),
            "fill_entry_ts": fill["entry_ts"], "instrument": fill["instrument"]}, ts=now)
        summary["matched"] += 1
        if fill["r_multiple"] is not None:
            outcome = ("WIN" if fill["r_multiple"] > 0
                       else "LOSS" if fill["r_multiple"] < 0 else "SCRATCH")
            store.append("OutcomeEvent", {
                "decision_id": decision["id"], "outcome": outcome,
                "error_type": None, "r_multiple": fill["r_multiple"],
                "source": "ninjatrader_import"}, ts=now)
            summary["outcomes"] += 1

    matched_decision_ids = {d["id"] for d, _, _ in matched}
    for decision in candidates:
        if decision["id"] not in matched_decision_ids:
            store.append("ReconEvent", {
                "decision_id": decision["id"], "fill_source": "ninjatrader",
                "matched": False, "anomaly": "go_without_fill",
                "instrument": decision.get("instrument")}, ts=now)
            summary["go_without_fill"] += 1

    for idx, fill in enumerate(fills):
        if idx not in used_fill_idx:
            store.append("ReconEvent", {
                "decision_id": None, "fill_source": "ninjatrader",
                "matched": False, "anomaly": "fill_without_go",
                "fill_entry_ts": fill["entry_ts"], "instrument": fill["instrument"],
                "r_multiple": fill["r_multiple"]}, ts=now)
            summary["fill_without_go"] += 1

    return summary
