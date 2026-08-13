"""Journal des setups et matrice de calibration (D-082, phase P2).

L'infrastructure qui recevra les 60+ setups. Elle répond à **une** question, et c'est celle qui
justifie toute la phase :

> Les setups marqués `FLAG` par les balises O1-O5 ont-ils un taux de réussite dégradé ?

**Grammaire event-sourced, reprise telle quelle du Decision Log** (`CLAUDE §2.5`, D-045) :
`setup_armed` est un event **immuable** écrit par L4 à l'armement ; `setup_outcome` est un event
**ultérieur** qui le référence par `setup_id`. L'état courant est une **projection**. Aucun
chemin ne met à jour un armement — le corriger reviendrait à réécrire l'histoire de la
calibration, et l'append-only est garanti par des triggers SQLite, pas par convention.

---

**Quatre règles d'honnêteté, toutes testées.**

1. **`NO_FILL` n'entre pas au dénominateur du taux de réussite.** « La stratégie gagne-t-elle ? »
   et « les entrées sont-elles servies ? » sont deux questions ; les mélanger rend les deux
   illisibles. Le taux de non-remplissage est remonté **à côté**, au même rang.
2. **Sous l'échantillon minimal, le taux vaut `None`, pas un chiffre.** Un taux de réussite sur
   trois trades n'est pas une mesure, c'est du bruit avec une décimale. Le statut le dit :
   `INSUFFICIENT_DATA`.
3. **Un setup sans issue est `PENDING`, jamais un résultat neutre.** Le compter comme nul
   fabriquerait des trades qui n'ont pas eu lieu.
4. **Process et résultat ne sont jamais consolidés** (`CLAUDE §2.7`). La matrice porte des
   volets séparés, et le volet résultat reste masqué sous `RESULT_SCORE_MIN_TRADES`.

**Ce module ne conclut rien.** Il compte. Aucune fonction ici n'écrit qu'une balise « marche »
ou « a un edge » : le taux de réussite réel est inconnu, aucun des contrôles n'a été validé sur
données, et la calibration doit **mesurer**, jamais confirmer.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Optional

from . import config
from .event_store import EventStore, get_store

#: Colonnes de l'export, dans l'ordre : identité, décision, balises, exécution, issue.
CSV_COLUMNS = (
    "setup_id", "armed_ts_ms", "instrument", "side", "entry_price", "stop_loss",
    "target_price", "position_size",
    "context_health",
    "o1_status", "o1_gex_local", "o2_status", "o2_distance_ticks",
    "o3_status", "o3_obstacle_level", "o4_status", "o4_direction",
    "o5_status", "o5_excess_kurtosis", "o5_skewness", "o5_variance",
    "o5_dominant_residual_share", "o5_sample_size",
    "entry_queue_ahead", "entry_feasible", "entry_reject_reason",
    "outcome_status", "entry_fill_price", "entry_queue_remaining",
    "exit_price", "exit_reason", "pnl_ticks", "pnl_usd", "exit_slip_ticks",
)

#: Les cinq balises dont on veut savoir si elles discriminent.
GATES = ("o1", "o2", "o3", "o4", "o5")

#: Sous ce nombre de trades DÉNOUÉS, aucun taux n'est publié pour une cellule. PLACEHOLDER —
#: il borne le bruit, il ne prétend pas à une puissance statistique.
MIN_CELL_SAMPLE = 10


class SetupJournal:
    """Écriture append-only + projections. Ne décide rien, ne conclut rien."""

    def __init__(self, store: Optional[EventStore] = None):
        self._store = store if store is not None else get_store()

    # -- écriture --

    def record_armed(self, entry: dict[str, Any], ts: Optional[float] = None) -> dict[str, Any]:
        """Écrit l'armement. Appelé par L4 (D-080) avec l'entrée qu'elle a produite."""
        setup_id = entry.get("setup_id")
        if not setup_id:
            raise ValueError("setup_armed sans setup_id : l'issue n'aurait rien à référencer")
        return self._store.append_setup("setup_armed", str(setup_id), dict(entry), ts=ts)

    def record_outcome(self, outcome: dict[str, Any],
                       ts: Optional[float] = None) -> dict[str, Any]:
        """Écrit l'issue — event ULTÉRIEUR qui référence l'armement. Vient du harnais de rejeu
        (D-081) en backtest, ou de la réconciliation NinjaTrader en live."""
        setup_id = outcome.get("setup_id")
        if not setup_id:
            raise ValueError("setup_outcome sans setup_id : une issue orpheline ne mesure rien")
        return self._store.append_setup("setup_outcome", str(setup_id), dict(outcome), ts=ts)

    # -- projection --

    def projection(self) -> list[dict[str, Any]]:
        """État courant par setup, reconstruit en rejouant les events dans l'ordre de `seq`.

        **Le PREMIER armement gagne.** Un second `setup_armed` pour un même `setup_id` est une
        anomalie (double émission) : l'écraser laisserait croire à une correction propre. Il est
        conservé au journal et compté dans `duplicate_armed`. Idem pour une seconde issue : la
        première fait foi, les suivantes sont comptées."""
        setups: dict[str, dict[str, Any]] = {}
        duplicates = {"armed": 0, "outcome": 0}
        for event in self._store.setup_entries():
            setup_id = event["setup_id"]
            if event["kind"] == "setup_armed":
                if setup_id in setups:
                    duplicates["armed"] += 1
                    continue
                setups[setup_id] = {**{k: v for k, v in event.items()
                                       if k not in ("kind", "id", "seq")},
                                    "outcome_status": "PENDING"}
            else:
                current = setups.get(setup_id)
                if current is None:
                    # Issue orpheline : conservée au journal, absente de la projection. Elle ne
                    # référence aucun armement, donc ne mesure rien.
                    duplicates["outcome"] += 1
                    continue
                if current.get("outcome_status") != "PENDING":
                    duplicates["outcome"] += 1
                    continue
                current.update({
                    "outcome_status": event.get("status", "PENDING"),
                    "entry_fill_price": event.get("entry_fill_price"),
                    "entry_queue_remaining": event.get("entry_queue_remaining"),
                    "exit_price": event.get("exit_price"),
                    "exit_reason": event.get("exit_reason"),
                    "pnl_ticks": event.get("pnl_ticks"),
                    "pnl_usd": event.get("pnl_usd"),
                    "exit_slip_ticks": event.get("exit_slip_ticks"),
                })
        rows = list(setups.values())
        for row in rows:
            row["_duplicates"] = duplicates
        return rows

    # -- export --

    def to_csv(self, path: Optional[str] = None) -> str:
        """Export CSV. Les colonnes sont FIXES et ordonnées : un export dont les colonnes
        changent selon les données présentes n'est pas comparable d'une passe à l'autre."""
        rows = self.projection()
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: _csv_value(row.get(col)) for col in CSV_COLUMNS})
        content = buffer.getvalue()
        if path:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        return content

    # -- LA question de P2 --

    def calibration_matrix(self, *, min_cell_sample: int = MIN_CELL_SAMPLE) -> dict[str, Any]:
        """Par balise et par statut : combien de setups, combien jamais servis, et — seulement
        si l'échantillon le permet — quel taux de réussite sur les trades réellement pris.

        C'est la seule sortie qui répond à la question de P2. Elle ne conclut pas : elle compte,
        et dit quand elle ne peut pas compter."""
        rows = self.projection()
        matrix: dict[str, Any] = {}
        for gate in GATES:
            column = f"{gate}_status"
            by_status: dict[str, Any] = {}
            for status in sorted({str(r.get(column)) for r in rows if r.get(column) is not None}):
                subset = [r for r in rows if str(r.get(column)) == status]
                by_status[status] = _cell(subset, min_cell_sample)
            matrix[gate] = by_status
        return {
            "generated_from": len(rows),
            "min_cell_sample": min_cell_sample,
            "overall": _cell(rows, min_cell_sample),
            "by_gate": matrix,
            # Volet PROCESS et volet RÉSULTAT jamais consolidés (§2.7). Le second reste masqué
            # tant que l'échantillon de trades dénoués n'atteint pas le seuil.
            "result_visible": len([r for r in rows if r.get("outcome_status") in ("WIN", "LOSS")])
            >= config.RESULT_SCORE_MIN_TRADES,
            "result_min_trades": config.RESULT_SCORE_MIN_TRADES,
            "duplicates": rows[0]["_duplicates"] if rows else {"armed": 0, "outcome": 0},
        }


