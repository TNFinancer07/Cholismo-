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

**Ce bruit ne suffisait pas** (D-061). Des prints indépendants forment un tape statistiquement
plausible, mais sans aucun des phénomènes que le Niveau 2 mesure : pas de sweep, pas de mur qui
se recharge, pas de rejet d'extrême. B1, B3 et B4 n'y réagissaient donc jamais — rejouer mille
ticks de bruit ne prouvait rien, ni dans un sens ni dans l'autre. Le générateur intercale
désormais des **scènes scriptées** (`scenes.py`) à des instants CONNUS, et écrit leur vérité
terrain dans un fichier `.truth.json` à côté du CSV.

Une scène scriptée peut INFIRMER (un mur qu'on a fait recharger et qui ne produit aucun B1 est
un défaut) ; elle ne peut pas VALIDER (elle dit que le calculateur réagit à ce qu'on a écrit,
pas qu'il mesure le marché). Seul un vrai tape le dira.

Déterministe : même graine, même fichier. Un jeu d'essai qui change à chaque exécution rend
tout écart inexplicable.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any, Optional, Sequence

from .scenes import SCENES, SEQUENCE_DEFAUT, Scene

COLONNES = ["timestamp", "price", "volume", "side", "bid_vol", "ask_vol"]
DEFAUT = Path(__file__).with_name("sample_orderbook.csv")
DEBUT_TS = 1_785_600_000.0          # epoch fixe : aucune horloge lue, le fichier est reproductible
# Ticks de bruit exigés PAR SCÈNE. En dessous, les scènes se marcheraient dessus et le « bruit »
# entre elles n'existerait plus : un tape fait de scènes bout à bout ne ressemble pas davantage à
# un marché que du bruit pur, et B4 n'aurait rien à comparer « avant le sweep ».
TICKS_DE_BRUIT_PAR_SCENE = 6


def _sillon(nom: str) -> str:
    """Nom du fichier de vérité terrain, à côté du CSV. Séparé du CSV parce qu'un tape doit
    rester un tape : y glisser une colonne « scène » ferait fuiter la réponse dans la donnée."""
    return nom + ".truth.json"


def generer(chemin: Path = DEFAUT, n: int = 500, *, propre: bool = False,
            graine: int = 42, prix_initial: float = 5000.0, tick: float = 0.25,
            scenes: Optional[Sequence[str]] = SEQUENCE_DEFAUT) -> dict[str, Any]:
    """Écrit le CSV et rend le compte de ce qui a été semé, pathologie par pathologie.

    `scenes` : phénomènes de microstructure à intercaler (`None` ou `()` pour du bruit seul).
    Ils sont indépendants de `propre` : une pathologie est une donnée ABÎMÉE, une scène est un
    phénomène de marché RÉEL. Un tape propre sans sweep reste un tape sur lequel B4 ne peut rien
    dire.
    """
    rng = random.Random(graine)
    seme: dict[str, int] = {}
    lignes: list[dict[str, str]] = []
    ts, prix = DEBUT_TS, prix_initial

    demandees = list(scenes or ())
    # Un nom inconnu est REFUSÉ, pas ignoré. Le laisser filer produirait un tape sans le
    # phénomène demandé, sans rien dire : on mesurerait ensuite B4 sur un tape sans sweep et on
    # conclurait que la porte ne marche pas. C'est la faute la plus coûteuse de tout ce module.
    inconnues = [s for s in demandees if s not in SCENES]
    if inconnues:
        raise ValueError(f"scène(s) inconnue(s) : {', '.join(inconnues)} — disponibles : "
                         f"{', '.join(sorted(SCENES))}")
    # Réparties dans le fichier, jamais collées : chaque scène doit être précédée et suivie de
    # bruit, sinon B4 n'a rien à comparer « avant le sweep » et la mesure n'a pas de sens.
    jouees: list[Scene] = []
    positions: dict[int, str] = {}
    omises = ""
    if demandees and n < TICKS_DE_BRUIT_PAR_SCENE * len(demandees):
        # Dit, jamais tu : un tape sans scène qui se croit avec est pire qu'un tape sans scène.
        omises = (f"{len(demandees)} scène(s) omise(s) : {n} ticks de bruit pour "
                  f"{TICKS_DE_BRUIT_PAR_SCENE * len(demandees)} requis")
    elif demandees:
        positions = {(k + 1) * n // (len(demandees) + 1): nom
                     for k, nom in enumerate(demandees)}

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

        nom = positions.get(i + 1)
        if nom is not None:
            # La scène part de l'état courant du marché (instant + prix) et le rend ensuite au
            # bruit : recoller le bruit sur l'ancien prix ferait un saut que personne n'a coté.
            scene = SCENES[nom](ts + rng.uniform(0.05, 0.20), prix, tick, rng)
            # AUCUNE pathologie n'est injectée dans une scène : une ligne écartée au milieu d'un
            # sweep en ferait un demi-sweep, et l'attente ne vaudrait plus rien.
            scene.debut_idx = len(lignes)
            lignes.extend(scene.lignes)
            scene.fin_idx = len(lignes) - 1
            ts, prix = scene.fin_ts, float(scene.lignes[-1]["price"])
            jouees.append(scene)

    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(lignes)
    verite = {"fichier": chemin.name, "graine": graine, "tick": tick,
              "scenes": [s.as_truth() for s in jouees]}
    chemin_verite = chemin.with_name(_sillon(chemin.name))
    if jouees:
        chemin_verite.write_text(json.dumps(verite, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    return {"chemin": str(chemin), "lignes": len(lignes), "propre": propre, "seme": seme,
            "scenes": [s.as_truth() for s in jouees], "omises": omises,
            "verite": str(chemin_verite) if jouees else None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Génère un tape d'essai pour le mode Replay.")
    p.add_argument("--sortie", type=Path, default=DEFAUT)
    p.add_argument("--ticks", type=int, default=500)
    p.add_argument("--propre", action="store_true",
                   help="sans pathologies — à n'utiliser que pour comparer (CLAUDE §4 : un mock "
                        "trop propre est un piège)")
    p.add_argument("--graine", type=int, default=42)
    p.add_argument("--sans-scenes", action="store_true",
                   help="bruit seul, sans phénomène de microstructure — B1/B3/B4 n'auront alors "
                        "rien à mesurer, ce qui est précisément le piège")
    args = p.parse_args(argv)
    bilan = generer(args.sortie, args.ticks, propre=args.propre, graine=args.graine,
                    scenes=() if args.sans_scenes else SEQUENCE_DEFAUT)
    print(f"écrit : {bilan['chemin']} · {bilan['lignes']} lignes"
          + (" · SANS pathologies" if bilan["propre"] else ""))
    for nom, n in sorted(bilan["seme"].items()):
        print(f"   semé : {n:>3}× {nom}")
    for scene in bilan["scenes"]:
        print(f"   scène : {scene['porte']} · {scene['nom']:<12} "
              f"t+{scene['debut_ts'] - DEBUT_TS:7.2f}s → t+{scene['fin_ts'] - DEBUT_TS:7.2f}s "
              f"· {scene['attendu']}")
    if bilan["omises"]:
        print(f"   ⚠ {bilan['omises']}")
    if bilan["verite"]:
        print(f"   vérité terrain : {bilan['verite']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
