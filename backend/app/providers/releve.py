"""Relevé des identifiants C2 — l'outil de la séance de catalogue (D-065).

    python -m app.providers.releve                          # ce qu'il reste à relever, et l'enjeu
    python -m app.providers.releve nfa BOP.Q.US.BFNA_BP6_USD # valider un identifiant candidat

**Pourquoi un outil plutôt qu'une liste.** La doctrine C2 (D-057) dit « ne pas coder l'identifiant
en dur sans être passé par le catalogue ». Six lignes attendent ce passage. Le risque n'est pas de
les oublier — c'est d'en relever un qui *ressemble* au bon : un identifiant plausible qui répond
200 et rend une série sans rapport se code aussi facilement que le vrai, et rien ne le signalera
ensuite. L'outil pose donc les trois questions dans l'ordre :

1. **Est-ce que ça répond ?** — URL construite depuis le registre, appel réel, échec classé PAR
   CAUSE (réseau · service · parsing) parce que « ça ne marche pas » n'aide personne.
2. **Est-ce que c'est LISIBLE ?** — le connecteur en tire-t-il des observations, et lesquelles ?
   Premières et dernières dates affichées : c'est là qu'on voit qu'on a ramené la mauvaise série.
3. **Qu'est-ce que ça DÉBLOQUE ?** — simulation contre un registre hypothétique, sans rien
   modifier sur disque. Un identifiant qui n'ouvre aucun champ n'est pas une priorité de séance.

L'étape 3 est le tri utile : sur les six lignes C2, toutes ne se valent pas. `r_star_us` ne
débloque rien tant que `r_star_ez` reste C3 ; `nairu_ez` ne débloque rien tant que D1 manque de
jambes zone euro. L'outil le dit au lieu de laisser passer une séance sur la mauvaise ligne.

Rien n'est écrit sur disque : le relevé se conclut par une modification MANUELLE du registre,
faite par un humain qui a vu la donnée. C'est le sens de C2.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import Any, Optional

from . import connectors as cx
from .catalog import BY_KEY, CATALOG, Confidence, Kind, SeriesSpec, fetch_block_reason
from .client import client_for_provider, has_client

LARGEUR = 100


def lignes_a_relever() -> tuple[SeriesSpec, ...]:
    """Lignes dont l'identifiant reste à confirmer. **OBSERVED uniquement** : une ligne DÉRIVÉE
    marquée C2 (`uip_implied`) ne se relève pas au catalogue, elle se calcule — l'inclure ferait
    partir l'opérateur chercher un identifiant qui n'existe nulle part."""
    return tuple(s for s in CATALOG
                 if s.confidence is Confidence.C2 and s.kind is Kind.OBSERVED)


def _registre_simule(cles: Any, identifiant: str = "CANDIDAT") -> dict[str, SeriesSpec]:
    """Copie du registre où les clés données seraient relevées et vérifiées. **Rien n'est modifié
    sur disque** : on répond à « et si ? », on ne décide pas à la place de l'opérateur."""
    table = dict(BY_KEY)
    for cle in ([cles] if isinstance(cles, str) else cles):
        table[cle] = dataclasses.replace(BY_KEY[cle], identifier=identifiant,
                                         confidence=Confidence.C1)
    return table


