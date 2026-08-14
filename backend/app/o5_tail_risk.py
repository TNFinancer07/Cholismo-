"""O5 — tail risk caché (D-076).

Port Python de `reference/v2/fast-engine/o5TailRisk.ts` (v2), sous verrou de parité (D-072 : un
test LIT le TypeScript et échoue si les deux côtés divergent).

**O5 est la seule balise autonome** : elle ne lit jamais le contexte options, seulement les
barres ES. Un fournisseur mort ne l'entraîne pas dans sa chute.

**Pourquoi des barres et non des rendements bruts** (rupture assumée du v2 sur le v1) : sans
horodatage, impossible de rejeter une barre dupliquée ou hors-ordre après une reconnexion
Rithmic — un mouvement extrême compterait alors double, en silence, dans la mesure même qui
existe pour détecter les mouvements extrêmes. Impossible aussi de voir un trou temporel.

**Mode G2 — garantie structurelle.** Aucune fonction ne retourne de booléen bloquant, aucune ne
lève : il n'existe pas de chemin de blocage à réactiver par erreur. Toute donnée absente,
insuffisante, dupliquée, trouée ou dégénérée produit un statut consultatif explicite — **jamais
`PASS` par défaut** (§3).

**Explicitement rejeté côté TS, et non réintroduit ici** : calcul incrémental (Welford/West),
tampon en tableau typé, lissage du kurtosis par moyenne mobile, fenêtre adaptative par période
de séance. Mesuré et documenté là-bas comme gain nul ou négatif, ou destruction du signal
recherché.

**Coût.** Deux passes sur ~120 rendements, numériquement stable. C'est du CPU **synchrone** :
exécuté tel quel dans une boucle asyncio, il la gèle avant tout point d'attente (piège Python en
tête de `RUNTIME_LOOPS.md`). C'est à la boucle L3 de le déporter (`asyncio.to_thread`) — ce
module reste pur et n'impose rien.

Tous les seuils sont `PLACEHOLDER` : aucun n'a été validé sur données.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

#: Miroir exact de `O5Status` (verrouillé par test).
STATUSES = ("PASS", "FLAG_HIDDEN_TAIL", "O5_SAMPLE_TOO_SMALL", "O5_DATA_GAP")

#: Miroir de `O5_CONFIG_PLACEHOLDER`. `window_size` 121 barres → 120 rendements.
#: `max_bar_gap_ms` 90 s pour des barres nominales 1 min : tolère une barre manquée, pas deux.
O5_CONFIG_PLACEHOLDER: dict[str, Any] = {
    "window_size": 121,
    "min_samples": 30,
    "kurtosis_threshold": 6.0,
    "max_bar_gap_ms": 90_000,
    "is_placeholder": True,
}


def config_with(**over: Any) -> dict[str, Any]:
    """Config dérivée — l'étiquette `is_placeholder` ne se perd jamais en route."""
    cfg = dict(O5_CONFIG_PLACEHOLDER)
    cfg.update(over)
    cfg["is_placeholder"] = True
    return cfg


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _bar_parts(bar: Any) -> Optional[tuple[float, float]]:
    """`(timestamp, close)` d'une barre, ou `None` si elle est inexploitable. Ne lève jamais :
    les barres viennent d'un feed, et un feed livre parfois n'importe quoi."""
    if not isinstance(bar, dict):
        return None
    ts, close = bar.get("timestamp"), bar.get("close")
    if not _finite(ts) or not _finite(close):
        return None
    return float(ts), float(close)


def push_bar(buffer: Iterable[Any], bar: Any, max_size: int) -> tuple[tuple, bool, Optional[str]]:
    """Ajoute une barre au tampon glissant. **Pure** : le tampon d'entrée n'est jamais muté.

    Rejette toute barre dont l'horodatage n'est pas strictement postérieur au dernier connu —
    protection contre un replay de reconnexion Rithmic qui renverrait une barre déjà vue. Le
    rejet est SIGNALÉ, pas levé : c'est à l'appelant de compter les rejets s'il le souhaite
    (état injecté, comme partout dans le moteur).

    Rend `(tampon, accepté, motif)`.
    """
    buf = tuple(buffer)
    parts = _bar_parts(bar)
    if parts is None:
        return buf, False, "invalid"
    ts, _ = parts
    if buf:
        last = _bar_parts(buf[-1])
        if last is not None:
            if ts == last[0]:
                return buf, False, "duplicate"
            if ts < last[0]:
                return buf, False, "out_of_order"
    nxt = buf + (bar,)
    if max_size > 0 and len(nxt) > max_size:
        nxt = nxt[len(nxt) - max_size:]
    return nxt, True, None


def to_log_returns(bars: Iterable[Any]) -> list[float]:
    """`ln(closeₜ / closeₜ₋₁)`. Suppose les barres triées (garanti par `push_bar`). Rend `nan`
    pour toute transition invalide plutôt que de lever — `evaluate_o5` traite tout `nan` comme
    un échantillon invalide."""
    out: list[float] = []
    seq = tuple(bars)
    for i in range(1, len(seq)):
        prev, cur = _bar_parts(seq[i - 1]), _bar_parts(seq[i])
        if prev is None or cur is None or prev[1] <= 0 or cur[1] <= 0:
            out.append(math.nan)
            continue
        out.append(math.log(cur[1] / prev[1]))
    return out


