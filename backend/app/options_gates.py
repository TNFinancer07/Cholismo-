"""Balises O1-O4 + assemblage O1-O5 à l'armement (D-076).

Port Python de `reference/v2/fast-engine/gatesO1toO4.ts` et `decisionLog.ts`, sous verrou de
parité (D-072 : le test LIT le TypeScript et échoue si les deux côtés divergent).

**MODE G2 — GARANTIE STRUCTURELLE, PAS UNE CONFIGURATION.** Chaque évaluateur retourne un objet
de statut. Aucun ne retourne de booléen, aucun ne lève. Il n'existe nulle part ici un motif
`if not gate: block()` désactivé qu'un refactor pourrait réactiver par accident — il n'y a
simplement **aucun chemin de blocage**. L'entrée de journal n'a ni champ `blocked` ni `allowed` :
elle existe pour remplir le journal, pas pour être testée par un `if`. La chaîne fail-fast
déterministe conserve exactement ses contrôles bloquants ; O1-O5 n'en fait pas partie (§2.1).

**Deux divergences délibérées avec le TS**, chacune dans le sens fail-closed :
1. **GEX non fini** → `O1_DATA_UNAVAILABLE`. Le TS ferait `Math.abs(NaN) <= seuil` → faux, puis
   `NaN > 0` → faux, et conclurait au régime négatif : un `FLAG_STRONG` porteur d'un `NaN`.
   Ce n'est pas du JSON valide, et §3 exige un refus explicite plutôt qu'une mesure inventée.
   Un strike **ou** une valeur non finie est écarté du choix du plus proche.
2. **Horodatage du futur**, déjà tranché en D-075 dans `options_context`.
Toute autre divergence est un bug, pas un choix.

**Unités.** `now_ms` est en **millisecondes** — le `netDriftCrossover.ts` du worker l'est aussi,
et convertir au milieu du gate serait le meilleur moyen de comparer des secondes à des
millisecondes sans que rien ne le signale. Le reste du backend est en secondes : la conversion
est la responsabilité de l'appelant, explicitement.

Tous les seuils sont `PLACEHOLDER` : aucun n'a été validé sur données.
"""
from __future__ import annotations

import math
import pathlib
from typing import Any, Optional

from .o5_tail_risk import O5_CONFIG_PLACEHOLDER, evaluate_o5
from .options_context import ContextHealth, OptionsContextSnapshot

TICK_ES = 0.25

#: Seuil de significativité du GEX local — en dessous, le régime est du bruit, pas un signal.
O1_SIGNIFICANCE_THRESHOLD = 30      # M$/1%, PLACEHOLDER
#: ≈ 1,2× le stop LSR de 10 ticks. PLACEHOLDER, non calibré.
O2_EXCLUSION_TICKS = 12
#: Marge pour l'incertitude de conversion SPX→ES. PLACEHOLDER.
O3_TOLERANCE_TICKS = 1
#: Fenêtre de fraîcheur du croisement, alignée sur F7 (anti-FOMO, 90 s). PLACEHOLDER.
O4_WINDOW_MS = 90_000
#: Tolérance de coïncidence de lieu avec le niveau GEX pertinent. PLACEHOLDER.
O4_LOCATION_TOLERANCE_TICKS = 4

#: Miroirs exacts des unions de statuts TS (verrouillés par test).
STATUSES: dict[str, tuple[str, ...]] = {
    "O1": ("PASS", "FLAG_WEAK", "FLAG_STRONG", "O1_REGIME_INDETERMINE", "O1_DATA_UNAVAILABLE"),
    "O2": ("PASS", "FLAG_EXCLUSION_ZONE", "O2_FLIP_UNKNOWN"),
    "O3": ("PASS", "FLAG_OBSTACLE", "O3_WALLS_UNKNOWN"),
    "O4": ("PASS", "O4_NO_CONVICTION", "O4_NO_LOCATION", "O4_DATA_MISSING",
           "O4_SOURCE_UNCONFIRMED"),
}

_REFERENCE_DIR = pathlib.Path(__file__).resolve().parents[2] / "reference" / "v2" / "fast-engine"


def ts_reference_source(name: str) -> str:
    """Source TS de référence, lue depuis `/reference/v2/fast-engine/` (marquée `AUTORITÉ` au
    MANIFEST). Elle vit là et non dans `lsr-engine/` parce qu'elle appartient au Fast Engine
    v1.7 — un autre paquet, d'autres dépendances. Ce dépôt ne l'exécute pas, il la porte."""
    path = _REFERENCE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"source TS de référence introuvable : {path}")
    return path.read_text(encoding="utf-8")


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _usable(snapshot: OptionsContextSnapshot) -> Optional[dict[str, Any]]:
    """Le contexte n'est exploitable qu'en santé `OK`. `STALE` et `VENDOR_DOWN` sont des données
    fraîches qui disent « je n'ai pas de donnée » : les traiter comme utilisables ferait passer
    des murs absents pour des murs mesurés."""
    if snapshot.health is not ContextHealth.OK or snapshot.raw is None:
        return None
    return snapshot.raw