def debloque(cles: Any, identifiant: str = "CANDIDAT") -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(champs_debloques, series_debloquees)` si `cles` étaient relevées — une clé ou plusieurs.

    **Le relevé se raisonne par LOT.** Prise seule, `nfa` n'ouvre rien puisque `tot` reste
    bloquée ; ensemble elles ouvrent `beer_z`. Un outil qui ne saurait juger qu'une ligne à la
    fois ferait conclure que le relevé ne sert à rien.

    La simulation passe par `Recipe.blocage(registry=…)` et `fetch_block_reason(registry=…)` :
    aucune règle n'est réécrite ici, sinon elle divergerait de celle qui décide vraiment.
    """
    # Import LOCAL : le pont vit au-dessus du registre, et `providers` ne doit pas en dépendre à
    # l'import (même motif que les délégations d'URL entre `connectors` et les clients).
    from ..external.macro_series import RECIPES

    simule = _registre_simule(cles, identifiant)
    demandees = {cles} if isinstance(cles, str) else set(cles)
    champs = tuple(r.field for r in RECIPES
                   if r.blocage() is not None and r.blocage(simule) is None)
    series = tuple(s.key for s in CATALOG
                   if s.key not in demandees
                   and fetch_block_reason(s.key) is not None
                   and fetch_block_reason(s.key, registry=simule) is None)
    return champs, series


def valider(cle: str, identifiant: str) -> int:
    """Les trois questions, dans l'ordre. Code de sortie non nul si l'identifiant ne tient pas."""
    spec = BY_KEY.get(cle)
    if spec is None:
        print(f"✕ « {cle} » n'est pas au registre — rien à relever.")
        return 2
    if spec.confidence is not Confidence.C2 or spec.kind is not Kind.OBSERVED:
        print(f"○ {cle} n'est pas une ligne C2 observée ({spec.confidence.value}, "
              f"{spec.kind.value}) — rien à relever ici.")
        return 2

    print(f"RELEVÉ  {cle} · {spec.label}")
    print(f"        fournisseur {spec.provider.value} · dimension {spec.dimension} · "
          f"jambe {spec.leg.value}")
    print(f"        piste       {spec.catalog_hint or '—'}")
    print(f"        candidat    {identifiant}\n")

    seule, _ = debloque(cle, identifiant)
    lot = [x.key for x in lignes_a_relever()]
    ensemble, _ = debloque(lot, identifiant)
    sans = debloque([x for x in lot if x != cle], identifiant)[0]
    indispensable = tuple(sorted(set(ensemble) - set(sans)))
    print("3. CE QUE ÇA DÉBLOQUE (simulation — rien n'est écrit sur disque)")
    print(f"   cette ligne SEULE     : {', '.join(seule) or 'aucun champ'}")
    print(f"   indispensable à       : {', '.join(indispensable) or 'aucun champ'}")
    if not seule and indispensable:
        print("   → seule elle n'ouvre rien, mais sans elle ces champs restent fermés : le")
        print("     relevé se raisonne par LOT, pas ligne à ligne.")
    if not seule and not indispensable:
        print("   → cette ligne n'ouvre rien aujourd'hui, même avec les autres. Elle attend")
        print("     une levée de blocage d'une autre nature (C3, paramètre, ou dérivation).")
    print()

    if not has_client(spec.provider):
        print(f"○ 1-2. NON VÉRIFIABLE ICI — aucun client écrit pour {spec.provider.value}.")
        print("       relever l'identifiant à la main, puis écrire le connecteur.")
        return 1

    print("1-2. APPEL RÉEL et LECTURE")
    try:
        client = client_for_provider(spec.provider)
    except cx.SeriesBlocked as exc:
        print(f"   ✕ {exc}")
        return 1
    try:
        # Entrée par IDENTIFIANT, pas par clé du registre : la ligne est encore C2, donc le
        # portillon la refuserait — à juste titre pour la production, à tort pour un relevé.
        res = client._by_identifier(identifiant)
    except cx.SeriesBlocked as exc:
        # Le connecteur REFUSE la forme de l'identifiant. C'est le résultat le plus utile du
        # relevé, pas une panne : on a recopié quelque chose qui ne ressemble pas à ce que ce
        # fournisseur attend, et on l'apprend AVANT de le figer au registre.
        print(f"   ✕ IDENTIFIANT REFUSÉ — {exc}")
        print("     retourner au catalogue : la forme attendue est décrite dans le message.")
        return 1
    except Exception as exc:
        print(f"   ✕ CRASH — {type(exc).__name__} : {exc}")
        print("     c'est un défaut CHEZ NOUS, pas un mauvais identifiant.")
        return 1
    if res.series is None:
        motif = res.error or "sans motif"
        cause = ("RÉSEAU" if "injoignable" in motif else
                 "SERVICE" if "HTTP" in motif or "refus" in motif or "quota" in motif else
                 "PARSING")
        print(f"   ✕ {cause} — {motif}")
        if cause == "PARSING":
            print("     LE CAS QUI COMPTE : le service a répondu, notre lecture ne comprend")
            print("     pas. L'identifiant peut être bon et le format inattendu — ne pas")
            print("     conclure trop vite qu'il est faux.")
        return 1
    obs = res.series.observations
    print(f"   ✓ {len(obs)} observation(s) · {obs[0].date} → {obs[-1].date}")
    print(f"     premières : {[o.value for o in obs[:3]]}")
    print(f"     dernières : {[o.value for o in obs[-3:]]}")
    print()
    print("→ VÉRIFIER À L'ŒIL que ces dates et ces ordres de grandeur sont ceux de la série")
    print("  ATTENDUE. Un identifiant plausible qui ramène la mauvaise série répond 200 aussi,")
    print("  et plus rien ne le signalera ensuite.")
    print(f"  Si c'est la bonne : passer `{cle}` en C1 dans `catalog.py` avec cet identifiant,")
    print("  puis `python -m app.providers` et `python -m app.external.macro_series`.")
    return 0


def inventaire() -> str:
    lignes = [
        "CHOLISMO · lignes C2 à relever au catalogue (D-065)",
        f"{len(lignes_a_relever())} ligne(s) · une séance suffit · lecture seule, aucun appel réseau",
        "",
        "  Trié par ENJEU : ce que chaque relevé débloquerait réellement aujourd'hui.",
        "",
    ]
    lot = [s.key for s in lignes_a_relever()]
    ensemble, _ = debloque(lot)
    lignes.append(f"  Relevé COMPLET des {len(lot)} → débloque : "
                  f"{', '.join(ensemble) if ensemble else 'AUCUN champ'}")
    lignes.append("")
    rangs = []
    for spec in lignes_a_relever():
        seule, _ = debloque(spec.key)
        # Le relevé se raisonne par LOT : `nfa` seule n'ouvre rien puisque `tot` reste bloquée,
        # mais sans elle `beer_z` reste fermé. Juger ligne à ligne ferait conclure à tort que
        # ces relevés ne servent à rien.
        sans, _ = debloque([k for k in lot if k != spec.key])
        indispensable = tuple(sorted(set(ensemble) - set(sans)))
        rangs.append((len(seule), len(indispensable), spec, seule, indispensable))
    for _, _, spec, seule, indispensable in sorted(rangs,
                                                   key=lambda r: (-r[0], -r[1], r[2].key)):
        if seule:
            enjeu = f"débloque {', '.join(seule)}"
        elif indispensable:
            enjeu = f"INDISPENSABLE à {', '.join(indispensable)} (avec d'autres lignes)"
        else:
            enjeu = "n'ouvre rien aujourd'hui, même avec les autres"
        lignes.append(f"  {spec.key:<14} {spec.provider.value:<12} {enjeu}")
        lignes.append(f"                 piste : {spec.catalog_hint or '—'}"[:LARGEUR])
    lignes += [
        "",
        "Protocole, pour chaque ligne",
        "─" * 60,
        "  1. ouvrir le catalogue du fournisseur à la piste indiquée ;",
        "  2. y lire l'identifiant EXACT (pas un identifiant qui lui ressemble) ;",
        "  3. `python -m app.providers.releve <clé> <identifiant>` — il dit ce qui se débloque ;",
        "  4. si la donnée lue correspond : passer la ligne en C1 dans `catalog.py` ;",
        "  5. `python -m app.providers` puis `python -m app.external.macro_series` pour constater.",
        "",
        "  Le passage en C1 est MANUEL, par un humain qui a vu la donnée. C'est tout le sens",
        "  de C2 : un identifiant plausible se code aussi facilement que le bon.",
    ]
    return "\n".join(lignes)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Relevé des identifiants C2 au catalogue.")
    p.add_argument("cle", nargs="?", help="clé du registre à relever (ex. nfa)")
    p.add_argument("identifiant", nargs="?", help="identifiant candidat lu au catalogue")
    args = p.parse_args(argv)
    if not args.cle:
        print(inventaire())
        return 0
    if not args.identifiant:
        champs, series = debloque(args.cle)
        spec: Any = BY_KEY.get(args.cle)
        if spec is None:
            print(f"✕ « {args.cle} » n'est pas au registre.")
            return 2
        print(f"{args.cle} · piste : {spec.catalog_hint or '—'}")
        print(f"débloquerait : {', '.join(champs) or 'aucun champ'} · "
              f"{', '.join(series) or 'aucune série'}")
        print("\nDonner l'identifiant candidat pour le valider :")
        print(f"  python -m app.providers.releve {args.cle} <IDENTIFIANT>")
        return 0
    return valider(args.cle, args.identifiant)


if __name__ == "__main__":
    sys.exit(main())
