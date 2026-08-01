"""Client Eurostat — API de dissémination (D-057).

« Distinct du SDMX BCE malgré la ressemblance. » Trois datasets servent le pipeline :
`ei_bssi_m_r2` (ESI — proxy PMI zone euro, D1, w 0.30), `nama_10_lp_ulc` (productivité — D5,
4ᵉ composante du BEER) et `une_rt_m` (chômage — Arb 2, jambe EUR de la courbe de Phillips).

**Aucune clé API** : le service est public, et c'est vérifié par un test plutôt que déclaré —
le client n'a même pas de paramètre de clé.

**Le point de sûreté propre à Eurostat : réduire le cube AVANT de lire.** Un dataset non filtré
rend pays × unité × âge × temps, aplati en un seul tableau. Le lire comme une série produit des
nombres parfaitement plausibles et faux — trois pays peuvent sortir comme trois dates (défaut
réel, corrigé et couvert par un test de régression). Le connecteur ne devine donc rien : il
transmet les filtres, et si la réponse porte encore plusieurs valeurs sur une dimension, il
**dit laquelle** au lieu de choisir un pays à la place de l'opérateur (§2.1).

Ce qui est documenté ici tient à ce que les specs disent, et rien de plus. `une_rt_m` reçoit
`geo=EA20` parce que la spec l'écrit ; pour les deux autres datasets, aucune valeur de filtre
n'est inventée — c'est la réponse du service qui nomme les dimensions restées ouvertes, et
c'est une information plus fiable qu'une constante devinée (doctrine C2).

Réserve de fond, à garder en tête en lisant ce qui sort d'ici : **l'ESI n'est pas un PMI.**
Échelle et construction diffèrent. Le z-score les rend comparables, le niveau brut non — et le
biais n'est présent que d'un côté de la divergence, donc il ne s'annule pas : il se lit comme
du signal. C'est le risque n°1 signalé sur D1, dont le PMI porte le plus gros poids.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional
from urllib.parse import quote

from . import connectors as cx
from .catalog import Provider
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

__all__ = ["EurostatClient", "DATASETS", "data_url", "fetch_series", "BASE",
           "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]

# Ce que chaque dataset alimente. Documentation, pas liste blanche : le connecteur reste
# générique et accepte tout identifiant bien formé.
DATASETS: dict[str, str] = {
    "ei_bssi_m_r2": "ESI — proxy du PMI zone euro (D1, w 0.30 · Arb 5). L'ESI n'est PAS un "
                    "PMI : le z-score le rend comparable, le niveau brut non.",
    "nama_10_lp_ulc": "productivité et coût unitaire du travail — 4ᵉ composante du BEER "
                      "(D5 · Arb 3), jambe base de l'effet Balassa. Annuel.",
    "une_rt_m": "taux de chômage mensuel — jambe EUR de la courbe de Phillips (Arb 2). "
                "Filtre geo=EA20 (spec).",
}

_DATASET_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
# Un filtre est un couple code=code : tout ce qui sort de là (espace, `&`, `?`) s'écrirait dans
# la query string et ajouterait un paramètre à l'appel.
_FILTER_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,31}$")
_FILTER_VALUE_RE = re.compile(r"^[A-Za-z0-9_.+\-]{1,64}$")
# `format` est décidé ici, pas par l'appelant : le parser ne sait lire que le JSON-stat, et
# proposer un format qu'on ne parse pas serait une promesse creuse.
_RESERVED_FILTERS = {"format"}


def _check_dataset(dataset: object) -> str:
    if not isinstance(dataset, str) or not _DATASET_RE.match(dataset):
        connus = ", ".join(DATASETS)
        raise cx.SeriesBlocked(
            f"« {dataset} » n'a pas la forme d'un dataset Eurostat (minuscules, chiffres, "
            f"underscore) — refusé avant la requête. Datasets utilisés ici : {connus}.")
    return dataset


def _check_filters(filters: Optional[Mapping[str, object]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in (filters or {}).items():
        if name in _RESERVED_FILTERS:
            raise cx.SeriesBlocked(
                f"filtre « {name} » réservé : le format est fixé à JSON-stat, seul format que "
                "le parser sait lire.")
        if not isinstance(name, str) or not _FILTER_NAME_RE.match(name):
            raise cx.SeriesBlocked(f"« {name} » n'est pas un nom de dimension Eurostat valide.")
        if not isinstance(value, str) or not _FILTER_VALUE_RE.match(value):
            raise cx.SeriesBlocked(
                f"filtre {name} : « {value} » n'est pas un code Eurostat valide — refusé avant "
                "construction de l'URL.")
        out[name] = value
    return out


def data_url(dataset: str, filters: Optional[Mapping[str, object]] = None) -> str:
    """URL d'un dataset filtré. Filtres ORDONNÉS : une URL stable est comparable d'un appel à
    l'autre, et testable."""
    name = _check_dataset(dataset)
    pinned = _check_filters(filters)
    query = "".join(f"&{quote(k)}={quote(v)}" for k, v in sorted(pinned.items()))
    return f"{BASE}/{quote(name)}?format=JSON{query}"


