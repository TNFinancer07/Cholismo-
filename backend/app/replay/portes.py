"""Ce qu'un tape donné peut RÉELLEMENT alimenter — les quatre portes, mesurées (D-061).

    python -m app.replay.portes app/replay/sample_orderbook.csv
    python -m app.replay.portes export_bookmap.csv --dialecte bookmap

Compagnon de `inspect.py`. Celui-ci répond « ton fichier est-il lisible ? » ; celui-là répond la
question d'après, la seule qui compte avant de rejouer une séance : **est-ce que ce tape contient
de quoi faire parler B1-B4 ?**

Deux sections, et elles ne disent pas la même chose :

1. **SCÈNES** — présente uniquement si un fichier `.truth.json` accompagne le CSV (tape fabriqué
   par `mock_data_generator`). Chaque phénomène scripté est mesuré sur sa propre fenêtre, avec
   son niveau de mur et son instant de sweep issus de la VÉRITÉ TERRAIN, jamais d'une détection.
   Une scène qui ne fait pas réagir sa porte est un défaut.
2. **BALAYAGE** — sur n'importe quel tape, y compris un export réel. On interroge les portes à
   intervalles réguliers, à la fenêtre RÉELLE du terminal, et on compte combien de fois chacune
   sait répondre. C'est le seul chiffre honnête à regarder avant de brancher un enregistrement :
   une porte muette 95 % du temps ne servira à rien en séance, et il vaut mieux le savoir avant.

Le carnet est reconstruit avec le `TapeBook` de `ReplayDataSource` — celui que le terminal
utilise réellement. Mesurer sur une autre reconstruction dirait quelque chose sur cet outil, pas
sur le terminal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..datasource.replay import TapeBook
from ..orderflow import OrderFlowSnapshot, compute_snapshot
from .dialects import DIALECTES
from .replay_engine import ReplayEngine, ReplaySummary, Tick

PORTES = (("B1", "rechargement de mur"), ("B2", "fraction agresseur acheteur"),
          ("B3", "rejet d'extrême"), ("B4", "essoufflement post-sweep"))
LARGEUR = 100


def _couper(texte: str) -> str:
    """Troncature VISIBLE. Couper en silence ferait lire une phrase amputée comme une phrase
    entière — le motif « trou d'observation de 3.33s dans le… » perdrait justement son chiffre."""
    return texte if len(texte) <= LARGEUR else texte[:LARGEUR - 1] + "…"


def valeurs(s: OrderFlowSnapshot) -> dict[str, Optional[float]]:
    """Accès par nom LITTÉRAL, jamais par `getattr` : un champ renommé doit casser à la
    compilation, pas rendre une porte silencieuse en production."""
    return {"B1": s.wall_refill_ratio, "B2": s.tape_aggressor_buy_fraction,
            "B3": s.rejection_delta_ratio, "B4": s.post_sweep_aggression_ratio}


def charger(chemin: Path, dialecte: Optional[str] = None
            ) -> tuple[list[Tick], list[dict[str, Any]], list[dict[str, Any]], ReplaySummary]:
    """`(ticks, prints, books, bilan)` — exactement ce que le terminal verrait de ce fichier."""
    mapping = DIALECTES[dialecte] if dialecte else None
    moteur = ReplayEngine(str(chemin), lambda _t: None, mapping=mapping)
    ticks: list[Tick] = []
    prints: list[dict[str, Any]] = []
    books: list[dict[str, Any]] = []
    book = TapeBook(tick=config.PRICE_TICK)
    bilan = ReplaySummary()
    for tick, bilan in moteur.iter_ticks():
        ticks.append(tick)
        prints.append({"ts": tick["timestamp"], "price": tick["price"], "size": tick["volume"],
                       "side": tick["side"], "seq": len(prints)})
        book.update(tick)
        payload = book.payload()
        if payload is not None:
            books.append({"ts": tick["timestamp"], **payload})
    return ticks, prints, books, bilan


def _motif(snap: OrderFlowSnapshot, porte: str) -> str:
    for m in snap.missing:
        if m.startswith(porte):
            return m.split(" : ", 1)[-1]
    return "sans motif"


