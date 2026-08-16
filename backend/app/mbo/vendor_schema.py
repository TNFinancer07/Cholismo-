"""Normalisation des exports fournisseur → schéma MBO interne (D-121).

    rows, rapport = normalize_order_flow_schema(rows, source_type="auto")

`ingest_parquet` lit un export **Databento GLBX.MDP3** et rien d'autre : `REQUIRED_COLUMNS` y est
fatal au fichier, pas à la ligne. Un export Tradovate ou Rithmic ne porte ni les mêmes noms de
colonnes, ni le même vocabulaire d'actions, ni la même échelle de prix. Ce module fait la
traduction — **et rien d'autre** : il ne lit aucun fichier, ne valide aucune règle métier, ne
décide d'aucun armement.

---

⚠️ **CE QUI EST VÉRIFIÉ, ET CE QUI NE L'EST PAS.** Le mappage Databento est vérifié : il est lu
depuis `ingest.py`, qui fait autorité. Les mappages **Tradovate et Rithmic viennent de la
documentation publique et n'ont été confrontés à AUCUN export réel** — exactement le statut du
codec Tradovate (D-100). Ce sont des `PLACEHOLDER` : la cohérence interne et le fail-closed sont
garantis, la conformité au format ne l'est pas. Le premier export réel les corrigera, et c'est
pour ça que chaque table est isolée et nommée.

**Quatre refus structurent ce module**, et ce sont eux qui le rendent sûr :

1. **`ts_event` reste un ENTIER de nanosecondes.** `pd.to_datetime()` produirait un `datetime64`
   que `normalize_row` rejette comme `MISSING_TIMESTAMP` — le fichier entier partirait à la
   poubelle en silence. La conversion depuis une date texte se fait en **arithmétique entière**
   (`_iso_to_ns`) : passer par `timestamp()` en flottant coûterait ~200 ns de précision à
   l'époque actuelle, ce que `events.py` interdit explicitement.

2. **Une valeur non mappée REJETTE la ligne, elle ne devient pas `NaN`.** Un `.map()` pandas rend
   `NaN` sur une clé absente : la ligne survit, paraît complète, et porte un trou. Ici elle est
   écartée **et comptée** avec son motif — doctrine d'`ingest.py` : « aucune ligne écartée sans
   être comptée ».

3. **Une source non reconnue est une ERREUR, pas un passe-plat.** Rendre l'entrée inchangée
   laisserait croire qu'elle était déjà au bon format ; l'ingestion échouerait trois couches plus
   loin sur un message sans rapport. Une détection ambiguë (deux signatures présentes) refuse
   aussi : deviner entre deux fournisseurs, c'est tirer à pile ou face sur le sens des colonnes.

4. **`sequence` synthétisée est ANNONCÉE comme telle.** Ni Tradovate ni Rithmic ne l'exportent, et
   `ingest_parquet` la exige. On la fabrique depuis l'ordre des lignes — mais une séquence
   fabriquée **ne peut pas détecter un trou de capture**, ce que la vraie sait faire. Le rapport
   porte `sequence_synthesised: True` pour que personne ne lise une continuité qui n'a pas été
   observée.

**Pas de pandas dans le chemin d'exécution.** `requirements-dev.txt` le dit : « `to_dataframe`
uniquement — commodité d'exploration, JAMAIS le chemin d'exécution ». Le cœur travaille donc sur
les `list[dict]` que `read_parquet_rows` produit déjà. Un DataFrame passé en entrée est accepté
par commodité (`.to_dict("records")`), sans que pandas entre dans le graphe d'import.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .events import IngestStats, MboAction, MboSide, RejectCode

#: Databento : prix `int64` en fixed-point 1e-9. Repris d'`ingest.py`, qui fait autorité.
PRICE_SCALE = 1_000_000_000

SOURCE_DATABENTO = "databento"
SOURCE_TRADOVATE = "tradovate"
SOURCE_RITHMIC = "rithmic"

#: Colonnes du schéma interne, dans l'ordre où `ingest.py` les exige.
TARGET_COLUMNS = ("ts_event", "action", "side", "price", "size", "order_id", "sequence")

#: Signature de détection : colonnes qui, ENSEMBLE, n'appartiennent qu'à ce fournisseur. Une
#: signature d'une seule colonne ferait des faux positifs (`price` existe partout).
SIGNATURES: dict[str, frozenset[str]] = {
    SOURCE_DATABENTO: frozenset({"ts_event", "order_id"}),
    SOURCE_TRADOVATE: frozenset({"timestamp", "orderId"}),
    SOURCE_RITHMIC: frozenset({"Date Time", "Order ID"}),
}

#: Renommage vers le schéma interne. PLACEHOLDER pour Tradovate et Rithmic (voir docstring).
RENAME: dict[str, dict[str, str]] = {
    SOURCE_TRADOVATE: {"timestamp": "ts_event", "orderId": "order_id", "action": "action",
                       "side": "side", "price": "price", "qty": "size"},
    SOURCE_RITHMIC: {"Date Time": "ts_event", "Order ID": "order_id", "Type": "action",
                     "BS": "side", "Price": "price", "Volume": "size"},
}

#: Vocabulaire des côtés. Le brouillon d'origine oubliait `MboSide.NONE` : un `TRADE` sans côté
#: attribué est légitime dans un flux MBO, et le rejeter jetterait des impressions réelles.
SIDES: dict[str, dict[str, str]] = {
    SOURCE_TRADOVATE: {"Buy": MboSide.BID, "Sell": MboSide.ASK, "B": MboSide.BID,
                       "A": MboSide.ASK, "None": MboSide.NONE, "": MboSide.NONE},
    SOURCE_RITHMIC: {"B": MboSide.BID, "BUY": MboSide.BID, "S": MboSide.ASK,
                     "SELL": MboSide.ASK, "N": MboSide.NONE, "": MboSide.NONE},
}

#: Vocabulaire des actions. Le brouillon n'en avait AUCUN : les actions passaient telles quelles,
#: et `normalize_row` aurait rejeté chaque ligne en `UNKNOWN_ACTION`. C'est le défaut qui aurait
#: vidé un fichier entier sans qu'aucune exception ne soit levée.
ACTIONS: dict[str, dict[str, str]] = {
    SOURCE_TRADOVATE: {"Add": MboAction.ADD, "Cancel": MboAction.CANCEL,
                       "Modify": MboAction.MODIFY, "Trade": MboAction.TRADE,
                       "Fill": MboAction.FILL, "Clear": MboAction.CLEAR},
    SOURCE_RITHMIC: {"A": MboAction.ADD, "C": MboAction.CANCEL, "M": MboAction.MODIFY,
                     "T": MboAction.TRADE, "F": MboAction.FILL, "R": MboAction.CLEAR,
                     "ADD": MboAction.ADD, "CANCEL": MboAction.CANCEL,
                     "MODIFY": MboAction.MODIFY, "TRADE": MboAction.TRADE},
}

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class VendorSchemaError(Exception):
    """Export inexploitable : source indétectable, ambiguë, ou colonne requise absente. Distinct
    d'une LIGNE rejetée — on ne devine pas un format, on refuse."""