class EurostatClient(HttpSeriesClient):
    """Interrogateur Eurostat. Aucun paramètre de clé API : le service est public.
    `fetcher` est INJECTÉ — les tests n'ouvrent aucune socket."""

    LABEL = "Eurostat"
    PROVIDER = Provider.EUROSTAT
    PARSER = staticmethod(cx.parse_eurostat_json)

    def fetch(self, dataset: str, **filters: object) -> SeriesResult:
        """Observations d'un dataset, réduites par les filtres passés
        (`fetch("une_rt_m", geo="EA20")`).

        Lève `SeriesBlocked` si la demande est refusée par politique ; sinon rend toujours un
        résultat, motif à l'appui — y compris quand la réponse est un cube encore ouvert."""
        return self._run(dataset, data_url(dataset, filters))

    async def fetch_async(self, dataset: str, **filters: object) -> SeriesResult:
        """Même chose, I/O en thread (§7). Le refus de politique est levé AVANT le thread."""
        return await self._run_async(dataset, data_url(dataset, filters))

    def fetch_catalog(self, catalog_key: str, **filters: object) -> SeriesResult:
        """Chemin normal : `unrate_ez` plutôt que `une_rt_m` + `geo=EA20`. Les filtres du
        registre s'appliquent d'office — l'appelant n'a pas à se souvenir que la spec impose
        `geo=EA20` — et peuvent être complétés (jamais contredits en silence : un filtre passé
        ici l'emporte, et c'est un choix explicite de l'appelant)."""
        spec = self._spec_for(catalog_key)
        merged = {**dict(spec.filters), **filters}
        return self.fetch(spec.identifier or "", **merged)

    def _on_unreadable(self, text: str, result: SeriesResult) -> SeriesResult:
        """Un cube non réduit n'est PAS une réponse illisible. Deux causes, deux messages :
        chercher un défaut de parsing quand il manque juste un filtre fait perdre l'après-midi.
        Le texte est fourni par le harnais — aucun second appel."""
        open_dims = cx.eurostat_open_dimensions(text)
        if not open_dims:
            return result                                    # vraiment illisible
        return SeriesResult(
            result.series_id, None,
            f"réponse Eurostat NON FILTRÉE : {', '.join(open_dims)} porte(nt) encore plusieurs "
            "valeurs — épingler ces dimensions dans la requête. Lire ce cube comme une série "
            "donnerait des nombres plausibles et faux.", result.url)


def fetch_series(dataset: str, fetcher: Optional[object] = None,
                 **filters: object) -> SeriesResult:
    """Raccourci sans état pour un script ou une session d'exploration."""
    return EurostatClient(fetcher=fetcher).fetch(dataset, **filters)   # type: ignore[arg-type]