def section_scenes(chemin: Path, prints: list[dict[str, Any]],
                   books: list[dict[str, Any]]) -> None:
    sidecar = chemin.with_name(chemin.name + ".truth.json")
    if not sidecar.exists():
        print("SCÈNES     aucun fichier de vérité terrain à côté du CSV — section omise.")
        print("           (un tape réel n'en a pas : c'est le BALAYAGE ci-dessous qui compte)")
        return
    try:
        verite = json.loads(sidecar.read_text(encoding="utf-8"))
        scenes: list[dict[str, Any]] = verite["scenes"]
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
        # Une vérité terrain illisible ne doit PAS emporter le balayage, qui lui reste valable :
        # le tape est intact, c'est son étiquette qui ne l'est pas.
        print(f"SCÈNES     {sidecar.name} ILLISIBLE ({type(exc).__name__}) — section omise.")
        print("           régénérer le tape (`python -m app.replay.mock_data_generator`) "
              "réécrit la vérité terrain avec lui.")
        return
    print(f"SCÈNES     {sidecar.name} · {len(scenes)} phénomènes scriptés")
    print("           mesurés sur LEUR fenêtre, avec mur et sweep issus de la vérité terrain\n")
    for s in scenes:
        est_sweep = s["nom"] == "sweep"
        # Le marqueur de sweep est la FIN de la rafale, pas son début : le détecteur horodate son
        # alerte à l'instant où il CONSTATE la rafale (D-067). Le placer au début mettrait toute
        # la rafale « après », et B4 mesurerait une agression soutenue là où il y a un excès.
        now = s["fin_ts"] + 1.2 if est_sweep else s["fin_ts"]
        fenetre = 8.0 if est_sweep else s["fin_ts"] - s["debut_ts"] + 0.01
        snap = compute_snapshot(now=now, prints=prints, books=books, window_s=fenetre,
                                wall_price=s["wall_price"], wall_side=s["wall_side"],
                                sweep=({"ts": s["fin_ts"],
                                        "window_s": s["fin_ts"] - s["debut_ts"]}
                                       if est_sweep else None))
        v = valeurs(snap)[s["porte"]]
        rendu = f"{v:.3f}" if v is not None else f"MUETTE — {_motif(snap, s['porte'])}"
        glyphe = "✓" if v is not None else "✕"
        print(f"  {glyphe} {s['porte']}  {s['nom']:<14} {rendu}")
        print(_couper(f"        attendu : {s['attendu']}"))


def section_balayage(ticks: list[Tick], prints: list[dict[str, Any]],
                     books: list[dict[str, Any]], pas: int) -> None:
    """Combien de fois chaque porte SAIT répondre sur ce tape, à la fenêtre réelle du terminal.

    On désigne un mur au dernier prix coté et un sweep au milieu de la fenêtre : sans cela B1 et
    B4 seraient muettes par construction (« aucun niveau désigné »), ce qui ne dirait rien du
    fichier. La question posée est donc bien « si on l'interrogeait ici, pourrait-elle répondre ? »
    """
    fenetre = config.ORDERFLOW_WINDOW_S
    compte: dict[str, int] = {p: 0 for p, _ in PORTES}
    motifs: dict[str, dict[str, int]] = {p: {} for p, _ in PORTES}
    instants = 0
    for k in range(pas, len(ticks), pas):
        now = ticks[k]["timestamp"]
        if now - ticks[0]["timestamp"] < fenetre:
            continue                                    # fenêtre incomplète : rien à conclure
        instants += 1
        snap = compute_snapshot(now=now, prints=prints, books=books, window_s=fenetre,
                                wall_price=ticks[k]["price"], wall_side="BID",
                                sweep={"ts": now - fenetre / 2})   # rafale = fenêtre par défaut
        for porte, valeur in valeurs(snap).items():
            if valeur is not None:
                compte[porte] += 1
            else:
                m = _motif(snap, porte)
                motifs[porte][m] = motifs[porte].get(m, 0) + 1
    print(f"\nBALAYAGE   fenêtre réelle {fenetre:g}s · {instants} instants interrogés")
    if not instants:
        print("           tape trop court pour une seule fenêtre complète — rien à conclure")
        return
    for porte, libelle in PORTES:
        part = compte[porte] / instants
        pire = max(motifs[porte].items(), key=lambda kv: kv[1], default=("", 0))
        silence = f"  ·  silence : {pire[0]}" if pire[1] else ""
        print(_couper(f"  {'✓' if part > 0.5 else '○' if part else '✕'} {porte} "
                      f"{libelle:<28} {compte[porte]:>4}/{instants} ({part:>4.0%}){silence}"))


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Mesure ce que les portes B1-B4 peuvent tirer d'un tape donné.")
    p.add_argument("fichier", type=Path)
    p.add_argument("--dialecte", choices=sorted(DIALECTES), default=None,
                   help="correspondance de colonnes pour un export tiers (voir `inspect`)")
    p.add_argument("--pas", type=int, default=25, help="un instant interrogé tous les N ticks")
    args = p.parse_args(argv)
    if not args.fichier.exists():
        print(f"fichier introuvable : {args.fichier}")
        return 2

    ticks, prints, books, bilan = charger(args.fichier, args.dialecte)
    print(f"FICHIER    {args.fichier.name} · {len(ticks)} ticks valides · "
          f"{len(books)} carnets reconstruits")
    print(f"           {bilan.resume}\n")
    if not ticks:
        print("aucun tick exploitable — lancer `python -m app.replay.inspect` sur ce fichier.")
        return 1
    section_scenes(args.fichier, prints, books)
    section_balayage(ticks, prints, books, max(1, args.pas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
