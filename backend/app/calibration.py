"""Passe de calibration sur une séance MBO (D-082, phase P2).

    python -m app.calibration seance.parquet [--csv setups.csv] [--min-sample 10]

Le point d'entrée qui tournera **le jour où le fichier Databento arrivera**. Il enchaîne la
chaîne complète, sans étape manuelle :

    Parquet MBO → carnet L2/L3 → armement → simulateur FIFO → issues → journal → matrice

**Ce qu'il mesure enfin.** Le taux de **non-remplissage** est la mesure laissée non chiffrée
depuis D-078 : c'est lui qui donne la magnitude réelle du biais de touché, celle qu'aucune
fixture synthétique ne pouvait produire. Un backtest naïf l'affiche structurellement à 0 %.

**Le détecteur d'armement est INJECTÉ.** Ce module ne décide pas quand un setup se déclenche ;
il mesure ce qui arrive à ceux qu'on lui donne. Sans détecteur fourni, il n'invente pas de
setups : il le dit et s'arrête. Fabriquer des armements arbitraires produirait une matrice
d'allure complète mesurant un générateur, pas une stratégie.

**Rien n'est conclu ici.** Le module compte et imprime. Le taux de réussite réel reste inconnu,
et la calibration doit mesurer, jamais confirmer.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Optional

from .event_store import EventStore
from .mbo.book import MboBook
from .mbo.events import MboEvent
from .mbo.ingest import ingest_parquet
from .mbo.lsr_adapter import MboLsrDetector
from .mbo.session_context import SessionContext
from .replay_harness import ReplayHarness, Setup, summarize
from .setup_journal import SetupJournal


def run_calibration(parquet_path: str, *,
                    arm: Callable[[MboBook, MboEvent], Optional[Setup]],
                    journal: SetupJournal,
                    tick_size: float = 0.25, point_value: float = 5.0,
                    latency_ms: float = 35.0, latency_jitter_ms: float = 15.0,
                    rng_seed: int = 0,
                    min_cell_sample: int = 10) -> dict[str, Any]:
    """Rejoue une séance, journalise armements et issues, rend le bilan + la matrice.

    Les armements sont écrits AVANT les issues, dans l'ordre du flux : le journal doit pouvoir
    se relire comme l'histoire de la séance, pas comme son résumé."""
    events, ingest_stats = ingest_parquet(parquet_path)
    harness = ReplayHarness(tick_size=tick_size, point_value=point_value,
                            latency_ms=latency_ms, latency_jitter_ms=latency_jitter_ms,
                            rng_seed=rng_seed)

    armed: list[Setup] = []

    def _arm(book: MboBook, event: MboEvent) -> Optional[Setup]:
        setup = arm(book, event)
        if setup is not None:
            armed.append(setup)
        return setup

    outcomes = harness.run(events, _arm)

    for setup in armed:
        journal.record_armed({
            "setup_id": setup.setup_id, "armed_ts_ms": setup.armed_ts_ms,
            "side": setup.side, "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss, "target_price": setup.take_profit,
            "position_size": setup.qty,
        })
    for outcome in outcomes:
        journal.record_outcome(outcome.as_event())

    return {
        "ingest": ingest_stats.as_dict(),
        "replay": summarize(outcomes),
        "calibration": journal.calibration_matrix(min_cell_sample=min_cell_sample),
    }


def _format(report: dict[str, Any]) -> str:
    ingest, replay = report["ingest"], report["replay"]
    lines = [
        "── Ingestion ─────────────────────────────────────────",
        f"  lignes lues     {ingest['rows_read']}",
        f"  événements      {ingest['events_emitted']}",
        f"  rejetées        {ingest['rows_rejected']}  ({ingest['reject_ratio']:.1%})",
        f"  hors-ordre      {ingest['out_of_order_count']}",
        f"  trous           {len(ingest['gaps'])}",
        "",
        "── Rejeu ─────────────────────────────────────────────",
        f"  setups armés    {replay['setups']}",
        f"  par issue       {replay['by_status']}",
    ]
    no_fill = replay["no_fill_rate"]
    lines.append(
        # LA mesure de P3/P2 : un backtest naïf l'affiche structurellement à 0 %.
        f"  NON REMPLIS     {no_fill:.1%}" if no_fill is not None
        else "  NON REMPLIS     — (aucun setup)")
    win = replay["win_rate"]
    lines.append(f"  réussite        {win:.1%} (sur trades PRIS)" if win is not None
                 else "  réussite        — (aucun trade pris)")
    lines += ["", "── Calibration par balise ────────────────────────────"]
    for gate, statuses in report["calibration"]["by_gate"].items():
        for status, cell in statuses.items():
            rate = (f"{cell['win_rate']:.1%}" if cell["win_rate"] is not None
                    else f"— ({cell['status']})")
            lines.append(f"  {gate}/{status:<26} n={cell['settled']:<4} réussite {rate}")
    detector = report.get("detector")
    if detector:
        lines += ["", "── Détecteur LSR sur MBO ─────────────────────────────",
                  f"  prints accumulés  {detector['prints_accumulated']}",
                  f"  setups armés      {detector['armed']}",
                  f"  refusés (post-sweep) {detector['refused_after_sweep']}",
                  f"  ATR (dérivé du flux) fast={detector['atr']['atr_fast']} "
                  f"slow={detector['atr']['atr_slow']} sur {detector['atr']['bars_closed']} barres",
                  f"  joint du contexte : {', '.join(detector['inputs_joined_from_context']) or '— (aucun --context)'}",
                  f"  ⓘ absent, non joignable : {', '.join(detector['inputs_absent_from_mbo'])}"]
    if not report["calibration"]["result_visible"]:
        lines += ["", f"  ⓘ volet RÉSULTAT masqué — moins de "
                      f"{report['calibration']['result_min_trades']} trades dénoués (§2.7)"]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Passe de calibration sur une séance MBO")
    parser.add_argument("parquet", help="export Databento GLBX.MDP3 (MES/MNQ)")
    parser.add_argument("--csv", help="chemin d'export du journal des setups")
    parser.add_argument("--db", help="base du journal (défaut : celle du terminal)")
    parser.add_argument("--min-sample", type=int, default=10,
                        help="échantillon minimal par cellule de la matrice")
    parser.add_argument("--tick", type=float, default=0.25, help="taille du tick")
    parser.add_argument("--context", help="JSON de contexte de séance (VIX + calendrier) — "
                        "joint POINT-IN-TIME, jamais interrogé au présent (D-084)")
    parser.add_argument("--news-state", default=None,
                        help="état de la porte F0 (défaut : inconnu → fail-closed, D-050)")
    parser.add_argument("--json", action="store_true", help="rapport brut en JSON")
    args = parser.parse_args(argv)

    journal = SetupJournal(EventStore(args.db) if args.db else None)
    # Le détecteur LSR RÉEL (D-083) : il projette l'état MBO dans un ContextSchema et réutilise
    # la chaîne déterministe existante. Il refuse tant que les entrées absentes du fichier
    # manquent — refus MOTIVÉ, rapporté par `diagnostics()`, jamais un silence.
    context = SessionContext.from_json_file(args.context) if args.context else None
    detector = MboLsrDetector(tick_size=args.tick, news_state=args.news_state, context=context)
    report = run_calibration(args.parquet, arm=detector, journal=journal,
                             tick_size=args.tick, min_cell_sample=args.min_sample)
    report["detector"] = detector.diagnostics()
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else _format(report))
    if args.csv:
        journal.to_csv(args.csv)
        print(f"\njournal exporté : {args.csv}")
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