# ---------------------------------------------------------------------------
# O1 — régime gamma local, SIGNÉ par le côté du trade
# ---------------------------------------------------------------------------

def _nearest_strike_gex(strikes: Any, level: float) -> Optional[tuple[float, float]]:
    """Le strike le plus proche PORTEUR d'une valeur utilisable. Écarter aussi les valeurs non
    finies (et pas seulement les strikes) évite de désigner « le plus proche » puis de n'avoir
    rien à en lire — voir divergence 1."""
    if not isinstance(strikes, dict):
        return None
    best: Optional[tuple[float, float]] = None
    best_dist = math.inf
    for key, value in strikes.items():
        try:
            strike = float(key)
        except (TypeError, ValueError):
            continue
        if not _finite(strike) or not _finite(value):
            continue
        dist = abs(strike - level)
        if dist < best_dist:
            best_dist = dist
            best = (strike, float(value))
    return best


def evaluate_o1(snapshot: OptionsContextSnapshot, level: float, side: str) -> dict[str, Any]:
    """Régime gamma au niveau visé. L'asymétrie par côté est établie dans le Pont v2 : un LONG
    en régime négatif est la plus défavorable des quatre combinaisons."""
    raw = _usable(snapshot)
    if raw is None:
        return {"gate": "O1", "status": "O1_DATA_UNAVAILABLE", "gex_local": None,
                "nearest_strike": None}
    nearest = _nearest_strike_gex(raw.get("gexLocalByStrike"), level)
    if nearest is None:
        return {"gate": "O1", "status": "O1_DATA_UNAVAILABLE", "gex_local": None,
                "nearest_strike": None}
    strike, gex = nearest
    if abs(gex) <= O1_SIGNIFICANCE_THRESHOLD:
        status = "O1_REGIME_INDETERMINE"
    elif gex > 0:
        status = "PASS"
    else:
        status = "FLAG_STRONG" if side == "LONG" else "FLAG_WEAK"
    return {"gate": "O1", "status": status, "gex_local": gex, "nearest_strike": strike}


# ---------------------------------------------------------------------------
# O2 — zone d'exclusion autour du gamma zero (HVL), symétrique par construction
# ---------------------------------------------------------------------------

def evaluate_o2(snapshot: OptionsContextSnapshot, entry_price: float) -> dict[str, Any]:
    """Ni LONG ni SHORT n'est privilégié près du point où le mécanisme est éteint."""
    raw = _usable(snapshot)
    flip = None if raw is None else raw.get("gammaZeroEs")
    if raw is None or not _finite(flip) or not _finite(entry_price):
        return {"gate": "O2", "status": "O2_FLIP_UNKNOWN", "distance_ticks": None}
    distance = abs(entry_price - float(flip)) / TICK_ES
    return {"gate": "O2",
            "status": "PASS" if distance >= O2_EXCLUSION_TICKS else "FLAG_EXCLUSION_ZONE",
            "distance_ticks": distance}


# ---------------------------------------------------------------------------
# O3 — obstacle géométrique entre l'entrée et l'objectif
# ---------------------------------------------------------------------------

def _strictly_between(x: float, a: float, b: float, tolerance_ticks: float) -> bool:
    lo = min(a, b) + tolerance_ticks * TICK_ES
    hi = max(a, b) - tolerance_ticks * TICK_ES
    return lo < x < hi


def evaluate_o3(snapshot: OptionsContextSnapshot, entry_price: float, target_price: float,
                side: str) -> dict[str, Any]:
    """LONG : le call wall ne doit pas se trouver entre l'entrée et le TP. SHORT : le put wall.
    Inverser les deux retournerait le gate en silence."""
    raw = _usable(snapshot)
    if raw is None or not _finite(entry_price) or not _finite(target_price):
        return {"gate": "O3", "status": "O3_WALLS_UNKNOWN", "obstacle_level": None}
    wall = raw.get("callWallEs") if side == "LONG" else raw.get("putWallEs")
    if not _finite(wall):
        return {"gate": "O3", "status": "O3_WALLS_UNKNOWN", "obstacle_level": None}
    blocked = _strictly_between(float(wall), entry_price, target_price, O3_TOLERANCE_TICKS)
    return {"gate": "O3", "status": "FLAG_OBSTACLE" if blocked else "PASS",
            "obstacle_level": float(wall) if blocked else None}


# ---------------------------------------------------------------------------
# O4 — Net Premium Drift. INERTE PAR PRÉREQUIS EXTERNE, pas par bug.
# ---------------------------------------------------------------------------

