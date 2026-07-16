"""Snapshot Déterministe (D-030) — capture instantanée des 4 blocs microstructure/macro
(carnet d'ordres, CVD par niveau, calendrier économique, alertes IA) en JSON + Markdown.

DÉTERMINISTE : pure projection du `ContextSchema` à l'instant du déclenchement — aucun LLM,
aucun hasard (le seul non-déterminisme est l'horodatage, passé en paramètre). FAIL-CLOSED
(§3) : capture l'état RÉEL, gaps compris (freshness ABSENT / value None) — jamais un carnet
ou un CVD inventé. Écriture ASYNC NON-BLOQUANTE (`asyncio.to_thread`) : l'I/O fichier ne
bloque jamais la boucle d'événements ni le hot path (§7). OBSERVATION, jamais un ordre (§2.1).
"""
from __future__ import annotations

import asyncio
import json
import os

from pydantic import BaseModel

from .schema import ContextSchema


class Snapshot(BaseModel):
    """Capture instantanée — chaque bloc est le dump JSON tel quel du ContextSchema (pas de
    ré-interprétation : le snapshot reflète EXACTEMENT ce que le terminal savait à l'instant)."""
    snapshot_id: str
    created_ts: float
    operator: str
    session_marker: str
    order_book: dict        # s1_state.order_book (MetaField dumpé)
    cvd_by_level: dict      # s1_state.cvd_by_level dumpé
    econ_calendar: dict     # econ_calendar dumpé
    liquidity_sweep: dict   # liquidity_sweep dumpé


def build_snapshot(schema: ContextSchema, snapshot_id: str, created_ts: float,
                   operator: str, session_marker: str) -> Snapshot:
    """Projette les 4 blocs du schéma courant. Déterministe : dépend uniquement des entrées."""
    dump = schema.model_dump(mode="json")
    return Snapshot(
        snapshot_id=snapshot_id, created_ts=created_ts,
        operator=operator, session_marker=session_marker,
        order_book=dump["s1_state"]["order_book"],
        cvd_by_level=dump["s1_state"]["cvd_by_level"],
        econ_calendar=dump["econ_calendar"],
        liquidity_sweep=dump["liquidity_sweep"],
    )


# ---------- rendu Markdown lisible (honnête sur les données absentes) ----------

def _fmt_ts(ts: float) -> str:
    # Horodatage lisible sans dépendre du fuseau — UTC compact, déterministe.
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%SZ")


def _md_order_book(ob: dict) -> str:
    if ob.get("freshness") != "FRESH" or not isinstance(ob.get("value"), dict):
        return f"- **PAS DE DONNÉES** (freshness : {ob.get('freshness', 'ABSENT')})"
    val = ob["value"]
    bids, asks = val.get("bids") or [], val.get("asks") or []
    if not bids or not asks:
        return "- **PAS DE DONNÉES** (carnet vide)"
    best_bid, best_ask = bids[0][0], asks[0][0]
    spread = round((best_ask - best_bid) / 0.25, 2)
    flags = ", ".join(ob.get("flags") or []) or "—"
    return (f"- Meilleur bid : **{best_bid}** ({bids[0][1]}) · meilleur ask : **{best_ask}** "
            f"({asks[0][1]})\n- Spread : **{spread} ticks**"
            f"{'  ⚠ CROISÉ' if spread <= 0 else ''}\n- Flags : {flags}")


def _md_cvd(cvd: dict) -> str:
    levels = cvd.get("levels") or []
    if not levels:
        return "- **PAS DE DONNÉES**"
    poc = max(levels, key=lambda le: le["buy"] + le["sell"])
    reset = cvd.get("reset_reason") or "—"
    tags = []
    if cvd.get("stale"):
        tags.append("FIGÉ")
    if cvd.get("capped"):
        tags.append("SATURÉ")
    head = (f"- Net cumulé Δ : **{cvd.get('total_delta', 0):+g}** · reset : {reset}"
            f"{'  [' + ', '.join(tags) + ']' if tags else ''}\n"
            f"- POC (volume max) : **{poc['price']}** (Δ {poc['delta']:+g})\n\n"
            "| Prix | Delta | Buy | Sell |\n|---:|---:|---:|---:|\n")
    body = "\n".join(f"| {le['price']} | {le['delta']:+g} | {le['buy']:g} | {le['sell']:g} |"
                     for le in sorted(levels, key=lambda le: le["price"], reverse=True))
    return head + body


