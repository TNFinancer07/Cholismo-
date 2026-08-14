"""Vecteur de features à l'armement — le matériau du futur modèle (D-108).

**Ce module n'entraîne rien et ne prédit rien.** Il enregistre, à l'instant de l'armement, l'état
qui a produit le setup. Le jour où 50 trades réconciliés existeront, un modèle pourra s'entraîner
dessus ; d'ici là, chaque séance passée sans ce journal est une séance de données **définitivement
perdues** — c'est la seule raison de le construire maintenant.

---

**Absent n'est pas zéro.** La règle qui décide de la valeur du jeu entier. Un vecteur où `cvd: 0`
peut signifier « CVD mesuré à zéro » ou « CVD indisponible » produirait un modèle entraîné sur des
zéros fictifs — il apprendrait que l'absence de mesure prédit quelque chose.

Chaque champ absent vaut donc `None`, **et** son nom entre dans `missing`. Un consommateur peut
ainsi écarter les vecteurs incomplets, ou traiter l'absence comme une modalité — mais jamais la
confondre avec une mesure.

**Les valeurs sont celles que le MOTEUR a réellement calculées** (arbitrage D-107) : le TP est
dynamique, ancré au VPOC et calibré par instrument (D-069). On enregistre `tp_target_ticks` tel
qu'il sort, jamais une valeur théorique — un vecteur qui décrirait un moteur imaginaire
n'entraînerait rien d'utile.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

MTL = ZoneInfo("America/Montreal")


def _num(value: Any) -> Optional[float]:
    """`None` sur tout ce qui n'est pas un nombre fini. Un `NaN` journalisé se propagerait
    silencieusement dans un entraînement."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _dig(root: Any, *path: str) -> Any:
    """Descend une arborescence de dicts. `None` dès qu'un maillon manque — sans lever, parce
    qu'un champ absent du schéma est une information, pas une panne."""
    cur = root
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _meta_value(root: Any, *path: str) -> Any:
    """Valeur d'un `MetaField` — **uniquement si elle est FRESH**.

    Une valeur périmée est pire qu'absente dans un jeu d'entraînement : elle a l'air d'une mesure
    et décrit un autre instant. On la traite donc comme manquante.
    """
    node = _dig(root, *path)
    if not isinstance(node, dict):
        return None
    if node.get("freshness") not in ("FRESH", None):
        return None
    return node.get("value")


def _ticks(a: Any, b: Any, tick_size: float) -> Optional[float]:
    """Distance en ticks entre deux prix. `None` si l'un manque ou si le tick est absurde."""
    x, y = _num(a), _num(b)
    if x is None or y is None or tick_size <= 0:
        return None
    return round(abs(x - y) / tick_size, 2)


def build_feature_vector(*, setup: Any, schema: Any, now_ms: float,
                         tick_size: float = 0.25) -> dict[str, Any]:
    """Vecteur `[géométrie réelle + microstructure + contexte + heure]` à l'armement.

    Ne lève jamais : un vecteur partiel avec ses absences déclarées vaut mieux qu'une exception
    dans la boucle d'armement (mode G2 — rien ne bloque).
    """
    # `setup` est le manifeste DÉJÀ parsé par `_read_manifest` — on ne re-parse pas une seconde
    # fois : deux lectures du même manifeste finiraient par diverger (leçon D-069).
    setup = setup if isinstance(setup, dict) else {}

    entry = _num(setup.get("entry_price"))
    stop = _num(setup.get("stop_loss"))
    target = _num(setup.get("target_price"))
    vpoc = _num(_meta_value(schema, "s1_state", "structure", "vpoc"))

    tp_ticks = _ticks(target, entry, tick_size)
    sl_ticks = _ticks(stop, entry, tick_size)

    features: dict[str, Any] = {
        # -- géométrie RÉELLE du moteur (D-107) : dynamique, jamais une valeur théorique --
        "instrument": setup.get("instrument") or None,
        "direction": setup.get("side") or None,
        "entry_price": entry,
        "tp_target_ticks": tp_ticks,
        "stop_loss_ticks": sl_ticks,
        # Rapport gain/risque tel qu'il sort du moteur — la grandeur qui rend deux instruments
        # comparables malgré des ticks et des calibrations différents.
        "rr_ratio": (round(tp_ticks / sl_ticks, 3)
                     if tp_ticks is not None and sl_ticks and sl_ticks > 0 else None),
        "distance_to_vpoc_ticks": _ticks(vpoc, entry, tick_size),
        "contracts": _num(setup.get("position_size")),

        # -- microstructure --
        "svs_score": _num(_meta_value(schema, "s1_state", "svs_score")),
        "cvd": _num(_meta_value(schema, "s1_state", "cvd")),
        "aggressor_ratio": _num(_meta_value(schema, "s1_state", "order_flow", "aggressor_ratio")),
        "chop": _num(_meta_value(schema, "s1_state", "chop")),
        "vpoc": vpoc,

        # -- contexte --
        "vix": _num(_meta_value(schema, "bridge_variables", "vix")),
        "news_state": _dig(schema, "session_identity", "news_state") or None,
        "sweep_direction": _dig(schema, "liquidity_sweep", "alert", "direction") or None,
        "session": _dig(schema, "session_identity", "session_marker") or None,

        # -- heure, dans le fuseau de l'opérateur (même convention que le reste du dépôt) --
        "hour_local": None,
        "minute_local": None,
    }

    absorption = _meta_value(schema, "s1_state", "order_flow", "absorption")
    features["absorption"] = absorption if isinstance(absorption, bool) else None

    try:
        local = datetime.fromtimestamp(now_ms / 1000.0, tz=MTL)
        features["hour_local"] = local.hour
        features["minute_local"] = local.minute
    except (TypeError, ValueError, OSError, OverflowError):
        pass

    # `missing` est la moitié utile du vecteur : sans lui, un `None` sérialisé en JSON puis relu
    # redevient indiscernable d'une valeur non renseignée par le producteur.
    missing = sorted(k for k, v in features.items() if v is None)
    return {"features": features, "missing": missing,
            "complete": not missing, "tick_size": tick_size, "ts_ms": now_ms}
