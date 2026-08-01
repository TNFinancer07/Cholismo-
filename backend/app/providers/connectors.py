"""Sept connecteurs génériques — D-057.

« Sept connecteurs génériques couvrent les 49 lignes : FRED, SDMX BCE, Eurostat, REST
Bundesbank, Socrata CFTC, SDMX international (FMI / OCDE / BIS), yfinance. » Les coder UNE
fois, plutôt que dupliquer la même logique cinquante fois — c'est tout l'objet de ce module.

Deux moitiés, strictement séparées :

1. **Construction d'URL** — pilotée par le registre, jamais par une table parallèle. Le
   dataflow BCE se DÉDUIT de la clé (`HICP.M.U2.…` → dataflow `HICP`) ; maintenir une seconde
   table dataflow↔série serait un deuxième endroit où se tromper. Et le portillon du registre
   commande : une ligne C2/C3, un paramètre ou un fournisseur sans REST ne produit **aucune
   URL** — `SeriesBlocked`, avec le motif.
2. **Parsing PUR** — aucune I/O, aucune horloge. Un flux illisible rend `None` (doctrine
   D-050 : l'appelant garde son ancien cache, qui vieillit honnêtement) ; une LIGNE corrompue
   est écartée et **comptée** (`dropped`). Une troncature silencieuse serait le pire des deux
   mondes : un trou qui a l'air d'une série complète.

Marqueurs de valeur manquante, un par fournisseur, tous mortels si on les lit comme des
nombres : FRED et Bundesbank écrivent `.`, Eurostat écrit `:`, Yahoo écrit `null`, DBnomics
écrit `null` JSON. Aucun ne vaut zéro.

La PÉRIODE n'est jamais convertie : « 2026-Q2 » reste « 2026-Q2 ». Lui donner un jour
inventerait une précision que la source ne publie pas.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

from .. import config
from .catalog import BY_KEY, Provider, SeriesSpec, fetch_block_reason

# Un flux macro réel est petit : quelques milliers d'observations. Au-delà, ce n'est plus une
# série, c'est une page d'erreur, une redirection HTML ou une attaque — refusé ENTIER.
MAX_FEED_BYTES = 8_000_000
MAX_OBSERVATIONS = 200_000

_MISSING_MARKERS = {"", ".", ":", "-", "na", "n/a", "nan", "null", "none", "..."}
_PERIOD_RE = re.compile(r"^\d{4}(-(\d{2}|Q[1-4]|S[12]|W\d{2}))?(-\d{2})?$")


class SeriesBlocked(Exception):
    """Refus d'accès à une série — motif de registre, pas panne réseau."""


@dataclass(frozen=True)
class Observation:
    date: str          # période telle que la source la publie ("2026-07-31", "2026-06", "2026-Q2")
    value: float


@dataclass(frozen=True)
class ParsedSeries:
    observations: tuple[Observation, ...]
    dropped: int       # lignes écartées (valeur manquante, illisible, doublon) — jamais silencieux


# =============================================================================================
# Construction d'URL
# =============================================================================================

_REST_PROVIDERS = {Provider.FRED, Provider.ECB_SDMX, Provider.EUROSTAT, Provider.BUNDESBANK,
                   Provider.CFTC_SOCRATA, Provider.SDMX_INTL, Provider.YFINANCE}

_NO_REST_REASON = {
    Provider.PHILADELPHIA_FED: ("pas d'API REST — fichiers XLSX trimestriels à télécharger et "
                                "parser. L'absence est STRUCTURELLE, pas un trou d'accès."),
    Provider.NY_FED: ("pas d'API REST — fichier public trimestriel (Holston-Laubach-Williams) "
                      "à télécharger et parser."),
    Provider.NONE: "aucun fournisseur REST rattaché à cette ligne.",
}


def has_rest_endpoint(key: str) -> bool:
    """Collectable et interrogeable en HTTP ne sont pas la même chose : le SPF est vérifié (C1)
    et n'a pourtant aucun REST."""
    spec = BY_KEY.get(key)
    return bool(spec and spec.provider in _REST_PROVIDERS)


def build_url(key: str, *, api_key: Optional[str] = None, start: Optional[str] = None,
              contract: Optional[str] = None, limit: int = 50_000, **_ignored: Any) -> str:
    """URL d'appel d'une série. Lève `SeriesBlocked` dès que le registre l'interdit — c'est un
    refus de POLITIQUE, pas une donnée absente : il doit arrêter le programme, pas se glisser
    dans un `str(None)` au milieu d'une requête."""
    reason = fetch_block_reason(key)
    if reason is not None:
        raise SeriesBlocked(f"{key} : {reason}")
    spec = BY_KEY[key]
    if spec.provider not in _REST_PROVIDERS:
        raise SeriesBlocked(f"{key} : {_NO_REST_REASON.get(spec.provider, 'pas de REST')}")
    builder = _BUILDERS[spec.provider]
    return builder(spec, api_key=api_key, start=start, contract=contract, limit=limit)


FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
# Un identifiant FRED est alphanumérique (UNRATE, DFF, SP500, T10YIE, BAMLH0A0HYM2…). Tout ce
# qui sort de cette forme n'est pas une série : c'est une tentative d'écrire dans la query
# string (`&api_key=…`, `../`, un espace). On refuse AVANT de construire l'URL.
_FRED_SERIES_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def fred_observations_url(series_id: str, *, api_key: Optional[str] = None,
                          start: Optional[str] = None, context: str = "") -> str:
    """URL d'observations FRED pour N'IMPORTE QUELLE série. Source unique de vérité de cet
    endpoint : le registre passe par ici, le client direct aussi."""
    label = context or (series_id if isinstance(series_id, str) else "?")
    if not isinstance(series_id, str) or not _FRED_SERIES_ID_RE.match(series_id):
        raise SeriesBlocked(
            f"{label} : « {series_id} » n'a pas la forme d'un identifiant FRED "
            "(alphanumérique, ≤ 64 caractères) — refusé avant construction de l'URL.")
    key = config.FRED_API_KEY if api_key is None else api_key
    if not key:
        raise SeriesBlocked(
            f"{label} : clé API FRED absente — renseigner FRED_API_KEY (gratuite). "
            "Sans elle, on ne part pas à l'aveugle chercher une série qui reviendra en erreur.")
    url = f"{FRED_OBSERVATIONS}?series_id={quote(series_id)}&api_key={quote(key)}&file_type=json"
    return url + (f"&observation_start={quote(start)}" if start else "")


def _fred_url(spec: SeriesSpec, *, api_key: Optional[str], start: Optional[str], **_: Any) -> str:
    return fred_observations_url(spec.identifier or "", api_key=api_key, start=start,
                                 context=spec.key)


def _ecb_url(spec: SeriesSpec, **_: Any) -> str:
    # Import LOCAL, et volontairement : `ecb` dépend de ce module (parsing, redaction), donc
    # l'inverse ne peut pas se faire en tête de fichier. Le faire ici garde une SEULE
    # construction d'URL BCE — dont les gardes (dataflow retiré, clé mal formée) valent alors
    # aussi pour le chemin registre.
    from .ecb import data_url
    dataflow, _, series = (spec.identifier or "").partition(".")
    if not dataflow or not series:
        raise SeriesBlocked(f"{spec.key} : clé SDMX BCE incomplète — dataflow.série attendus")
    return data_url(dataflow, series)


def _eurostat_url(spec: SeriesSpec, **_: Any) -> str:
    return ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
            f"{quote(spec.identifier or '')}?format=JSON")


def _bundesbank_url(spec: SeriesSpec, **_: Any) -> str:
    dataset, _, series = (spec.identifier or "").partition(".")
    if not dataset or not series:
        raise SeriesBlocked(f"{spec.key} : clé Bundesbank incomplète — dataset.série attendus")
    return (f"https://api.statistiken.bundesbank.de/rest/download/{quote(dataset)}/{quote(series)}"
            f"?format=csv&lang=en")


def _socrata_url(spec: SeriesSpec, *, start: Optional[str], limit: int, **_: Any) -> str:
    url = f"https://publicreporting.cftc.gov/resource/{quote(spec.identifier or '')}.json"
    where = f"?$where=report_date_as_yyyy_mm_dd>'{start}'&$limit={int(limit)}" if start \
        else f"?$limit={int(limit)}"
    return url + where


def _sdmx_intl_url(spec: SeriesSpec, **_: Any) -> str:
    dataflow, _, series = (spec.identifier or "").partition("/")
    if not dataflow or not series:
        raise SeriesBlocked(f"{spec.key} : clé SDMX incomplète — dataflow/clé attendus")
    return f"https://stats.bis.org/api/v1/data/{quote(dataflow)}/{quote(series)}/all"


def _yahoo_url(spec: SeriesSpec, *, contract: Optional[str], **_: Any) -> str:
    ticker = spec.identifier or ""
    if ticker == "ZQ":
        # « ZQ » est une RACINE de contrat, pas un ticker : sans le mois et l'année, il n'y a
        # aucune série à demander. Le dire vaut mieux que fabriquer une échéance par défaut.
        if not contract:
            raise SeriesBlocked(
                f"{spec.key} : « ZQ » est une racine de contrat, pas un ticker — préciser le "
                "contrat (ex. ZQZ26). La méthodologie FedWatch est publique, le choix de "
                "l'échéance ne l'est pas.")
        ticker = contract if "." in contract else f"{contract}.CBT"
    return (f"https://query1.finance.yahoo.com/v7/finance/download/{quote(ticker)}"
            f"?period1=0&period2=9999999999&interval=1d&events=history")


