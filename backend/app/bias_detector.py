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

from dataclasses import asdict, dataclass
from typing import Optional

from . import config


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
    fail-closed : un champ manquant désactive le détecteur concerné pour ce trade (§3)."""
    findings: list[BiasFinding] = []
    for i, t in enumerate(trades):
        instrument = str(t.get("instrument", ""))
        expo = t.get("exposure_seconds")
        entry = t.get("entry_ts")
        exit_ts = t.get("exit_ts")
        anomaly = bool(t.get("entry_delta_anomaly"))

        # 1) FOMO — entrée impulsive : tenue anormalement courte SUR une anomalie de delta.
        if expo is not None and expo < config.FOMO_MAX_DURATION_S and anomaly:
            findings.append(BiasFinding(
                "FOMO", i, instrument, entry, exit_ts, expo,
                f"Entrée impulsive : {int(expo)}s de tenue sur une anomalie de delta "
                f"(< {int(config.FOMO_MAX_DURATION_S)}s)."))

        # 2) EXEC_TOO_LONG — position tenue au-delà du seuil critique.
        if expo is not None and expo > config.EXEC_MAX_DURATION_S:
            findings.append(BiasFinding(
                "EXEC_TOO_LONG", i, instrument, entry, exit_ts, expo,
                f"Exécution trop longue : {int(expo)}s > seuil critique "
                f"{int(config.EXEC_MAX_DURATION_S)}s."))

        # 3) REVENGE — trade initié < REVENGE_WINDOW_S après la clôture d'une PERTE antérieure.
        if entry is not None:
            for j, p in enumerate(trades):
                if j == i:
                    continue
                pnl = p.get("pnl_usd")
                p_exit = p.get("exit_ts")
                if (pnl is not None and pnl < 0 and p_exit is not None
                        and 0 <= entry - p_exit < config.REVENGE_WINDOW_S):
                    gap = int(entry - p_exit)
                    findings.append(BiasFinding(
                        "REVENGE", i, instrument, entry, exit_ts, expo,
                        f"Trade initié {gap}s après une perte "
                        f"(< {int(config.REVENGE_WINDOW_S)}s) — revenge trading."))
                    break
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
