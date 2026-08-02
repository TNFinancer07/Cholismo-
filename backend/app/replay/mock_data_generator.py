"""Générateur de tape d'essai pour le mode Replay — avec ses pathologies (Étape 1).

    python -m app.replay.mock_data_generator            # 500 ticks + pathologies
    python -m app.replay.mock_data_generator --propre   # sans pathologies (comparaison)

CLAUDE §4 est explicite : « `MockDataSource` **doit injecter les pathologies réelles** : ticks
manquants, données en retard, valeurs contradictoires entre sources, NaN, désync d'horloge. Un
mock trop propre est un piège. » Ce générateur applique la même règle : par DÉFAUT il salit le
fichier, parce qu'un replay qui ne rejoue que du parfait ne prouve rien sur le comportement du
terminal face à un vrai enregistrement.

Chaque pathologie est là pour tester une garde précise du moteur de replay :

| pathologie              | ce qu'elle éprouve                                        |
|-------------------------|-----------------------------------------------------------|
| prix vide / non numérique | la ligne est écartée, pas le replay entier               |
| volume fractionnaire    | un volume n'est pas un nombre réel                        |
| `side` inconnu          | rien n'est deviné à la place de l'opérateur               |
| horodatage qui RECULE   | le tape ne remonte pas le temps                           |
| `bid_vol` vide          | absent ≠ zéro (D-055 : hors profondeur ≠ taille nulle)    |
| trou de plusieurs secondes | la cadence réelle a des vides, pas seulement des rafales |
| rafale de ticks         | c'est ce que cherche `TAPE_BURST` — un tape uniforme ment |

Déterministe : même graine, même fichier. Un jeu d'essai qui change à chaque exécution rend
tout écart inexplicable.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

COLONNES = ["timestamp", "price", "volume", "side", "bid_vol", "ask_vol"]
DEFAUT = Path(__file__).with_name("sample_orderbook.csv")
DEBUT_TS = 1_785_600_000.0          # epoch fixe : aucune horloge lue, le fichier est reproductible


def generer(chemin: Path = DEFAUT, n: int = 500, *, propre: bool = False,
            graine: int = 42, prix_initial: float = 5000.0, tick: float = 0.25) -> dict:
    """Écrit le CSV et rend le compte de ce qui a été semé, pathologie par pathologie."""
    rng = random.Random(graine)
    seme: dict[str, int] = {}
    lignes: list[dict] = []
    ts, prix = DEBUT_TS, prix_initial

    for i in range(n):
        # Cadence réaliste : la plupart des ticks sont serrés, avec des rafales et des trous.
        # Un pas constant produirait un tape que `TAPE_BURST` ne pourrait jamais qualifier.
        if not propre and i % 97 == 0 and i:
            ts += rng.uniform(3.0, 9.0)                     # trou de séance
            seme["trou"] = seme.get("trou", 0) + 1
        elif not propre and i % 31 == 0:
            ts += 0.004                                     # rafale
            seme["rafale"] = seme.get("rafale", 0) + 1
        else:
            ts += rng.uniform(0.05, 0.4)

        prix = round(round((prix + rng.choice((-1, 0, 1)) * tick) / tick) * tick, 4)
        ligne = {
            "timestamp": f"{ts:.3f}",
            "price": f"{prix:.2f}",
            "volume": str(rng.randint(1, 50)),
            "side": rng.choice(("BUY", "SELL")),
            "bid_vol": f"{rng.uniform(10, 400):.1f}",
            "ask_vol": f"{rng.uniform(10, 400):.1f}",
        }

        if not propre:
            if i % 61 == 7:
                ligne["price"] = ""                         # prix manquant
                seme["prix vide"] = seme.get("prix vide", 0) + 1
            elif i % 61 == 13:
                ligne["price"] = "n/a"                      # prix illisible
                seme["prix illisible"] = seme.get("prix illisible", 0) + 1
            elif i % 61 == 23:
                ligne["volume"] = "3.5"                     # volume fractionnaire
                seme["volume fractionnaire"] = seme.get("volume fractionnaire", 0) + 1
            elif i % 61 == 31:
                ligne["side"] = "UNKNOWN"                   # côté non renseigné
                seme["côté inconnu"] = seme.get("côté inconnu", 0) + 1
            elif i % 61 == 43:
                ligne["timestamp"] = f"{ts - 12.0:.3f}"     # désync d'horloge : le tape recule
                seme["horodatage qui recule"] = seme.get("horodatage qui recule", 0) + 1
            if i % 17 == 5:
                ligne["bid_vol"] = ""                       # profondeur INCONNUE, pas nulle
                seme["profondeur absente"] = seme.get("profondeur absente", 0) + 1
        lignes.append(ligne)

    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(lignes)
    return {"chemin": str(chemin), "lignes": len(lignes), "propre": propre, "seme": seme}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Génère un tape d'essai pour le mode Replay.")
    p.add_argument("--sortie", type=Path, default=DEFAUT)
    p.add_argument("--ticks", type=int, default=500)
    p.add_argument("--propre", action="store_true",
                   help="sans pathologies — à n'utiliser que pour comparer (CLAUDE §4 : un mock "
                        "trop propre est un piège)")
    p.add_argument("--graine", type=int, default=42)
    args = p.parse_args(argv)
    bilan = generer(args.sortie, args.ticks, propre=args.propre, graine=args.graine)
    print(f"écrit : {bilan['chemin']} · {bilan['lignes']} lignes"
          + (" · SANS pathologies" if bilan["propre"] else ""))
    for nom, n in sorted(bilan["seme"].items()):
        print(f"   semé : {n:>3}× {nom}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