_BUILDERS = {
    Provider.FRED: _fred_url,
    Provider.ECB_SDMX: _ecb_url,
    Provider.EUROSTAT: _eurostat_url,
    Provider.BUNDESBANK: _bundesbank_url,
    Provider.CFTC_SOCRATA: _socrata_url,
    Provider.SDMX_INTL: _sdmx_intl_url,
    Provider.YFINANCE: _yahoo_url,
}


def redact(url: str) -> str:
    """URL sans secret — pour les logs et tout ce qui sort de la machine."""
    return re.sub(r"(api_key=)[^&]*", r"\1{api_key}", str(url))


def describe_endpoint(key: str) -> str:
    """Ce qu'on peut MONTRER : le gabarit, jamais la clé de l'opérateur. Une ligne bloquée
    décrit son blocage — c'est l'information utile à ce stade."""
    reason = fetch_block_reason(key)
    if reason is not None:
        return reason
    spec = BY_KEY.get(key)
    if spec is None:
        return "ligne inconnue"
    if spec.provider not in _REST_PROVIDERS:
        return _NO_REST_REASON.get(spec.provider, "pas de REST")
    try:
        return redact(build_url(key, api_key="{api_key}", contract="{contrat}"))
    except SeriesBlocked as e:
        return str(e)


# =============================================================================================
# Parsing — pur, défensif, jamais silencieux
# =============================================================================================

def _too_big(text: Any) -> bool:
    return not isinstance(text, str) or len(text) > MAX_FEED_BYTES


def _value(raw: Any) -> Optional[float]:
    """`None` = pas une valeur. Les marqueurs de trou de chaque fournisseur meurent ici."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(raw) else None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.lower() in _MISSING_MARKERS:
        return None
    try:
        out = float(text.replace(",", "."))          # certains flux européens virgulent
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _period(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    text = raw.strip().split("T")[0]                 # Socrata horodate un jour : on garde le jour
    return text if text and _PERIOD_RE.match(text) else None


def _finish(rows: list[tuple[str, float]], dropped: int) -> Optional[ParsedSeries]:
    """Dédoublonne (le PREMIER gagne — une révision arrivée dans le même lot ne réécrit pas en
    silence ce qu'on vient de lire), ordonne, borne."""
    if not rows:
        return None                                  # rien de lisible = illisible, pas « vide »
    seen: dict[str, float] = {}
    for date, value in rows:
        if date in seen:
            dropped += 1
            continue
        seen[date] = value
    if len(seen) > MAX_OBSERVATIONS:
        return None
    obs = tuple(Observation(date=d, value=v) for d, v in sorted(seen.items()))
    return ParsedSeries(observations=obs, dropped=dropped)


def parse_fred_json(text: str) -> Optional[ParsedSeries]:
    """`{"observations": [{"date": ..., "value": "."}]}` — le point est un TROU, pas un zéro."""
    if _too_big(text):
        return None
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("observations"), list):
        return None
    rows, dropped = [], 0
    for entry in raw["observations"]:
        date = _period(entry.get("date")) if isinstance(entry, dict) else None
        value = _value(entry.get("value")) if isinstance(entry, dict) else None
        if date is None or value is None:
            dropped += 1
            continue
        rows.append((date, value))
    return _finish(rows, dropped)


def parse_eurostat_json(text: str) -> Optional[ParsedSeries]:
    """JSON-stat : `value` est indexé par POSITION, les libellés de période sont dans
    `dimension.time.category.index`. Le marqueur de trou est « : »."""
    if _too_big(text):
        return None
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    index = (((raw.get("dimension") or {}).get("time") or {}).get("category") or {}).get("index")
    values = raw.get("value")
    if not isinstance(index, dict) or not isinstance(values, (dict, list)):
        return None
    rows, dropped = [], 0
    for label, position in index.items():
        date = _period(label)
        if date is None or not isinstance(position, int) or isinstance(position, bool):
            dropped += 1
            continue
        if isinstance(values, list):
            raw_value = values[position] if 0 <= position < len(values) else None
        else:
            raw_value = values.get(str(position))
        value = _value(raw_value)
        if value is None:
            dropped += 1
            continue
        rows.append((date, value))
    return _finish(rows, dropped)


def _csv_rows(text: str) -> Optional[list[list[str]]]:
    if _too_big(text) or not text.strip():
        return None
    try:
        return [row for row in csv.reader(io.StringIO(text)) if row]
    except (csv.Error, ValueError):
        return None