def evaluate_o4(snapshot: OptionsContextSnapshot, side: str, level: float,
                now_ms: float) -> dict[str, Any]:
    """Alignement du Net Premium Drift.

    **Blocage de périmètre documenté** : la source n'est confirmée que sur QQQ, pas SPY/SPX
    (Pont v2 §4 — la capture fournisseur porte le badge « QQQ only »). Tant que
    `sourceConfirmed` est faux — ce qui est systématiquement le cas avec les données disponibles
    aujourd'hui — ce gate retourne `O4_SOURCE_UNCONFIRMED` **avant toute autre logique**.

    La logique d'alignement ci-dessous est prête et volontairement inerte. Ce n'est pas du code
    mort à supprimer : c'est du code qui attend une donnée qui n'existe pas encore.
    """
    raw = _usable(snapshot)
    if raw is None:
        return {"gate": "O4", "status": "O4_DATA_MISSING", "direction": None}
    drift = raw.get("netDriftCrossover") or {}
    if not drift.get("sourceConfirmed", False):
        return {"gate": "O4", "status": "O4_SOURCE_UNCONFIRMED", "direction": None}

    direction, ts = drift.get("direction"), drift.get("ts")
    if direction is None or not _finite(ts):
        return {"gate": "O4", "status": "O4_NO_CONVICTION", "direction": None}
    if direction != ("up" if side == "LONG" else "down"):
        return {"gate": "O4", "status": "O4_NO_CONVICTION", "direction": direction}
    if not _finite(now_ms) or now_ms - float(ts) > O4_WINDOW_MS:
        return {"gate": "O4", "status": "O4_NO_CONVICTION", "direction": direction}

    relevant = raw.get("putWallEs") if side == "LONG" else raw.get("callWallEs")
    if not _finite(relevant) or not _finite(level):
        return {"gate": "O4", "status": "O4_NO_LOCATION", "direction": direction}
    if abs(level - float(relevant)) / TICK_ES > O4_LOCATION_TOLERANCE_TICKS:
        return {"gate": "O4", "status": "O4_NO_LOCATION", "direction": direction}
    return {"gate": "O4", "status": "PASS", "direction": direction}


# ---------------------------------------------------------------------------
# Assemblage — point d'appel UNIQUE à l'armement (port de decisionLog.ts)
# ---------------------------------------------------------------------------

def evaluate_options_gates(snapshot: OptionsContextSnapshot, *, level: float, side: str,
                           entry_price: float, target_price: float, es_bars: Any,
                           now_ms: float, o5_config: Optional[dict] = None) -> dict[str, Any]:
    """Appelé UNE fois par armement, après le calcul de la géométrie (entrée, stop, TP) —
    cohérent avec la cadence spécifiée : O1/O2 relus à chaque armement, O3 après la géométrie,
    O4 synchrone avec le balayage.

    Ne lève jamais : chaque sous-évaluateur est déjà fail-closed sur ses propres entrées, et
    cette fonction n'ajoute rien qui puisse échouer au-delà de la lecture pure du cache
    (`snapshot`, garanti sans I/O).

    **Aucune valeur retournée n'a de sens booléen bloquant** — pas de `blocked`, pas de
    `allowed` : il n'y a rien à vérifier avant d'exécuter le trade.
    """
    return {
        "o1": evaluate_o1(snapshot, level, side),
        "o2": evaluate_o2(snapshot, entry_price),
        "o3": evaluate_o3(snapshot, entry_price, target_price, side),
        "o4": evaluate_o4(snapshot, side, level, now_ms),
        # O5 ne dépend JAMAIS du contexte options : calcul local, zéro dépendance fournisseur.
        "o5": evaluate_o5(es_bars, o5_config if o5_config is not None else O5_CONFIG_PLACEHOLDER,
                          now_ms),
        "context_health": snapshot.health.value,
        "timestamp": now_ms,
    }


def to_csv_columns(entry: dict[str, Any]) -> dict[str, Any]:
    """Aplatit l'entrée en colonnes, à la suite des colonnes existantes des contrôles fail-fast.
    Pure. Une mesure absente s'exporte **vide**, jamais en `None` : le journal des 60+ setups
    sera relu par la calibration, et `None` s'y lirait comme une chaîne."""
    def _v(x: Any) -> Any:
        return "" if x is None else x

    o1, o2, o3, o4, o5 = entry["o1"], entry["o2"], entry["o3"], entry["o4"], entry["o5"]
    return {
        "context_health": entry["context_health"],
        "o1_status": o1["status"],
        "o1_gex_local": _v(o1["gex_local"]),
        "o2_status": o2["status"],
        "o2_distance_ticks": _v(o2["distance_ticks"]),
        "o3_status": o3["status"],
        "o3_obstacle_level": _v(o3["obstacle_level"]),
        "o4_status": o4["status"],
        "o4_direction": _v(o4["direction"]),
        "o5_status": o5["status"],
        "o5_excess_kurtosis": _v(o5["excess_kurtosis"]),
        "o5_skewness": _v(o5["skewness"]),
        "o5_variance": _v(o5["variance"]),
        "o5_dominant_residual_share": _v(o5["dominant_residual_share"]),
        "o5_sample_size": o5["sample_size"],
    }
