"""Client Socrata CFTC — positionnement COT (D-057).

« JSON avec filtres SoQL, historique complet gratuit et RÉTROACTIF — point important pour tout
z-score. » Sert `cot_fx` (D4), qui alimente l'Arb 6bis, le remplacement envisagé de l'Arb 6
bloqué. Hebdomadaire : relevé le mardi, publié le vendredi.

**Le champ de valeur est EXPLICITE, jamais deviné.** Une ressource Socrata porte des dizaines de
colonnes (positions longues/courtes, commerciales/non-commerciales, spreads…). En choisir une
« par défaut » produirait une série silencieusement fausse — le pire cas, puisqu'elle serait
parfaitement plausible.

Aucune clé API : le portail est public (un jeton Socrata ne fait que relever les quotas).
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from . import connectors as cx
from .catalog import Provider
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

BASE = "https://publicreporting.cftc.gov/resource"
DEFAULT_LIMIT = 50_000
__all__ = ["CftcClient", "RESOURCES", "data_url", "fetch_series", "BASE",
           "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]

RESOURCES: dict[str, str] = {
    "gpe5-46if": "Traders in Financial Futures — futures only. Positionnement FX (D4 · Arb 6bis).",
}

_RESOURCE_RE = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")     # forme d'un identifiant Socrata
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check(value: object, motif: re.Pattern, quoi: str) -> str:
    if not isinstance(value, str) or not motif.match(value):
        raise cx.SeriesBlocked(
            f"« {value} » n'a pas la forme d'un {quoi} — refusé avant construction de l'URL, "
            "où il finirait dans la query string SoQL.")
    return value


def data_url(resource: str, *, since: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> str:
    """URL SoQL. `$limit` est TOUJOURS posé : sans lui Socrata plafonne à 1 000 lignes en
    silence — une troncature invisible, exactement ce qu'on refuse ailleurs."""
    res = _check(resource, _RESOURCE_RE, "identifiant de ressource Socrata (xxxx-xxxx)")
    borne = max(1, min(int(limit) if isinstance(limit, int) else DEFAULT_LIMIT, 1_000_000))
    url = f"{BASE}/{quote(res)}.json?$limit={borne}"
    if since is not None:
        jour = _check(since, _DATE_RE, "date SoQL (AAAA-MM-JJ)")
        url += f"&$where=report_date_as_yyyy_mm_dd>'{jour}'"
    return url


class CftcClient(HttpSeriesClient):
    """Interrogateur Socrata CFTC. Aucun paramètre de clé API."""

    LABEL = "CFTC"
    PROVIDER = Provider.CFTC_SOCRATA

    def fetch(self, resource: str, *, value_field: str, since: Optional[str] = None,
              limit: int = DEFAULT_LIMIT) -> SeriesResult:
        """`value_field` est OBLIGATOIRE et sans défaut : la ressource porte des dizaines de
        colonnes, en deviner une produirait une série fausse et plausible."""
        champ = _check(value_field, _FIELD_RE, "nom de colonne Socrata")
        url = data_url(resource, since=since, limit=limit)
        return self._run(f"{resource}:{champ}", url,
                         parser=lambda t: cx.parse_socrata_json(t, value_field=champ))

    async def fetch_async(self, resource: str, *, value_field: str, **kw) -> SeriesResult:
        champ = _check(value_field, _FIELD_RE, "nom de colonne Socrata")
        return await self._run_async(f"{resource}:{champ}", data_url(resource, **kw),
                                     lambda t: cx.parse_socrata_json(t, value_field=champ))

    def _fetch_one(self, name: str, *, catalog: bool, **kw) -> SeriesResult:
        return self.fetch_catalog(name, **kw) if catalog else self.fetch(name, **kw)

    def _by_identifier(self, identifier: str, **kw: Any) -> SeriesResult:
        """Socrata est le seul connecteur dont le contrat exige un argument DE PLUS que la clé :
        `value_field` n'a pas de défaut, parce que deviner quelle colonne porte la valeur
        fabriquerait une donnée (D-057). Le refus le DIT — avant, l'appel sortait un `TypeError`
        brut du fond de la pile, illisible pour l'appelant (trouvé par le filet de refactor)."""
        if not kw.get("value_field"):
            raise cx.SeriesBlocked(
                f"{identifier} : `value_field` est obligatoire pour une ressource Socrata — "
                "nommer la colonne qui porte la valeur ; la deviner fabriquerait une donnée.")
        return self.fetch(identifier, **kw)


def fetch_series(resource: str, *, value_field: str,
                 fetcher: Optional[object] = None, **kw) -> SeriesResult:
    return CftcClient(fetcher=fetcher).fetch(resource, value_field=value_field, **kw)  # type: ignore[arg-type]