def _rows_of(data: Any) -> list[dict[str, Any]]:
    """Accepte une liste de dicts ou un DataFrame. Le second est converti sans que pandas soit
    importé ici : c'est l'objet lui-même qui sait se rendre en enregistrements."""
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict) and not isinstance(data, dict):
        try:
            records = to_dict("records")
        except TypeError:
            records = None
        if isinstance(records, list):
            return [dict(r) for r in records]
    if isinstance(data, list):
        return [dict(r) for r in data if isinstance(r, dict)]
    raise VendorSchemaError("entrée illisible : ni liste d'enregistrements, ni DataFrame")


def _iso_to_ns(value: Any) -> Optional[int]:
    """Date texte → nanosecondes entières UTC. **Arithmétique entière de bout en bout** : passer
    par `datetime.timestamp()` coûterait ~200 ns de précision à l'époque actuelle (mantisse de
    53 bits), ce que `events.py` interdit — c'est le bug `bigint` que le port a justement évité.

    Une date SANS fuseau est refusée : la lire comme UTC décalerait toute une séance de plusieurs
    heures, et le décalage serait invisible dans des horodatages d'allure parfaitement normale."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    delta = parsed.astimezone(timezone.utc) - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000_000_000) + delta.microseconds * 1_000


def _to_ns(value: Any) -> Optional[int]:
    """`ts_event` interne = entier de nanosecondes. Un entier passe tel quel ; un texte ISO est
    converti ; **un flottant est refusé** — il ne porte pas la nanoseconde, et l'accepter
    réintroduirait le collapsus d'ordre que `events.py` verrouille par test."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return _iso_to_ns(value)


