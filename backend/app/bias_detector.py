"""Cortex Cognitif — bias_detector (D-035, Axe 4).

ANALYTIQUE POST-HOC sur les CompletedTrades (D-033). Détecte des biais comportementaux
DÉTERMINISTES (seuils booléens, aucun LLM) et calcule un Psych-Score de discipline /100.

Contraintes dures :
- **Ne bloque ni ne modifie JAMAIS le flux d'exécution (§2.1)** : c'est une lecture de trades
  DÉJÀ clôturés — aucune décision, aucun ordre, aucun verrou. Advisory pur.
- **Fail-closed (§3)** : champ absent/None → le détecteur concerné ne se déclenche pas (jamais un
  biais inventé). Aucun trade → Psych-Score None (pas un faux 100).
- **Process ≠ result (§2.7)** : le Psych-Score note le PROCESSUS (discipline), PAS le P&L. Les
  deux ne sont jamais consolidés.

Détecteurs (v1) :
1. FOMO — durée anormalement courte (< `FOMO_MAX_DURATION_S`) ET anomalie de delta à l'entrée
   (`entry_delta_anomaly`, dérivée du liquidity_sweep du snapshot d'entrée).
2. EXEC_TOO_LONG — durée d'exposition > `EXEC_MAX_DURATION_S` (seuil critique max).
3. REVENGE — trade initié moins de `REVENGE_WINDOW_S` (< 3 min, AUTORITÉ) après la CLÔTURE
   d'une perte.
"""
from __future__ import annotations

import bisect
from dataclasses import asdict, dataclass
from typing import Optional

from . import config


def _num(v) -> bool:
    """True si v est un nombre exploitable (ni None, ni bool, ni non-numérique)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class BiasFinding:
    """Un biais identifié sur UN trade (référencé par son index dans la liste analysée)."""
    type: str                      # FOMO | EXEC_TOO_LONG | REVENGE
    trade_index: int
    instrument: str
    entry_ts: Optional[float]
    exit_ts: Optional[float]
    exposure_seconds: Optional[float]
    detail: str                    # explication lisible (français, opérateur)


def detect_biases(trades: list[dict]) -> list[BiasFinding]:
    """Scanne les CompletedTrades (dumpés) et renvoie la liste des biais. Déterministe et
    fail-closed : un champ manquant/non numérique désactive le détecteur concerné (§3).

    REVENGE en O(n log n) : les clôtures de pertes sont pré-triées et interrogées par bisect
    (une recherche binaire par trade, pas de double boucle — tient les séquences massives)."""
    findings: list[BiasFinding] = []
    win = config.REVENGE_WINDOW_S
    # clôtures des trades PERDANTS, triées → recherche binaire de la fenêtre revenge.
    loss_exits = sorted(t["exit_ts"] for t in trades
                        if _num(t.get("pnl_usd")) and t["pnl_usd"] < 0 and _num(t.get("exit_ts")))

    for i, t in enumerate(trades):
        instrument = str(t.get("instrument", ""))
        expo = t.get("exposure_seconds")
        entry = t.get("entry_ts")
        exit_ts = t.get("exit_ts")
        anomaly = bool(t.get("entry_delta_anomaly"))

        # 1) FOMO — tenue anormalement COURTE (0 ≤ durée < seuil ; une durée négative = donnée
        #    invalide/inversée → pas de FOMO, §3) SUR une anomalie de delta à l'entrée.
        if _num(expo) and 0 <= expo < config.FOMO_MAX_DURATION_S and anomaly:
            findings.append(BiasFinding(
                "FOMO", i, instrument, entry, exit_ts, expo,
                f"Entrée impulsive : {int(expo)}s de tenue sur une anomalie de delta "
                f"(< {int(config.FOMO_MAX_DURATION_S)}s)."))

        # 2) EXEC_TOO_LONG — position tenue au-delà du seuil critique.
        if _num(expo) and expo > config.EXEC_MAX_DURATION_S:
            findings.append(BiasFinding(
                "EXEC_TOO_LONG", i, instrument, entry, exit_ts, expo,
                f"Exécution trop longue : {int(expo)}s > seuil critique "
                f"{int(config.EXEC_MAX_DURATION_S)}s."))

        # 3) REVENGE — trade initié < win après la clôture d'une PERTE antérieure (≠ soi-même).
        if _num(entry) and loss_exits:
            lo = bisect.bisect_right(loss_exits, entry - win)      # pertes clôturées > entry-win
            hi = bisect.bisect_right(loss_exits, entry)            # ... et ≤ entry (donc dans la fenêtre)
            in_range = hi - lo
            # exclure soi-même : seule une perte à durée nulle (exit==entry) peut se compter.
            self_counted = (_num(t.get("pnl_usd")) and t["pnl_usd"] < 0 and _num(exit_ts)
                            and entry - win < exit_ts <= entry)
            if in_range - (1 if self_counted else 0) > 0:
                gap = int(entry - loss_exits[hi - 1])              # perte la plus récente en fenêtre
                findings.append(BiasFinding(
                    "REVENGE", i, instrument, entry, exit_ts, expo,
                    f"Trade initié {gap}s après une perte "
                    f"(< {int(win)}s) — revenge trading."))
    return findings


def discipline_report(trades: list[dict]) -> dict:
    """Agrège les biais en un Psych-Score /100 = % de trades SANS biais (score de processus,
    v1 provisional). Fail-closed : aucun trade → score None (jamais un faux 100)."""
    findings = detect_biases(trades)
    total = len(trades)
    biased_indices = {f.trade_index for f in findings}
    biased = len(biased_indices)
    clean = total - biased
    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f.type] = by_type.get(f.type, 0) + 1
    return {
        "psych_score": round(100 * clean / total) if total else None,   # v1 provisional
        "total_trades": total,
        "biased_trades": biased,
        "clean_trades": clean,
        "biases_by_type": by_type,
        "biases": [asdict(f) for f in findings],
    }
