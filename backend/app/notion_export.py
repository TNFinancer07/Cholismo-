"""Export du journal des setups vers Notion — la PROJECTION, sans réseau (D-118).

Ce module ne parle à personne : il transforme une entrée de journal en propriétés Notion. Le
réseau vit dans `workers/notion_exporter.py`, autonome, hors du moteur. Les séparer permet de
tester la seule chose qui puisse être fausse ici — le mappage.

---

**OPT-IN strict.** Sans `NOTION_API_KEY` **et** `NOTION_DATABASE_ID`, rien ne part. Un export qui
s'activerait tout seul enverrait des données de trading vers un service tiers sans que personne
l'ait demandé.

**Absent ne devient pas zéro — ici encore.** Une propriété `number` à `0` dans Notion serait
indiscernable d'une mesure nulle, et corromprait le même jeu que D-108 protège en amont. Un champ
absent est **omis** de la ligne, et la colonne `Non mesuré` dit lequel.

**Rien n'est recalculé.** On mappe ce que le journal contient. Recalculer ici produirait une
seconde vérité, différente de celle sur laquelle le modèle s'entraînera.
"""
from __future__ import annotations

from typing import Any, Optional

#: Colonnes attendues côté Notion. Écrites ici pour qu'une base mal configurée se voie dans un
#: message clair plutôt que dans une erreur d'API illisible.
COLUMNS = ("Setup", "Horodatage", "Instrument", "Direction", "TP (ticks)", "Stop (ticks)",
           "R:R", "Distance VPOC", "OF1", "OF2", "OF3", "OF4", "Verrou", "Vide de liquidité",
           "Non mesuré")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _number(v: Any) -> Optional[dict]:
    """Propriété `number`, ou `None` pour l'omettre. **Jamais `{"number": 0}` par défaut.**"""
    n = _num(v)
    return None if n is None else {"number": n}


def _text(v: Any) -> Optional[dict]:
    if v is None or v == "":
        return None
    return {"rich_text": [{"text": {"content": str(v)[:2000]}}]}


def _title(v: Any) -> dict:
    return {"title": [{"text": {"content": str(v or "sans identifiant")[:2000]}}]}


def _select(v: Any) -> Optional[dict]:
    return None if v in (None, "") else {"select": {"name": str(v)[:100]}}


def _gate(gates: Any, code: str) -> Optional[str]:
    """Verdict lisible d'une gate : `franchie` / `refusée` / rien.

    `None` **omet** la propriété : « non mesurable » n'est pas « refusée », et l'écrire ainsi
    ferait apprendre au modèle qu'une absence de mesure prédit un refus.
    """
    if not isinstance(gates, dict):
        return None
    v = gates.get(code)
    if isinstance(v, dict):
        v = v.get("verdict_inhouse")
    if v is True:
        return "franchie"
    if v is False:
        return "refusée"
    return None


def to_notion_properties(entry: Any) -> Optional[dict[str, Any]]:
    """Une entrée `setup_armed` → propriétés Notion. `None` si l'entrée est inexploitable.

    Ne lève jamais : un export est un confort, il ne doit pas pouvoir casser la boucle qui
    l'appelle.
    """
    if not isinstance(entry, dict):
        return None
    setup_id = entry.get("setup_id")
    if not setup_id:
        return None                       # sans identifiant, la ligne serait irrattachable

    vecteur = entry.get("feature_vector") if isinstance(entry.get("feature_vector"), dict) else {}
    f = vecteur.get("features") if isinstance(vecteur.get("features"), dict) else {}
    manquants = vecteur.get("missing") if isinstance(vecteur.get("missing"), list) else []
    gates = entry.get("gates")

    brut: dict[str, Any] = {
        "Setup": _title(setup_id),
        "Horodatage": _number(entry.get("ts_ms")),
        "Instrument": _select(f.get("instrument") or entry.get("instrument")),
        "Direction": _select(f.get("direction") or entry.get("side")),
        "TP (ticks)": _number(f.get("tp_target_ticks")),
        "Stop (ticks)": _number(f.get("stop_loss_ticks")),
        "R:R": _number(f.get("rr_ratio")),
        "Distance VPOC": _number(f.get("distance_to_vpoc_ticks")),
        "OF1": _select(_gate(gates, "b1")),
        "OF2": _select(_gate(gates, "b2")),
        "OF3": _number(f.get("cvd")),
        "OF4": _number(f.get("aggressor_ratio")),
        "Verrou": _select(entry.get("lock_reason")),
        "Vide de liquidité": _select(entry.get("vacuum")),
        # La moitié utile : une ligne qui ne dirait pas ce qui manque laisserait croire à un
        # relevé complet.
        "Non mesuré": _text(", ".join(str(m) for m in manquants) if manquants else None),
    }
    # Omission plutôt que valeur nulle — c'est la règle qui donne sa valeur au jeu.
    return {k: v for k, v in brut.items() if v is not None}


def is_configured(api_key: Any, database_id: Any) -> bool:
    """Opt-in strict : les DEUX doivent être présents. Une clé sans base (ou l'inverse) est une
    configuration à moitié faite — l'exporteur se tait plutôt que d'échouer à chaque tentative."""
    return bool(api_key and str(api_key).strip()) and bool(database_id and str(database_id).strip())


def already_exported(setup_id: Any, exported: Any) -> bool:
    """Anti-doublon. Le journal est append-only et relu en entier à chaque passe : sans cette
    garde, chaque redémarrage recréerait toutes les lignes déjà envoyées."""
    if not setup_id:
        return True                       # rien à exporter, donc « déjà fait »
    try:
        return str(setup_id) in set(exported or ())
    except TypeError:
        return False
