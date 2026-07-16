"""Trade Reconciliator (D-033) — moteur analytique FIFO sur l'historique des snapshots.

ANALYTIQUE HORS-LIGNE : relit les `fill` déclencheurs embarqués dans les snapshots (D-030/031)
et les apparie entrée↔sortie par instrument en FIFO → `CompletedTrade` (durée, P&L USD,
R-Multiple). Ne passe JAMAIS d'ordre (§2.1) — c'est une lecture de projections passées.

FAIL-CLOSED (§3) — jamais un P&L inventé :
- fill sans côté (BUY/SELL) / prix / quantité → compté « non résolu », écarté ;
- contrat hors dictionnaire → P&L en POINTS seulement, `pnl_usd`/`r_multiple` = None ;
- dossier absent/illisible → aucune donnée.

`v1 provisional` : le dictionnaire de contrats et le risque de référence sont des paramètres
figés (config) ; l'appariement FIFO net (avec flips de position) est le cœur déterministe.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from . import config

POINT_VALUE: dict[str, float] = config.CONTRACT_POINT_VALUE
REFERENCE_RISK_USD: float = config.R_UNIT_USD

_ROOT_RE = re.compile(r"^[A-Za-z]+")


def normalize_instrument(instrument: str) -> str:
    """Ramène un nom d'instrument NT8 (« ES 12-24 ») à sa racine contrat (« ES »), en
    majuscules. Le point-value se cherche sur cette racine. Forme non reconnue → chaîne vide
    ou racine best-effort (le lookup renverra alors None → fail-closed)."""
    token = (instrument or "").strip().split(" ")[0]
    m = _ROOT_RE.match(token)
    return m.group(0).upper() if m else ""


@dataclass
class Fill:
    """Un fill NT8 (déjà exécuté par l'humain) extrait d'un snapshot. `side` peut être None si
    le log ne l'exposait pas → traité comme non résolu (jamais deviné)."""
    instrument: str
    side: Optional[str]     # "BUY" | "SELL" | None
    price: float
    quantity: int
    ts: float


class CompletedTrade(BaseModel):
    instrument: str
    root: str
    direction: str          # LONG | SHORT (côté de l'ENTRÉE)
    quantity: int
    entry_price: float
    exit_price: float
    entry_ts: float
    exit_ts: float
    exposure_seconds: float
    pnl_points: float
    point_value: Optional[float]
    pnl_usd: Optional[float]
    r_multiple: Optional[float]


class ReconResult(BaseModel):
    trades: list[CompletedTrade]
    open_lots: int          # lots ouverts non clôturés en fin d'historique
    unresolved_fills: int   # fills écartés (côté/prix/quantité manquants)
    summary: dict


def reconcile_fills(fills: list[Fill]) -> ReconResult:
    """Apparie les fills en FIFO par racine d'instrument. Position nette : un fill de même sens
    OUVRE/ajoute un lot ; un fill de sens opposé FERME les lots les plus anciens (FIFO), et tout
    surplus RETOURNE la position (flip). Chaque appariement produit un `CompletedTrade`."""
    books: dict[str, deque[list]] = defaultdict(deque)   # racine → lots [side, qty, price, ts]
    trades: list[CompletedTrade] = []
    unresolved = 0

    # sans horodatage → impossible d'ordonner : non résolu (jamais placé dans le carnet). Écarter
    # AVANT le tri, sinon `sorted` compare None et lève (bug trouvé au /devil).
    usable = []
    for f in fills:
        if f.ts is None:
            unresolved += 1
        else:
            usable.append(f)

    for f in sorted(usable, key=lambda x: x.ts):
        if f.side not in ("BUY", "SELL") or f.price is None or f.quantity is None or f.quantity <= 0:
            unresolved += 1
            continue
        root = normalize_instrument(f.instrument)
        book = books[root]
        qty = f.quantity
        # ferme les lots opposés les plus anciens
        while qty > 0 and book and book[0][0] != f.side:
            lot = book[0]
            matched = min(qty, lot[1])
            direction = "LONG" if lot[0] == "BUY" else "SHORT"
            entry_price, exit_price = lot[2], f.price
            pnl_points = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
            pv = POINT_VALUE.get(root)
            pnl_usd = round(pnl_points * matched * pv, 2) if pv is not None else None
            # R indéfini si le risque de référence est nul/absent → None (jamais /0, jamais inventé)
            r_multiple = (round(pnl_usd / REFERENCE_RISK_USD, 4)
                          if (pnl_usd is not None and REFERENCE_RISK_USD) else None)
            trades.append(CompletedTrade(
                instrument=f.instrument, root=root, direction=direction, quantity=matched,
                entry_price=entry_price, exit_price=exit_price, entry_ts=lot[3], exit_ts=f.ts,
                exposure_seconds=f.ts - lot[3], pnl_points=round(pnl_points, 6),
                point_value=pv, pnl_usd=pnl_usd, r_multiple=r_multiple))
            lot[1] -= matched
            qty -= matched
            if lot[1] == 0:
                book.popleft()
        # surplus → ouvre un lot dans le sens du fill (nouvelle position ou flip)
        if qty > 0:
            book.append([f.side, qty, f.price, f.ts])

    open_lots = sum(len(b) for b in books.values())
    known = [t for t in trades if t.pnl_usd is not None]
    total_usd = round(sum(t.pnl_usd for t in known), 2) if known else 0.0
    r_vals = [t.r_multiple for t in known if t.r_multiple is not None]   # None-safe (risque 0)
    total_r = round(sum(r_vals), 4) if r_vals else 0.0
    summary = {
        "trade_count": len(trades),
        "with_usd": len(known),
        "wins": sum(1 for t in known if t.pnl_usd > 0),
        "losses": sum(1 for t in known if t.pnl_usd < 0),
        "total_pnl_usd": total_usd,
        "total_r": total_r,
        "open_lots": open_lots,
        "unresolved_fills": unresolved,
    }
    return ReconResult(trades=trades, open_lots=open_lots, unresolved_fills=unresolved, summary=summary)


# ---------- chargement depuis l'historique des snapshots ----------

def load_fills_from_snapshots(directory: str) -> list[Fill]:
    """Charge les fills déclencheurs des snapshots JSON de `directory`, triés chronologiquement.
    Ignore les snapshots de CONTEXTE (sans `fill`) et les fichiers illisibles. Fail-closed :
    dossier absent → `[]`. Bloquant → appeler via `asyncio.to_thread`."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    keyed: list[tuple[float, str, Fill]] = []   # (ts, snapshot_id) → clé de tri DÉTERMINISTE
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue                             # illisible / JSON invalide → écarté (§3)
        if not isinstance(data, dict):
            continue                             # JSON valide mais pas un objet (liste/scalaire)
        fill = data.get("fill")
        if not isinstance(fill, dict):
            continue                             # snapshot de contexte (pas de fill) ou fill malformé
        instrument = fill.get("instrument")
        price = fill.get("price")
        ts = fill.get("ts", data.get("created_ts"))
        if instrument is None or price is None or ts is None:
            continue
        quantity = fill.get("quantity")
        try:                                     # valeurs non numériques → écartées, jamais un crash
            f_obj = Fill(instrument=str(instrument), side=fill.get("side"), price=float(price),
                         quantity=int(quantity) if quantity is not None else 0, ts=float(ts))
        except (ValueError, TypeError):
            continue
        keyed.append((f_obj.ts, str(data.get("snapshot_id") or name), f_obj))
    keyed.sort(key=lambda k: (k[0], k[1]))       # (ts, id) → ordre stable indépendant du FS
    return [k[2] for k in keyed]


def analyze_trades(directory: str) -> dict:
    """Charge l'historique + réconcilie → payload pour `GET /analyses/trades`. Déterministe."""
    fills = load_fills_from_snapshots(directory)
    res = reconcile_fills(fills)
    return {
        "trades": [t.model_dump() for t in res.trades],
        "summary": res.summary,
        "fills_loaded": len(fills),
        "reference_risk_usd": REFERENCE_RISK_USD,
        "contracts": POINT_VALUE,
    }