def parse_sdmx_csv(text: str) -> Optional[ParsedSeries]:
    """SDMX-CSV (BCE `format=csvdata`, BIS, miroirs). Colonnes lues par NOM : un fournisseur qui
    ajoute une colonne ne doit pas décaler toute la série."""
    rows = _csv_rows(text)
    if not rows:
        return None
    header = [c.strip().upper() for c in rows[0]]
    if "TIME_PERIOD" not in header or "OBS_VALUE" not in header:
        return None
    i_date, i_value = header.index("TIME_PERIOD"), header.index("OBS_VALUE")
    out, dropped = [], 0
    for row in rows[1:]:
        if len(row) <= max(i_date, i_value):
            dropped += 1
            continue
        date, value = _period(row[i_date]), _value(row[i_value])
        if date is None or value is None:
            dropped += 1
            continue
        out.append((date, value))
    return _finish(out, dropped)


def parse_bundesbank_csv(text: str) -> Optional[ParsedSeries]:
    """CSV Bundesbank : en-têtes de métadonnées à SAUTER (leur nombre varie selon la série), et
    les jours fériés écrits « . ». On ne saute pas un nombre fixe de lignes — on ne garde que
    celles dont le premier champ est une période."""
    rows = _csv_rows(text)
    if not rows:
        return None
    out, dropped = [], 0
    for row in rows:
        if not row:
            continue
        date = _period(row[0])
        if date is None:
            continue                                 # métadonnée : ni observation, ni rejet
        value = _value(row[1]) if len(row) > 1 else None
        if value is None:
            dropped += 1                             # période connue, valeur absente = trou
            continue
        out.append((date, value))
    return _finish(out, dropped)


def parse_socrata_json(text: str, *, value_field: str) -> Optional[ParsedSeries]:
    """Socrata CFTC : tableau de dicts. Le champ de valeur est EXPLICITE — le deviner sur une
    ressource qui en porte des dizaines produirait une série silencieusement fausse."""
    if _too_big(text):
        return None
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, list):
        return None
    out, dropped = [], 0
    for entry in raw:
        if not isinstance(entry, dict):
            dropped += 1
            continue
        date, value = _period(entry.get("report_date_as_yyyy_mm_dd")), _value(entry.get(value_field))
        if date is None or value is None:
            dropped += 1
            continue
        out.append((date, value))
    return _finish(out, dropped)


def parse_dbnomics_json(text: str) -> Optional[ParsedSeries]:
    """DBnomics : `period` et `value` sont deux listes PARALLÈLES. Un désalignement décale toute
    la série d'un cran — mieux vaut ne rien lire que lire décalé."""
    if _too_big(text):
        return None
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    docs = ((raw.get("series") or {}).get("docs") if isinstance(raw.get("series"), dict) else None)
    if not isinstance(docs, list) or not docs or not isinstance(docs[0], dict):
        return None
    periods, values = docs[0].get("period"), docs[0].get("value")
    if not isinstance(periods, list) or not isinstance(values, list):
        return None
    if len(periods) != len(values):
        return None
    out, dropped = [], 0
    for label, raw_value in zip(periods, values):
        date, value = _period(label), _value(raw_value)
        if date is None or value is None:
            dropped += 1
            continue
        out.append((date, value))
    return _finish(out, dropped)


def parse_yahoo_csv(text: str) -> Optional[ParsedSeries]:
    """CSV Yahoo. Réserve assumée UNE fois pour toutes (spec) : ce n'est pas une API officielle,
    les CGU couvrent l'usage personnel et la recherche — prévoir que ça casse un jour et que le
    remplacement sera manuel."""
    rows = _csv_rows(text)
    if not rows:
        return None
    header = [c.strip().lower() for c in rows[0]]
    if "date" not in header:
        return None
    i_date = header.index("date")
    i_value = header.index("adj close") if "adj close" in header else (
        header.index("close") if "close" in header else None)
    if i_value is None:
        return None
    out, dropped = [], 0
    for row in rows[1:]:
        if len(row) <= max(i_date, i_value):
            dropped += 1
            continue
        date, value = _period(row[i_date]), _value(row[i_value])
        if date is None or value is None:
            dropped += 1
            continue
        out.append((date, value))
    return _finish(out, dropped)


PARSERS = {
    Provider.FRED: parse_fred_json,
    Provider.ECB_SDMX: parse_sdmx_csv,
    Provider.EUROSTAT: parse_eurostat_json,
    Provider.BUNDESBANK: parse_bundesbank_csv,
    Provider.SDMX_INTL: parse_sdmx_csv,
    Provider.YFINANCE: parse_yahoo_csv,
}