def _cell(rows: Iterable[dict[str, Any]], min_sample: int) -> dict[str, Any]:
    """Une cellule de la matrice. `win_rate` n'est publié qu'au-delà de l'échantillon minimal :
    un taux sur trois trades n'est pas une mesure, c'est du bruit avec une décimale."""
    items = list(rows)
    total = len(items)
    pending = sum(1 for r in items if r.get("outcome_status") == "PENDING")
    no_fill = sum(1 for r in items if r.get("outcome_status") == "NO_FILL")
    settled = [r for r in items if r.get("outcome_status") in ("WIN", "LOSS")]
    wins = sum(1 for r in settled if r.get("outcome_status") == "WIN")
    resolved = total - pending
    enough = len(settled) >= min_sample
    pnls = [r.get("pnl_usd") for r in settled if isinstance(r.get("pnl_usd"), (int, float))]
    return {
        "setups": total,
        "pending": pending,
        "no_fill": no_fill,
        # Le taux de non-remplissage se calcule sur les setups RÉSOLUS : inclure les `PENDING`
        # le ferait baisser mécaniquement à mesure qu'on arme, sans qu'aucune entrée n'ait
        # été servie ou refusée.
        "no_fill_rate": (no_fill / resolved) if resolved else None,
        "settled": len(settled),
        "win_rate": (wins / len(settled)) if enough and settled else None,
        "status": "OK" if enough else "INSUFFICIENT_DATA",
        "avg_pnl_usd": (sum(pnls) / len(pnls)) if enough and pnls else None,
    }


def _csv_value(value: Any) -> Any:
    """`None` s'exporte VIDE. La chaîne « None » dans un CSV se relit comme une valeur."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return value
