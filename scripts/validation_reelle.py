#!/usr/bin/env python3
"""Validation END-TO-END contre les VRAIS fournisseurs — à lancer hors de l'environnement d'agent.

    cd backend && FRED_API_KEY=... .venv/bin/python ../scripts/validation_reelle.py

Pourquoi ce script existe : la politique d'egress de l'environnement de développement refuse le
CONNECT vers les cinq fournisseurs (403 sur le tunnel). Tous les essais menés jusqu'ici passent
donc par des serveurs locaux, et les formats de réponse viennent des SPECS, pas d'une réponse
observée. C'est la seule chose que le dépôt ne peut pas prouver depuis l'intérieur.

Ce script exerce les clients maison contre les vrais services et rend un verdict par ligne. Il
ne modifie rien, n'écrit rien, ne passe aucun ordre (§2.1). La BCE, Eurostat, la Bundesbank, la
CFTC et Yahoo ne demandent AUCUNE clé : seul FRED en a besoin, et son absence n'empêche pas les
autres de répondre.

Ce qu'il faut regarder dans la sortie, dans cet ordre :
  1. les lignes ✗ PARSING — le service a répondu mais le parser n'a rien su en tirer : c'est
     LÀ que la spec se trompait sur le format, et c'est l'inconnue principale ;
  2. les lignes ✗ REFUS — le service refuse (clé, quota, clé de série non confirmée) ; pour une
     ligne C2 c'est attendu, pour une C1 c'est une clé de la spec à corriger ;
  3. les ✓ — nombre d'observations et dernière période, à comparer au bon sens.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.isdir(os.path.join(_RACINE, "backend")):
    sys.path.insert(0, os.path.join(_RACINE, "backend"))

from app.providers import catalog as cat                                    # noqa: E402
from app.providers.client import client_for                                 # noqa: E402
from app.providers.connectors import SeriesBlocked                          # noqa: E402

# Une ligne C1 par fournisseur : de quoi prouver le format de chacun sans marteler les services.
CIBLES = ["vixcls", "hicp_ez", "unrate_ez", "bund_nominal", "reer", "dax", "cot_fx"]
EXTRA = {"cot_fx": {"value_field": "noncomm_positions_long_all"}}


def main() -> int:
    print(f"Validation réelle · {len(CIBLES)} lignes · lecture seule, aucun ordre\n")
    ok = refus = 0
    causes: dict[str, int] = {}
    for key in CIBLES:
        spec = cat.BY_KEY[key]
        etiquette = f"{key:<14} {spec.provider.value:<14}"
        try:
            client = client_for(key)
            debut = time.perf_counter()
            result = client.fetch_catalog(key, **EXTRA.get(key, {}))
            ms = (time.perf_counter() - debut) * 1000
        except SeriesBlocked as exc:
            print(f"  ✗ REFUS    {etiquette} {exc}")
            refus += 1
            continue
        except Exception:                                   # noqa: BLE001 — diagnostic
            print(f"  ✗ CRASH    {etiquette}\n{traceback.format_exc()}")
            causes["crash"] = causes.get("crash", 0) + 1
            continue
        if result.series is None:
            # Classer par CAUSE, pas par « il n'y a pas de série ». Étiqueter une panne réseau
            # « PARSING » enverrait chercher un défaut de format qui n'existe pas — la confusion
            # même que ce paquet passe son temps à défaire.
            motif = result.error or ""
            if "injoignable" in motif:
                etat, compteur = "✗ RÉSEAU ", "reseau"
            elif "refusé" in motif or "quota" in motif or "inconnue de" in motif or "panne" in motif:
                etat, compteur = "✗ SERVICE", "service"
            else:
                etat, compteur = "✗ PARSING", "parsing"
            print(f"  {etat}  {etiquette} {motif}")
            causes[compteur] = causes.get(compteur, 0) + 1
            continue
        obs = result.series.observations
        print(f"  ✓ OK       {etiquette} {len(obs):>6} obs · dernière {obs[-1].date} = "
              f"{obs[-1].value} · {result.series.dropped} trou(s) · {ms:.0f} ms")
        ok += 1
    detail = " · ".join(f"{n} {c}" for c, n in sorted(causes.items())) or "aucun échec"
    print(f"\n{ok} succès · {refus} refus de registre · {detail}")
    print("PARSING est le verdict le plus utile : il dit que la spec se trompait sur le format, "
          "et c'est précisément ce qu'un mock ne peut pas révéler.")
    print("RÉSEAU en série signifie que la machine n'a pas accès aux fournisseurs — c'est "
          "l'environnement qu'il faut changer, pas le code.")
    return 0 if not causes.get("parsing") and not causes.get("crash") else 1


if __name__ == "__main__":
    raise SystemExit(main())
