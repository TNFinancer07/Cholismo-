"""Extracteur de contexte historique (D-085, phase P2).

    python -m app.mbo.build_context --from 2025-03-03 --to 2025-03-07 -o contexte.json

Construit le `contexte.json` que `--context` consomme, en interrogeant FRED (VIX) et Finnhub
(calendrier) **sur une fenêtre passée**.

---

**La différence avec `app/external/`, et pourquoi ce module existe.**

`FredVix.fetch(now=…)` et `FinnhubCalendar.fetch(now=…)` servent le terminal LIVE : ils
demandent « quelle est la valeur maintenant ». Les appeler pour un rejeu injecterait la valeur
d'aujourd'hui dans une séance d'alors (D-084). Ici on demande **une fenêtre datée**, et chaque
point conserve **son propre horodatage de publication** — c'est ce qui permet à la jointure
point-in-time de ne jamais regarder devant.

Les parseurs, eux, sont réutilisés tels quels (`parse_fred_series`, `parse_finnhub_json`) : ce
sont eux qui font autorité sur les formats, et en écrire une seconde version les ferait diverger.

**Le VIX est daté de sa SÉANCE, pas de sa publication intraday.** `VIXCLS` est une série de
clôtures quotidiennes. Une clôture du 3 mars n'est connue qu'après la clôture du 3 mars : la
dater à 00:00 la rendrait disponible toute la journée du 3, ce qui serait du lookahead sur la
séance qu'on rejoue. Chaque observation est donc horodatée à la **clôture du cash US** (16:00
ET), l'instant où elle devient réellement connue.

**Un jeu vide n'est pas une erreur silencieuse.** Le calendrier historique n'est pas servi par
tous les plans Finnhub : si la fenêtre revient vide, le fichier porte `"calendar": []` **et** le
rapport le dit. La jointure, elle, reste fail-closed — sans calendrier, `news_state` vaut `None`
et F0 refuse (D-050). Un calendrier vide ne fabrique jamais un `SAFE`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from ..external.economic_calendar import parse_finnhub_json
from ..providers.fred import FredClient

NY_TZ = ZoneInfo("America/New_York")

#: Série FRED des clôtures VIX (quotidienne, gratuite).
VIX_SERIES = "VIXCLS"

#: Heure à laquelle une clôture quotidienne devient CONNUE. Voir docstring — la dater à minuit
#: la rendrait disponible avant d'exister.
CASH_CLOSE = time(16, 0)

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"


def _known_at(day: str) -> Optional[float]:
    """Horodatage auquel la clôture du jour `day` (AAAA-MM-JJ) devient connue."""
    try:
        parsed = datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return datetime.combine(parsed.date(), CASH_CLOSE, tzinfo=NY_TZ).timestamp()


def fetch_vix_window(start: str, end: str, *, api_key: Optional[str] = None,
                     fetcher: Optional[Callable[[str], str]] = None) -> tuple[list[dict], list[str]]:
    """Série VIX sur `[start, end]`. Rend `(points, avertissements)`.

    Ne lève pas sur une réponse partielle : une fenêtre incomplète est **rapportée**, pas
    complétée. Combler un jour manquant par la valeur de la veille fabriquerait une observation
    qui n'a jamais eu lieu."""
    warnings: list[str] = []
    client = FredClient(api_key=api_key, fetcher=fetcher)
    try:
        result = client.fetch(VIX_SERIES, start=start)
    except Exception as exc:
        return [], [f"FRED injoignable ou refusé : {type(exc).__name__}"]
    if result.series is None:
        return [], [f"FRED n'a rendu aucune série ({result.error or 'motif inconnu'})"]

    points: list[dict] = []
    for obs in result.series.observations:
        day = getattr(obs, "date", None) or (obs.get("date") if isinstance(obs, dict) else None)
        raw = getattr(obs, "value", None) or (obs.get("value") if isinstance(obs, dict) else None)
        if day is None or day > end:
            continue                                 # hors fenêtre demandée
        ts = _known_at(str(day))
        if ts is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            # FRED marque les jours fériés « . ». Ce n'est pas une donnée manquante à combler,
            # c'est un jour sans séance.
            continue
        points.append({"ts": ts, "value": value})
    if not points:
        warnings.append("aucune observation VIX exploitable sur la fenêtre")
    return points, warnings


