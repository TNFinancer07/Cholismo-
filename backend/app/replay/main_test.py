"""Démonstration du mode Replay — génère, rejoue, affiche (Étape 1).

    python -m app.replay.main_test              # tape avec pathologies (défaut)
    python -m app.replay.main_test --propre     # tape sans pathologies, pour comparer
    python -m app.replay.main_test --vitesse 50 # rejoue au temps RÉEL, ×50

⚠ Le nom `main_test.py` correspond au motif de collecte `*_test.py` de pytest. Le dépôt est
protégé par `testpaths = ["tests"]` dans `pyproject.toml`, donc `pytest` ne le ramasse pas —
mais `pytest app/` le ferait. Les vrais tests du moteur sont dans `tests/test_replay_engine.py`.

Ce que cette démonstration montre, et qui est le point de l'étape : les lignes pourries sont
ÉCARTÉES et COMPTÉES, pas devinées, et le replay va jusqu'au bout. Une profondeur absente
s'affiche « inconnue » — jamais 0.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .mock_data_generator import DEFAUT, generer
from .replay_engine import ReplayEngine, Tick


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Démonstration du mode Replay local.")
    p.add_argument("--ticks", type=int, default=40)
    p.add_argument("--afficher", type=int, default=12, help="nombre de ticks détaillés")
    p.add_argument("--propre", action="store_true")
    p.add_argument("--vitesse", type=float, default=None,
                   help="multiplicateur du temps réel du fichier (sinon : aucune pause)")
    p.add_argument("--fichier", type=Path, default=DEFAUT)
    args = p.parse_args(argv)

    bilan = generer(args.fichier, args.ticks, propre=args.propre)
    print(f"1. Tape généré : {bilan['lignes']} lignes"
          + ("" if args.propre else f" · pathologies semées : {sum(bilan['seme'].values())}"))
    for nom, n in sorted(bilan["seme"].items()):
        print(f"     {n:>3}× {nom}")

    vus: list[Tick] = []

    def on_tick(tick: Tick) -> None:
        vus.append(tick)
        if len(vus) <= args.afficher:
            # Accès par clé LITTÉRALE : le `TypedDict` refuse l'indexation dynamique, et il a
            # raison — c'est ce qui garantit que `bid_vol` est bien Optional partout.
            def profond(valeur: float | None) -> str:
                return "inconnue" if valeur is None else f"{valeur:.1f}"

            profondeur = f"bid={profond(tick['bid_vol'])} ask={profond(tick['ask_vol'])}"
            print(f"     {len(vus):>3}  t={tick['timestamp']:.3f}  {tick['side']:<4} "
                  f"{tick['volume']:>3} @ {tick['price']:>8.2f}   {profondeur}")

    print(f"\n2. Replay ({args.afficher} premiers ticks affichés) :")
    resume = ReplayEngine(str(args.fichier), on_tick).start(speed=args.vitesse)

    print(f"\n3. Bilan : {resume}")
    if resume.first_ts and resume.last_ts:
        print(f"     fenêtre rejouée : {resume.last_ts - resume.first_ts:.1f} s de séance")
    absentes = sum(1 for t in vus if t["bid_vol"] is None or t["ask_vol"] is None)
    print(f"     {absentes} tick(s) à profondeur INCONNUE — rendus `None`, jamais 0 : "
          "une profondeur absente n'est pas une absence de liquidité (D-055).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
