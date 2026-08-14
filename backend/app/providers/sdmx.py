"""Client SDMX international — BIS, FMI, OCDE, miroir DBnomics (D-057).

« Trois fournisseurs, un seul protocole. Toutes les lignes ≈ C2 qui restent sont ici, et elles
se règlent de la même façon : interroger le DSD/codelist une fois pour extraire la clé, puis la
figer. » Une seule ligne est C1 aujourd'hui — `reer` (BIS, `WS_EER_M/M.R.B.XM`) ; `nfa` et `tot`
attendent leur relevé, et le registre les bloque déjà.

**Deux formats, jamais confondus** : le BIS rend du SDMX-CSV, DBnomics du JSON à listes
parallèles. Le parser est choisi par la MÉTHODE appelée, pas par un attribut d'instance qu'un
appel précédent aurait laissé traîner.

« DBnomics sert de miroir aux trois — utile si un DSD est pénible » : c'est un repli assumé, pas
une source différente.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from . import connectors as cx
from .catalog import Provider
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

BIS_BASE = "https://stats.bis.org/api/v1/data"
DBNOMICS_BASE = "https://api.db.nomics.world/v22/series"
__all__ = ["SdmxClient", "bis_url", "dbnomics_url", "fetch_series", "BIS_BASE", "DBNOMICS_BASE",
           "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]

_DATAFLOW_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,39}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_+*.\-]{1,200}$")


def _check(value: object, motif: re.Pattern, quoi: str) -> str:
    if not isinstance(value, str) or not motif.match(value):
        raise cx.SeriesBlocked(
            f"« {value} » n'a pas la forme d'un {quoi} — refusé avant construction de l'URL.")
    return value


def bis_url(dataflow: str, key: str) -> str:
    flow = _check(dataflow, _DATAFLOW_RE, "dataflow SDMX")
    series = _check(key, _KEY_RE, "clé de série SDMX")
    return f"{BIS_BASE}/{quote(flow)}/{quote(series)}/all"


def dbnomics_url(provider: str, dataset: str, series: str) -> str:
    p = _check(provider, _DATAFLOW_RE, "fournisseur DBnomics")
    d = _check(dataset, _DATAFLOW_RE, "dataset DBnomics")
    s = _check(series, _KEY_RE, "clé de série DBnomics")
    return f"{DBNOMICS_BASE}/{quote(p)}/{quote(d)}/{quote(s)}?observations=1"


class SdmxClient(HttpSeriesClient):
    """Interrogateur SDMX international. Aucun paramètre de clé API."""

    LABEL = "SDMX international"
    PROVIDER = Provider.SDMX_INTL
    PARSER = staticmethod(cx.parse_sdmx_csv)

    def fetch(self, dataflow: str, key: str) -> SeriesResult:
        """BIS — SDMX-CSV. Exemple validé par la spec : `M.N.B.CH` ; cible zone euro
        `M.R.B.XM` (real, broad)."""
        return self._run(f"{dataflow}/{key}", bis_url(dataflow, key))

    async def fetch_async(self, dataflow: str, key: str) -> SeriesResult:
        return await self._run_async(f"{dataflow}/{key}", bis_url(dataflow, key))

    def fetch_dbnomics(self, provider: str, dataset: str, series: str) -> SeriesResult:
        """Miroir DBnomics — JSON à listes parallèles. Le parser est choisi ICI, pas hérité."""
        return self._run(f"{provider}/{dataset}/{series}",
                         dbnomics_url(provider, dataset, series),
                         parser=cx.parse_dbnomics_json)

    def fetch_key(self, slashed: str, **kw) -> SeriesResult:
        """Forme du registre : `WS_EER_M/M.R.B.XM` — dataflow et clé séparés par un `/`."""
        dataflow, _, key = (slashed or "").partition("/")
        if not dataflow or not key:
            raise cx.SeriesBlocked(
                f"« {slashed} » : clé SDMX incomplète — forme attendue « DATAFLOW/clé »")
        return self.fetch(dataflow, key, **kw)

    def _fetch_one(self, name: str, *, catalog: bool, **kw) -> SeriesResult:
        return self.fetch_catalog(name, **kw) if catalog else self.fetch_key(name, **kw)

    def _by_identifier(self, identifier: str, **kw: Any) -> SeriesResult:
        return self.fetch_key(identifier, **kw)


def fetch_series(dataflow: str, key: str, fetcher: Optional[object] = None) -> SeriesResult:
    return SdmxClient(fetcher=fetcher).fetch(dataflow, key)   # type: ignore[arg-type]
