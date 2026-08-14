"""`python -m app.replay.inspect <export.csv>` — que contient VRAIMENT ce fichier ? (D-060)

À lancer sur un export Bookmap (ou n'importe quel export tiers) **avant** tout rejeu. La commande
ne rejoue rien, n'écrit rien : elle lit un échantillon et montre ce qu'elle voit.

Ce qu'elle répond, dans l'ordre où ça compte :
  1. le SÉPARATEUR et les colonnes réellement présentes ;
  2. les CANDIDATS pour chaque rôle du tape — et elle refuse de choisir quand plusieurs sont
     plausibles, parce que se tromper de colonne produit un tape faux et crédible ;
  3. l'UNITÉ D'HORODATAGE déduite de l'ordre de grandeur — le piège n° 1 d'un export tiers :
     des millisecondes lues comme des secondes placent la séance en l'an 56 000, et toutes les
     fenêtres d'order flow deviennent absurdes en restant plausibles ;
  4. les valeurs de CÔTÉ observées, dont celles qu'on ne sait pas traduire.

Elle rend un extrait de code prêt à coller : la `Mapping` proposée, à relire avant usage.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .dialects import ROLES_FACULTATIFS, ROLES_REQUIS, sniff

LARGEUR = 100
ECHANTILLON_OCTETS = 200_000            # de quoi voir l'en-tête et quelques dizaines de lignes


def rapport(texte: str) -> str:
    diag = sniff(texte)
    if diag is None:
        return ("Ce fichier n'est pas un CSV lisible — ni en-tête, ni lignes exploitables.\n"
                "Vérifier qu'il s'agit bien de l'export TABULAIRE et non d'un enregistrement "
                "binaire (Bookmap enregistre nativement dans son propre format).")
    out = [
        f"Séparateur détecté : « {diag.delimiter!r} » · {len(diag.columns)} colonnes · "
        f"{diag.rows_read} lignes lues",
        "Colonnes : " + ", ".join(diag.columns),
        "",
        "RÔLES DU TAPE — candidats trouvés (la commande ne choisit pas à votre place) :",
    ]
    for role in ROLES_REQUIS + ROLES_FACULTATIFS:
        marque = "  " if role in ROLES_FACULTATIFS else "* "
        trouves = diag.candidates.get(role, [])
        if not trouves:
            manque = "NON TROUVÉ — à désigner à la main" if role in ROLES_REQUIS \
                else "absent (facultatif : le tape sera sans profondeur, ce qui est la vérité)"
            out.append(f"  {marque}{role:<10} {manque}")
        elif len(trouves) == 1:
            out.append(f"  {marque}{role:<10} → {trouves[0]}")
        else:
            out.append(f"  {marque}{role:<10} → {trouves[0]}   (AMBIGU : {', '.join(trouves)})")
    out += ["", f"HORODATAGE : {diag.time_unit} — {diag.time_note}"]
    if diag.time_unit == "?":
        out.append("  ⚠ tant que l'unité n'est pas tranchée, ne rien rejouer : une erreur "
                   "d'unité produit des fenêtres absurdes mais crédibles.")
    if diag.side_values:
        out.append(f"CÔTÉS observés : {', '.join(diag.side_values)}")
        if diag.side_unknown:
            out.append(f"  ⚠ NON TRADUITS : {', '.join(diag.side_unknown)} — préciser leur sens "
                       "dans `side_values`. Attention : « bid » comme côté AGRESSÉ veut dire une "
                       "VENTE ; l'inverse inverserait tout le delta.")
    if diag.sample:
        out += ["", "Trois premières lignes :"]
        for ligne in diag.sample:
            out.append("  " + " · ".join(f"{k}={v}" for k, v in list(ligne.items())[:6]))
    propose = diag.proposed()
    out += ["", f"VERDICT : {diag.resume}"]
    if propose is None:
        out.append("Correspondance NON proposée : un rôle requis reste ambigu ou l'unité de "
                   "temps est indéterminée. Compléter à la main plutôt que de laisser deviner.")
    else:
        out += ["", "Correspondance proposée — à RELIRE avant usage :", "",
                "    Mapping(", f"        columns={propose.columns!r},",
                f'        time_unit="{propose.time_unit}", delimiter={propose.delimiter!r},',
                '        label="Bookmap (confirmé le …)", verified=True)', "",
                "Puis : ReplayEngine(chemin, callback, mapping=…)"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reconnaître le format d'un export de tape.")
    p.add_argument("fichier", type=Path)
    args = p.parse_args(argv)
    if not args.fichier.exists():
        print(f"fichier introuvable : {args.fichier}")
        return 1
    with open(args.fichier, "r", newline="", encoding="utf-8", errors="replace") as f:
        texte = f.read(ECHANTILLON_OCTETS)
    print(f"═ {args.fichier} ".ljust(LARGEUR, "═"))
    print(rapport(texte))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
