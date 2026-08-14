"""Tradovate — codec et projection, côté LECTURE seule (D-100).

La plateforme du challenge est Tradovate. Son API sert deux besoins du terminal :
le **flux de marché** (quotes + DOM) et les **exécutions réelles** (fills), ces dernières
alimentant la réconciliation automatique du Decision Log (D-098).

---

**⛔ Aucune fonction de passage d'ordre n'existe dans ce module, et c'est structurel.**

`CLAUDE §2.1` : « Aucune exécution automatique d'ordre. » L'API Tradovate sait placer des ordres —
c'est précisément pourquoi ce fichier doit être borné explicitement plutôt que « simplement pas
encore écrit ». Un test de garde relit cette source et échoue si un endpoint d'exécution y
apparaît. Le terminal OBSERVE un fill après coup ; il ne le provoque jamais.

---

**Ce que ce module contient, et ce qu'il ne contient pas.**

Il contient le **codec** du protocole WebSocket de Tradovate et la **projection** de ses messages
vers les structures du terminal. C'est pur, déterministe, et entièrement testable hors ligne.

Il ne contient PAS le transport (ouverture de socket, boucle de heartbeat, renouvellement de
jeton). Ce dernier ne peut être ni exécuté ni vérifié ici — pas d'identifiants, pas d'accès au
service. L'écrire « au jugé » produirait du code d'apparence fonctionnelle que personne n'a vu
tourner, c'est-à-dire le contraire d'un connecteur.

⚠️ **Les libellés d'endpoints et la forme des trames ci-dessous sont issus de la documentation
publique de Tradovate et n'ont été confrontés à AUCUN service réel.** Ils sont à revérifier
contre la doc officielle avant le premier branchement. Ce qui est garanti ici, c'est la
cohérence interne et le comportement fail-closed, pas la conformité au protocole.
"""
from __future__ import annotations

import json
from typing import Any, Optional

#: Trames du protocole (dérivé de SockJS) : ouverture, heartbeat, tableau de messages, fermeture.
FRAME_OPEN, FRAME_HEARTBEAT, FRAME_ARRAY, FRAME_CLOSE = "o", "h", "a", "c"

#: Endpoints de LECTURE uniquement. Toute entrée ajoutée ici doit être une lecture — le test de
#: garde relit ce module et refuse le vocabulaire d'exécution.
MD_SUBSCRIBE_QUOTE = "md/subscribequote"
MD_SUBSCRIBE_DOM = "md/subscribedom"
USER_SYNC = "user/syncrequest"


def encode_request(endpoint: str, request_id: int, body: Optional[dict] = None,
                   query: str = "") -> str:
    """Trame de requête : `endpoint\\nid\\nquery\\nbody`.

    Le corps est omis s'il est absent — envoyer `null` là où le service attend du vide est le
    genre de détail qui fait échouer une session entière sans message clair.
    """
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return f"{endpoint}\n{request_id}\n{query}\n{payload}"


def decode_frame(raw: Any) -> tuple[str, list[dict]]:
    """Rend `(type_de_trame, messages)`. Ne lève jamais.

    Une trame illisible rend `("", [])` — traitée comme « rien reçu », donc les champs
    vieillissent visiblement (§3). L'alternative, deviner le contenu, fabriquerait de la donnée
    de marché à partir d'un octet corrompu.
    """
    if not isinstance(raw, str) or not raw:
        return "", []
    kind = raw[0]
    if kind in (FRAME_OPEN, FRAME_HEARTBEAT, FRAME_CLOSE):
        return kind, []
    if kind != FRAME_ARRAY:
        return "", []
    try:
        parsed = json.loads(raw[1:])
    except (ValueError, TypeError):
        return "", []
    if not isinstance(parsed, list):
        return "", []
    return FRAME_ARRAY, [m for m in parsed if isinstance(m, dict)]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def prints_from_quote(message: dict) -> list[dict]:
    """Projette un message de quote vers des prints du terminal.

    **Seul un TRADE devient un print.** Une mise à jour de bid/ask n'est pas une transaction :
    la compter gonflerait le tape et fausserait CVD, ratio d'agression et vitesse — toutes les
    mesures qui en dérivent. Un `price` ou une `size` absents écartent l'entrée plutôt que de la
    combler.
    """
    out: list[dict] = []
    for entry in _entities(message, "quote"):
        trade = entry.get("trade") if isinstance(entry.get("trade"), dict) else None
        if trade is None:
            continue
        price, size = _num(trade.get("price")), _num(trade.get("size"))
        ts = _timestamp(entry.get("timestamp") or trade.get("timestamp"))
        if price is None or size is None or ts is None:
            continue
        out.append({"ts": ts, "price": price, "size": size, "side": _side(trade.get("side"))})
    return out