def has_temporal_gap(bars: Iterable[Any], max_gap_ms: float) -> bool:
    seq = tuple(bars)
    for i in range(1, len(seq)):
        prev, cur = _bar_parts(seq[i - 1]), _bar_parts(seq[i])
        if prev is None or cur is None:
            continue
        if cur[0] - prev[0] > max_gap_ms:
            return True
    return False


def _compute_moments(returns: list[float]) -> Optional[dict[str, float]]:
    """Moyenne, variance, asymétrie, excess kurtosis et attribution du résidu dominant, en deux
    passes (numériquement stable ; le coût est négligeable à n≈120). Rend `None` si la série est
    vide, dégénérée (variance nulle) ou contient une valeur non finie — **jamais** un `inf` qui
    se lirait comme une mesure."""
    n = len(returns)
    if n == 0:
        return None
    total = 0.0
    for r in returns:
        if not _finite(r):
            return None
        total += r
    mean = total / n

    m2 = m3 = m4 = max_d4 = 0.0
    for r in returns:
        d = r - mean
        d2 = d * d
        m2 += d2
        m3 += d2 * d
        m4 += d2 * d2
        if d2 * d2 > max_d4:
            max_d4 = d2 * d2
    m2 /= n
    m3 /= n
    m4 /= n
    if m2 == 0:
        return None

    return {
        "mean": mean,
        "variance": m2,
        "skewness": m3 / math.pow(m2, 1.5),
        "excess_kurtosis": m4 / (m2 * m2) - 3.0,
        # `m4` est déjà divisé par n : `m4 * n` reconstitue Σd⁴, donc la part portée par le
        # résidu le plus extrême. Sans elle, « kurtosis 40 » ne dit pas si c'est une
        # distribution large ou un seul point aberrant.
        "dominant_residual_share": 0.0 if m4 == 0 else max_d4 / (m4 * n),
    }


def _empty(status: str, sample_size: int, now_ms: float, config: dict) -> dict[str, Any]:
    return {"status": status, "excess_kurtosis": None, "skewness": None, "variance": None,
            "dominant_residual_share": None, "sample_size": sample_size,
            "timestamp": now_ms, "config_used": config}


def evaluate_o5(bars: Any, config: Optional[dict] = None,
                now_ms: float = 0.0) -> dict[str, Any]:
    """Évalue O5 sur un tampon de barres. **Ne lève jamais** ; résultat consultatif, journalisé.

    Garde-fous, dans l'ordre — et l'ordre compte : calculer un kurtosis sur une fenêtre trouée
    produirait un nombre d'apparence valide sur une série qui n'existe pas.
      1. pas assez de barres pour former `min_samples` rendements → `O5_SAMPLE_TOO_SMALL`
      2. trou temporel dans la fenêtre                            → `O5_DATA_GAP`
      3. rendements non calculables ou série dégénérée            → `O5_SAMPLE_TOO_SMALL`
      4. toute défaillance interne inattendue                     → `O5_SAMPLE_TOO_SMALL`
      5. sinon, comparaison stricte au seuil        → `PASS` | `FLAG_HIDDEN_TAIL`
    """
    cfg = config if config is not None else O5_CONFIG_PLACEHOLDER
    try:
        seq = tuple(bars) if isinstance(bars, (list, tuple)) else ()
        min_bars = int(cfg["min_samples"]) + 1
        if len(seq) < min_bars:
            return _empty("O5_SAMPLE_TOO_SMALL", len(seq), now_ms, cfg)

        window = seq[-int(cfg["window_size"]):]
        if has_temporal_gap(window, cfg["max_bar_gap_ms"]):
            return _empty("O5_DATA_GAP", len(window), now_ms, cfg)

        returns = to_log_returns(window)
        if len(returns) < int(cfg["min_samples"]):
            return _empty("O5_SAMPLE_TOO_SMALL", len(returns), now_ms, cfg)

        moments = _compute_moments(returns)
        if moments is None or not _finite(moments["excess_kurtosis"]):
            return _empty("O5_SAMPLE_TOO_SMALL", len(returns), now_ms, cfg)

        flagged = moments["excess_kurtosis"] > cfg["kurtosis_threshold"]
        return {
            "status": "FLAG_HIDDEN_TAIL" if flagged else "PASS",
            "excess_kurtosis": moments["excess_kurtosis"],
            "skewness": moments["skewness"],
            "variance": moments["variance"],
            "dominant_residual_share": moments["dominant_residual_share"],
            "sample_size": len(returns),
            "timestamp": now_ms,
            "config_used": cfg,
        }
    except Exception:
        # Fail-closed absolu, cohérent avec le TS : jamais de propagation d'erreur depuis un
        # gate consultatif — elle interromprait la chaîne d'armement, donc bloquerait.
        size = len(bars) if isinstance(bars, (list, tuple)) else 0
        return _empty("O5_SAMPLE_TOO_SMALL", size, now_ms, cfg)