def _to_fixed_price(value: Any, scale: int) -> Optional[int]:
    """Prix décimal fournisseur → fixed-point 1e-9. `ingest.py` divise par `PRICE_SCALE` : livrer
    un prix décimal brut donnerait 5012.25 / 1e9 ≈ 5e-6, un prix d'allure minuscule mais
    parfaitement fini — donc accepté sans rejet, et faux partout en aval.

    Un entier déjà mis à l'échelle par le fournisseur passerait ici pour un prix décimal ; c'est
    pourquoi la mise à l'échelle n'est appliquée qu'aux sources NON-Databento."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if as_float != as_float or as_float in (float("inf"), float("-inf")):
        return None
    return int(round(as_float * scale))


def detect_source(columns: Any) -> str:
    """Source déduite des colonnes présentes. **Refuse plutôt que de deviner** : zéro signature
    reconnue ou deux signatures simultanées lèvent. Un export à moitié renommé à la main tombe
    dans le second cas, et c'est voulu — c'est là qu'un passe-plat ferait le plus de dégâts."""
    present = frozenset(columns or ())
    matches = [name for name, sig in SIGNATURES.items() if sig <= present]
    if not matches:
        raise VendorSchemaError(
            "source indétectable : aucune signature connue dans "
            f"{sorted(present)[:8]} — préciser source_type explicitement")
    if len(matches) > 1:
        raise VendorSchemaError(
            f"source ambiguë : {', '.join(sorted(matches))} correspondent tous les deux — "
            "préciser source_type plutôt que de laisser deviner")
    return matches[0]


def normalize_order_flow_schema(data: Any, source_type: str = "auto", *,
                                price_scale: int = PRICE_SCALE,
                                stats: Optional[IngestStats] = None,
                                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Harmonise un export Databento / Tradovate / Rithmic vers le schéma MBO interne.

    Rend `(lignes, rapport)`. Le rapport n'est pas un supplément : il porte la source retenue, le
    nombre de lignes écartées **par motif**, et si `sequence` a été fabriquée. Une normalisation
    silencieuse qui rend 40 % des lignes serait le pire résultat possible.

    Databento est rendu **inchangé** : il EST le schéma interne. Le renommer serait un aller-retour
    qui ne peut que perdre.
    """
    rows = _rows_of(data)
    columns = list(rows[0].keys()) if rows else []
    source = detect_source(columns) if source_type == "auto" else str(source_type).lower()
    if source not in SIGNATURES:
        raise VendorSchemaError(
            f"source « {source} » inconnue — attendu : {', '.join(sorted(SIGNATURES))}")

    counters = stats if stats is not None else IngestStats()
    rapport: dict[str, Any] = {"source": source, "rows_in": len(rows), "rows_out": 0,
                               "sequence_synthesised": False, "rejected_by_reason": {}}

    if source == SOURCE_DATABENTO:
        rapport["rows_out"] = len(rows)
        return rows, rapport

    rename, sides, actions = RENAME[source], SIDES[source], ACTIONS[source]
    missing = [src for src, dst in rename.items() if dst in TARGET_COLUMNS and src not in columns]
    if missing and rows:
        # Fatal au FICHIER, comme dans `ingest.py` : on ne devine pas une colonne absente.
        raise VendorSchemaError(f"colonnes {source} absentes : {', '.join(sorted(missing))}")

    out: list[dict[str, Any]] = []
    synthesised = False
    for index, row in enumerate(rows):
        renamed = {rename.get(key, key): value for key, value in row.items()}

        ts = _to_ns(renamed.get("ts_event"))
        if ts is None:
            counters.reject(RejectCode.MISSING_TIMESTAMP)
            continue

        action = actions.get(str(renamed.get("action", "")).strip())
        if action is None:
            counters.reject(RejectCode.UNKNOWN_ACTION)
            continue

        side = sides.get(str(renamed.get("side", "")).strip())
        if side is None:
            counters.reject(RejectCode.UNKNOWN_SIDE)
            continue

        price = _to_fixed_price(renamed.get("price"), price_scale)
        if price is None:
            counters.reject(RejectCode.NON_FINITE_PRICE)
            continue

        if "sequence" not in renamed or renamed.get("sequence") is None:
            renamed["sequence"] = index          # fabriquée — voir §4 de la docstring du module
            synthesised = True

        renamed.update({"ts_event": ts, "action": action, "side": side, "price": price})
        out.append(renamed)

    rapport.update({"rows_out": len(out), "sequence_synthesised": synthesised,
                    "rejected_by_reason": dict(counters.rejections_by_reason)})
    return out, rapport