def book_from_dom(message: dict) -> Optional[dict]:
    """Projette un message DOM vers `{bids, asks}` — `None` si rien d'exploitable.

    `None` plutôt qu'un carnet vide : zéro niveau se lirait « plus aucune liquidité », ce qui est
    une mesure, et elle serait fausse.
    """
    for entry in _entities(message, "dom"):
        bids = _levels(entry.get("bids"))
        asks = _levels(entry.get("offers") if entry.get("offers") is not None else entry.get("asks"))
        if bids or asks:
            return {"bids": bids, "asks": asks}
    return None


def fills_from_sync(message: dict) -> list[dict]:
    """Projette les exécutions d'un message de synchronisation vers la forme attendue par
    `reconcile_entry_fill` (D-098) : `{instrument, side, price, quantity, ts}`.

    C'est le chemin qui supprime l'import CSV manuel — un fill réel devient un `ReconEvent`
    d'entrée rattaché à sa décision, sans qu'aucun ordre n'ait été passé par le terminal.
    """
    out: list[dict] = []
    for f in _entities(message, "fill"):
        price, qty = _num(f.get("price")), _num(f.get("qty"))
        ts = _timestamp(f.get("timestamp"))
        if price is None or qty is None or ts is None:
            continue
        out.append({
            "instrument": str(f.get("contractName") or f.get("symbol") or "").strip(),
            "side": _side(f.get("action") or f.get("side")),
            "price": price, "quantity": qty, "ts": ts,
        })
    return out


# -- internes --

def _entities(message: dict, name: str) -> list[dict]:
    """Les messages portent soit `{e: 'md', d: {quotes: [...]}}`, soit `{<name>s: [...]}` selon
    le canal. On accepte les deux formes plutôt que d'en supposer une : se tromper ici rendrait
    un flux entier silencieux, et le silence est indiscernable d'un marché calme."""
    if not isinstance(message, dict):
        return []
    for holder in (message.get("d") if isinstance(message.get("d"), dict) else None, message):
        if not isinstance(holder, dict):
            continue
        for key in (f"{name}s", name):
            v = holder.get(key)
            if isinstance(v, list):
                return [e for e in v if isinstance(e, dict)]
            if isinstance(v, dict):
                return [v]
    return []


def _levels(raw: Any) -> list[list[float]]:
    out: list[list[float]] = []
    if not isinstance(raw, list):
        return out
    for lvl in raw:
        if not isinstance(lvl, dict):
            continue
        price, size = _num(lvl.get("price")), _num(lvl.get("size"))
        if price is None or size is None:
            continue
        out.append([price, size])
    return out


def _side(raw: Any) -> Optional[str]:
    """`Buy`/`Sell` → `BUY`/`SELL`. Inconnu → `None`, jamais un côté par défaut : un côté deviné
    inverse le signe du CVD."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    return s if s in ("BUY", "SELL") else None


def _timestamp(raw: Any) -> Optional[float]:
    """Tradovate horodate en ISO-8601 UTC. Rend des SECONDES epoch — l'unité du reste du dépôt.

    Un horodatage illisible rend `None` et l'entrée est écartée : dater un print de « maintenant »
    parce qu'on n'a pas su lire le sien fabriquerait de la fraîcheur.
    """
    if isinstance(raw, (int, float)):
        v = _num(raw)
        if v is None:
            return None
        return v / 1000.0 if v > 1e11 else v      # ms vs s, par magnitude
    if not isinstance(raw, str) or not raw.strip():
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