def fetch_calendar_window(start: str, end: str, *, api_key: Optional[str] = None,
                          fetcher: Optional[Callable[[str], str]] = None,
                          url: str = FINNHUB_URL) -> tuple[list[dict], list[str]]:
    """Calendrier économique sur `[start, end]`.

    L'endpoint LIVE d'`app/external/` n'envoie pas de bornes ; on les ajoute ici (`from`/`to`)
    tout en réutilisant **son** parseur, qui fait autorité sur le format et sur la promotion
    Tier 1."""
    warnings: list[str] = []
    if not (api_key or "").strip():
        return [], ["aucune clé Finnhub : calendrier non récupéré (F0 restera fail-closed)"]
    full = f"{url}?from={start}&to={end}&token={api_key}"
    try:
        text = fetcher(full) if fetcher is not None else _http(full)
    except Exception as exc:
        return [], [f"Finnhub injoignable ou refusé : {type(exc).__name__}"]

    events = parse_finnhub_json(text)
    if events is None:
        # Le parseur DISTINGUE deux cas et nous devons les distinguer aussi : `None` = flux
        # illisible ou empoisonné, `[]` = flux lisible et vide (semaine calme). Les confondre
        # écrirait un calendrier vide sur une réponse corrompue — et un fichier de contexte
        # d'allure normale sur des données qu'on n'a jamais lues.
        return [], ["flux Finnhub ILLISIBLE ou empoisonné — aucun calendrier écrit "
                    "(distinct d'une fenêtre vide)"]

    # `CalendarEvent` est un DICT, pas un objet : `getattr(ev, "ts")` rendait `None` pour chaque
    # entrée et jetait TOUS les événements valides (trouvé à l'essai réel, D-085).
    # Et `tier1` n'existe pas — la sévérité se lit sur `impact`, que le parseur a déjà promue
    # pour les publications sensibles dont l'impact était absent.
    points = [{"ts": ev["ts"], "name": ev.get("name", ""),
               "tier1": str(ev.get("impact", "")).upper() == "HIGH"}
              for ev in events if isinstance(ev, dict) and ev.get("ts") is not None]
    if not points:
        # Distinction qui compte : « pas d'événement ce jour-là » et « le plan ne sert pas
        # l'historique » se ressemblent dans la réponse, pas dans les conséquences.
        warnings.append("calendrier vide sur la fenêtre — soit aucun événement, soit "
                        "l'historique n'est pas servi par ce plan Finnhub. F0 restera "
                        "fail-closed (aucun SAFE ne sera fabriqué).")
    return points, warnings


def _http(url: str, timeout_s: float = 10.0) -> str:            # pragma: no cover - réseau
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout_s) as response:
        return response.read().decode("utf-8")


def build_context(start: str, end: str, *, fred_key: Optional[str] = None,
                  finnhub_key: Optional[str] = None,
                  fred_fetcher: Optional[Callable[[str], str]] = None,
                  finnhub_fetcher: Optional[Callable[[str], str]] = None) -> dict[str, Any]:
    """Assemble le contexte. **Le rapport fait partie du livrable** : un fichier de contexte
    silencieusement incomplet produirait une passe de calibration d'allure normale sur un
    contexte troué."""
    vix, vix_warnings = fetch_vix_window(start, end, api_key=fred_key, fetcher=fred_fetcher)
    calendar, cal_warnings = fetch_calendar_window(start, end, api_key=finnhub_key,
                                                   fetcher=finnhub_fetcher)
    return {
        "window": {"from": start, "to": end},
        "vix": vix,
        "calendar": calendar,
        "provenance": {
            "vix_series": VIX_SERIES,
            "vix_timestamped_at": "clôture cash US (16:00 ET) — instant où la valeur devient "
                                  "connue, jamais minuit",
            "calendar_source": FINNHUB_URL,
            "warnings": [*vix_warnings, *cal_warnings],
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    import os

    parser = argparse.ArgumentParser(
        description="Construit le contexte historique (VIX + calendrier) d'une séance rejouée")
    parser.add_argument("--from", dest="start", required=True, help="AAAA-MM-JJ (inclus)")
    parser.add_argument("--to", dest="end", help="AAAA-MM-JJ (inclus, défaut : --from)")
    parser.add_argument("-o", "--out", default="contexte.json")
    parser.add_argument("--fred-key", default=os.getenv("FRED_API_KEY", ""))
    parser.add_argument("--finnhub-key", default=os.getenv("FINNHUB_API_KEY", ""))
    parser.add_argument("--pad-days", type=int, default=5,
                        help="jours remontés AVANT la fenêtre : la jointure a besoin de la "
                             "dernière clôture ANTÉRIEURE au début de séance")
    args = parser.parse_args(argv)

    end = args.end or args.start
    # On remonte quelques jours en amont : sans une clôture antérieure au début de la séance,
    # `vix_at()` n'aurait rien à rendre sur les premières minutes (il ne regarde jamais devant).
    padded = (datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              - timedelta(days=max(0, args.pad_days))).strftime("%Y-%m-%d")

    context = build_context(padded, end, fred_key=args.fred_key or None,
                            finnhub_key=args.finnhub_key or None)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(context, handle, ensure_ascii=False, indent=2)

    print(f"contexte écrit : {args.out}")
    print(f"  fenêtre   {padded} → {end}  (séance demandée : {args.start} → {end})")
    print(f"  VIX       {len(context['vix'])} observations")
    print(f"  calendrier {len(context['calendar'])} événements "
          f"({sum(1 for c in context['calendar'] if c['tier1'])} Tier 1)")
    for warning in context["provenance"]["warnings"]:
        print(f"  ⚠ {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":                                      # pragma: no cover
    raise SystemExit(main())
