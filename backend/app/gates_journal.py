"""L4 `gates.eval` — évaluation des balises O1-O5 à l'armement (D-080, phase P3 item 3).

Point d'appel **unique** et **événementiel** : quand le détecteur de sweep arme un setup et que
le moteur émet un manifeste, O1-O5 sont évaluées une fois, sur l'état exact du contexte et du
carnet à cet instant. Une évaluation périodique réévaluerait le PASSÉ — le piège de cadence de
D-052, et la raison pour laquelle `gates.eval` est déclarée `EVENT_DRIVEN` depuis D-073.

**MODE G2 — CONSULTATIF, POINT FINAL.** Ce module **journalise**, il ne bloque rien. Il est
appelé APRÈS que le manifeste existe, donc après que les contrôles déterministes ont statué :
même s'il levait, il ne pourrait pas retirer un manifeste déjà émis. Il ne lève pas pour autant
— une exception ici polluerait la boucle d'un module qui n'a aucun pouvoir de décision.

---

**Ce qui peut être mesuré à l'armement, et ce qui ne le peut pas.**

L'objectif de P3 est de journaliser chaque setup « avec son PnL/slippage simulé ». Les deux
moitiés n'ont pas le même statut, et les confondre produirait un chiffre inventé :

- **Le slippage d'ENTRÉE est mesurable maintenant.** Le carnet est connu, la file d'attente à
  notre prix limite se lit dedans, et le simulateur FIFO (D-078) dit ce qu'un ordre y subirait.
- **Le PnL ne l'est PAS.** Le trade n'a pas eu lieu ; sa sortie dépend d'un futur qui n'est pas
  encore arrivé. Fabriquer un PnL à l'armement reviendrait à supposer le résultat qu'on cherche
  précisément à mesurer.

Ce n'est pas une limitation, c'est la doctrine event-sourced déjà établie (`CLAUDE §2.5`,
D-045) : **la décision est un event immuable ; l'outcome est un event ULTÉRIEUR qui la
référence**. Le setup est donc journalisé avec son `setup_id` ; le PnL arrivera comme
`OutcomeEvent`, par réconciliation NinjaTrader en live ou par rejeu MBO en backtest.

L'entrée porte `pnl_source: "PENDING"` — jamais un zéro qui se lirait comme un résultat nul.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .execution_sim import Book, ExecutionSimulator
from .features import build_feature_vector
from .options_gates import evaluate_options_gates, to_csv_columns

log = logging.getLogger("cholismo.gates_journal")


def _entry_execution(book: Optional[Book], side: str, entry_price: Any, qty: Any,
                     tick_size: float, now_ms: float) -> dict[str, Any]:
    """Ce qu'un ordre limite subirait À CETTE ENTRÉE, d'après le carnet observé.

    Fail-closed : sans carnet exploitable, le simulateur **refuse** l'ordre (D-078) et on le
    rapporte tel quel. Une file supposée nulle ferait passer notre ordre pour premier servi,
    exactement le biais que P3 existe pour supprimer."""
    unavailable = {"queue_ahead": None, "entry_feasible": None, "reject_reason": "NO_BOOK"}
    if book is None or not isinstance(entry_price, (int, float)):
        return unavailable
    sim = ExecutionSimulator(tick_size=tick_size, latency_ms=0.0, latency_jitter_ms=0.0,
                             rng_seed=0)
    # Le manifeste parle en LONG/SHORT, le simulateur en BUY/SELL. Passer `LONG` tel quel lisait
    # la file du MAUVAIS côté du carnet — donc presque toujours zéro, soit « premier servi ».
    # Le simulateur refuse désormais un côté inconnu, mais la traduction doit être faite ICI.
    book_side = "BUY" if side == "LONG" else "SELL"
    order = sim.place_limit(book_side, float(entry_price), float(qty or 1), now_ms, book=book)
    if order is None:
        return unavailable
    return {
        "queue_ahead": order.queue_ahead,
        # « Faisable » = il existe de la liquidité à traverser, pas « ce sera rempli » : le
        # remplissage dépend du volume à venir, que personne ne connaît à l'armement.
        "entry_feasible": True,
        "reject_reason": None,
    }


def evaluate_at_arming(manifest: Any, *, options_snapshot: Any, es_bars: Any,
                       book: Optional[Book], now_ms: float,
                       tick_size: float = 0.25,
                       schema: Any = None) -> Optional[dict[str, Any]]:
    """Évalue O1-O5 sur un manifeste armé et rend l'entrée de journal. Rend `None` si le
    manifeste est inexploitable — jamais une entrée à moitié remplie qui se lirait comme un
    setup mesuré. Ne lève jamais (mode G2)."""
    try:
        setup = _read_manifest(manifest)
        if setup is None:
            return None

        gates = evaluate_options_gates(
            options_snapshot,
            level=setup["level"], side=setup["side"],
            entry_price=setup["entry_price"], target_price=setup["target_price"],
            es_bars=es_bars, now_ms=now_ms)

        entry = _entry_execution(book, setup["side"], setup["entry_price"],
                                 setup["position_size"], tick_size, now_ms)

        return {
            "setup_id": setup["id"],
            "ts_ms": now_ms,
            "instrument": setup["instrument"],
            "side": setup["side"],
            "entry_price": setup["entry_price"],
            "stop_loss": setup["stop_loss"],
            "target_price": setup["target_price"],
            "position_size": setup["position_size"],
            **to_csv_columns(gates),
            "entry_queue_ahead": entry["queue_ahead"],
            "entry_feasible": entry["entry_feasible"],
            "entry_reject_reason": entry["reject_reason"],
            # Le PnL n'existe pas encore — voir docstring. `PENDING`, jamais un 0 qui se lirait
            # comme un resultat nul (§3).
            # Vecteur de features (D-108) : l'état qui a produit CE setup, figé à l'armement.
            # Attaché ici parce que c'est le seul instant où il est complet ET rattaché à un
            # setup identifié — plus tard, le contexte a déjà bougé.
            "feature_vector": build_feature_vector(
                setup=setup, schema=schema, now_ms=now_ms, tick_size=tick_size),
            "pnl_source": "PENDING",
            "realized_pnl": None,
            "realized_slip_ticks": None,
            "gates": gates,
        }
    except Exception:
        # Un gate consultatif qui casse la boucle d'armement aurait un pouvoir de blocage que
        # le mode G2 lui refuse par construction. On journalise l'incident, pas plus.
        log.exception("évaluation O1-O5 en échec à l'armement (consultatif : rien n'est bloqué)")
        return None


def _read_manifest(manifest: Any) -> Optional[dict[str, Any]]:
    """Extrait ce dont les gates ont besoin. Accepte un modèle Pydantic ou son dump — le moteur
    publie l'un, les tests manipulent l'autre, et exiger un type précis ici n'apporterait rien."""
    data = manifest.model_dump() if hasattr(manifest, "model_dump") else manifest
    if not isinstance(data, dict):
        return None
    entry = data.get("entry") or {}
    risk = data.get("risk") or {}
    entry_price = entry.get("price")
    target = risk.get("takeProfit")
    if entry_price is None or target is None:
        return None
    return {
        "id": data.get("id"),
        "instrument": data.get("instrument"),
        "side": "LONG" if str(data.get("direction", "")).upper() in ("LONG", "BUY") else "SHORT",
        "entry_price": entry_price,
        "stop_loss": risk.get("stopLoss"),
        "target_price": target,
        "position_size": risk.get("positionSize"),
        # Le NIVEAU balayé est le référentiel de O1 et O4. À défaut, l'entrée en tient lieu :
        # sur un LSR l'entrée est à quelques ticks du niveau, l'approximation est bornée et
        # explicite plutôt que silencieuse.
        "level": data.get("level", entry_price),
    }