def _md_calendar(cal: dict, now: float) -> str:
    events = (cal.get("events") or {})
    if events.get("freshness") != "FRESH" or not isinstance(events.get("value"), list):
        return f"- **PAS DE DONNÉES** (freshness : {events.get('freshness', 'ABSENT')})"
    vals = events["value"]
    if not vals:
        return "- Aucun événement dans la fenêtre"
    lines = []
    for e in vals[:6]:
        dt = e["ts"] - now
        sign = "T−" if dt >= 0 else "T+"
        mins = int(abs(dt) // 60)
        lines.append(f"- T{e['tier']} · **{e['name']}** ({e.get('region', '')}) — "
                     f"{sign}{mins}m")
    return "\n".join(lines)


def _md_sweep(sw: dict) -> str:
    if not sw.get("assessable"):
        return "- **IMPOSSIBLE À ÉVALUER** — données microstructure/news insuffisantes"
    if not sw.get("triggered") or not sw.get("alert"):
        return "- Aucun sweep actif"
    a = sw["alert"]
    return (f"- **SWEEP ACTIF** — {a.get('trigger', '')} · direction : "
            f"{a.get('direction') or '—'}\n- News : {a.get('news_context') or '—'}\n"
            f"- Raison : {sw.get('reason', '')}")


def render_markdown(snap: Snapshot) -> str:
    return (
        f"# Snapshot {snap.snapshot_id}\n\n"
        f"- **Créé** : {_fmt_ts(snap.created_ts)}\n"
        f"- **Opérateur** : {snap.operator} · **Session** : {snap.session_marker}\n\n"
        f"## Carnet d'ordres (ES)\n{_md_order_book(snap.order_book)}\n\n"
        f"## CVD par niveau\n{_md_cvd(snap.cvd_by_level)}\n\n"
        f"## Calendrier économique\n{_md_calendar(snap.econ_calendar, snap.created_ts)}\n\n"
        f"## Alertes IA (Liquidity Sweep)\n{_md_sweep(snap.liquidity_sweep)}\n\n"
        f"---\n*Observation instantanée — jamais un ordre (§2.1). Généré déterministiquement.*\n"
    )


# ---------- écriture async non-bloquante ----------

def _write_files(directory: str, snapshot_id: str, payload: dict, md: str) -> tuple[str, str]:
    """I/O bloquante — appelée UNIQUEMENT via `asyncio.to_thread` (hors boucle d'événements)."""
    os.makedirs(directory, exist_ok=True)
    jpath = os.path.join(directory, f"{snapshot_id}.json")
    mpath = os.path.join(directory, f"{snapshot_id}.md")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(md)
    return jpath, mpath


async def write_snapshot(snap: Snapshot, directory: str) -> dict:
    """Sérialise (JSON + Markdown) puis OFFLOADE l'écriture disque dans un thread : la boucle
    d'événements — donc le hot path — n'est jamais bloquée (§7)."""
    payload = snap.model_dump(mode="json")
    md = render_markdown(snap)
    jpath, mpath = await asyncio.to_thread(_write_files, directory, snap.snapshot_id, payload, md)
    return {"snapshot_id": snap.snapshot_id, "created_ts": snap.created_ts,
            "json_path": jpath, "md_path": mpath}


# ---------- déclencheur partagé (endpoint /snapshot ET auto-trigger log_scraper) ----------

# Compteur monotone pour désambiguïser deux captures dans la même milliseconde (rafale de
# fills). Lu+incrémenté SYNCHRONEMENT avant tout `await` → pas de course sur l'event loop
# coopératif (un seul opérateur par instance, CLAUDE §9).
_id_seq: dict[str, int] = {"ms": -1, "seq": 0}


def _unique_snapshot_id(now: float, operator: str) -> str:
    ms = int(now * 1000)
    if _id_seq["ms"] == ms:
        _id_seq["seq"] += 1
    else:
        _id_seq["ms"] = ms
        _id_seq["seq"] = 0
    suffix = "" if _id_seq["seq"] == 0 else f"-{_id_seq['seq']}"
    return f"snap_{ms}_{operator.lower()}{suffix}"


async def capture_snapshot(engine, now: float, *, snapshot_id: str | None = None,
                           directory: str | None = None) -> dict:
    """Capture + écrit le snapshot du schéma courant. Chemin UNIQUE partagé par l'endpoint
    `POST /snapshot` et l'auto-déclenchement du log_scraper : projection déterministe, écriture
    async non-bloquante (§7). L'id est horodaté à la milliseconde ET désambiguïsé par un
    compteur monotone → deux fills dans la même ms produisent deux fichiers distincts, jamais
    un écrasement. Passer `snapshot_id` pour forcer un id explicite."""
    from . import config
    si = engine.schema.session_identity
    operator = si.operator.value
    snap_id = snapshot_id or _unique_snapshot_id(now, operator)
    snap = build_snapshot(engine.schema, snap_id, now, operator, si.session_marker.value)
    return await write_snapshot(snap, directory or config.SNAPSHOT_DIR)
