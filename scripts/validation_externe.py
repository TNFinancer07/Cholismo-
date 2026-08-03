#!/usr/bin/env python3
"""Validation RÉELLE des sources externes Niveau 3 — à lancer depuis une machine avec du réseau.

    cd backend
    FINNHUB_API_KEY=... FRED_API_KEY=... .venv/bin/python ../scripts/validation_externe.py

**Pourquoi ce script existe.** Le paquet `app/external` a été écrit dans un environnement dont
l'egress est bloqué : aucune réponse réelle de Finnhub n'a jamais été vue. Le format vient de la
documentation, et `FinnhubCalendar` porte donc `verified=False` (doctrine C2, D-057). Ce script
est la seule chose qui puisse lever ce doute — et il classe les échecs **par CAUSE**, parce que
« ça ne marche pas » n'a jamais aidé personne :

    ✗ RÉSEAU   — on n'a pas joint le service (proxy, DNS, pare-feu)
    ✗ SERVICE  — le service a RÉPONDU et refusé (clé, plan, quota)
    ✗ PARSING  — la réponse est arrivée mais notre lecture ne la comprend pas ← le cas qui compte
    ✗ CRASH    — notre code a levé, c'est un défaut chez nous

Un `✗ PARSING` est le résultat le plus utile : il veut dire que le format réel diffère de la
documentation, et l'échantillon affiché en dessous dit exactement en quoi.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.external.economic_calendar import (FINNHUB_URL, FinnhubCalendar,  # noqa: E402
                                            parse_finnhub_json)
from app.external.vix import FredVix  # noqa: E402
from app.providers.connectors import redact  # noqa: E402

LARGEUR = 78


def titre(texte: str) -> None:
    print(f"\n{texte}\n{'─' * min(LARGEUR, len(texte))}")


def essayer_finnhub(cle: str) -> None:
    titre("1. Calendrier économique — Finnhub")
    if not cle:
        print("  ○ IGNORÉ — FINNHUB_API_KEY absente (ce n'est pas un échec : rien n'a été tenté)")
        return
    url = f"{FINNHUB_URL}?token={cle}"
    print(f"  URL : {redact(url)}")
    brut = ""
    try:
        brut = FinnhubCalendar(cle)._http(url)          # l'appel nu, pour voir la RÉPONSE
    except Exception as exc:
        nom = type(exc).__name__
        code = getattr(exc, "code", None)
        if code is not None:
            print(f"  ✗ SERVICE — HTTP {code} : le service a répondu et refusé.")
            print("             Le calendrier éco Finnhub est payant sur la plupart des plans :")
            print("             vérifier le PLAN avant la clé.")
        else:
            print(f"  ✗ RÉSEAU — {nom} : le service n'a pas été joint (proxy, DNS, pare-feu).")
        return
    print(f"  réponse reçue : {len(brut)} octets")
    events = parse_finnhub_json(brut)
    if events is None:
        print("  ✗ PARSING — la réponse est arrivée mais notre lecture ne la comprend pas.")
        print("             C'est LE cas qui compte : le format réel diffère de la doc.")
        print(f"  échantillon : {brut[:400]}")
        return
    haut = [e for e in events if e["impact"] == "HIGH"]
    print(f"  ✓ OK — {len(events)} événements lus, dont {len(haut)} à fort impact")
    for e in sorted(haut, key=lambda x: x["ts"])[:5]:
        quand = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(e["ts"]))
        print(f"      {quand}  {e['country'] or '??'}  {e['name']}")
    if not events:
        print("      (liste VIDE — c'est un état connu, pas une panne : semaine calme ?)")
    print("\n  → Si cette liste est cohérente avec le calendrier public, le format est CONFIRMÉ :")
    print("    passer `verified=True` sur FinnhubCalendar et le noter dans DECISIONS.md.")
    print("  → VÉRIFIER SURTOUT L'HEURE ci-dessus contre l'heure publique de la publication.")
    print("    Une heure d'écart = l'hypothèse UTC est fausse, et toute la fenêtre de blackout")
    print("    est décalée sans que rien ne le signale (piège n° 1).")


def essayer_fred(cle: str) -> None:
    titre("2. VIX — FRED VIXCLS")
    if not cle:
        print("  ○ IGNORÉ — FRED_API_KEY absente")
        return
    try:
        res = FredVix(api_key=cle).fetch(now=time.time())
    except Exception:
        print("  ✗ CRASH — notre code a levé, c'est un défaut chez nous :")
        traceback.print_exc(limit=3)
        return
    if res.ok:
        print(f"  ✓ OK — {res.resume}")
        print("  → `as_of` est la date de CLÔTURE : en séance, cette valeur décrit la veille.")
    else:
        motif = res.error or ""
        cause = "SERVICE" if "HTTP" in motif or "refus" in motif else \
                "RÉSEAU" if "injoignable" in motif else "PARSING"
        print(f"  ✗ {cause} — {motif}")


def main() -> int:
    print("Validation des sources externes Niveau 3 (D-062)")
    print("Les échecs sont classés PAR CAUSE : « ça ne marche pas » n'aide personne.")
    essayer_finnhub(os.getenv("FINNHUB_API_KEY", "").strip())
    essayer_fred(os.getenv("FRED_API_KEY", "").strip())
    titre("3. Rappel")
    print("  Tant qu'un ✓ OK n'a pas été obtenu sur Finnhub, la source reste marquée")
    print("  SOURCE_NON_VERIFIEE jusque dans le panneau — c'est voulu (doctrine C2).")
    print("  Le repli hors ligne : EXTERNAL_CALENDAR_FILE=<fichier.json>, forme")
    print(f"  {json.dumps([{'ts': 1785600000, 'name': 'NFP', 'impact': 'HIGH', 'country': 'US'}])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
