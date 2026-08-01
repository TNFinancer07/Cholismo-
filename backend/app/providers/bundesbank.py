"""Client REST Bundesbank — BBSIS et la jambe EUR du breakeven (D-057).

« Remplace la Finanzagentur, qui publie la donnée mais sans API. Jambe nominale (Svensson
quotidien) et rendements par ISIN. » Deux lignes du registre en dépendent : `bund_nominal` (C1,
courbe Svensson) et `bundei_real` (C2, rendement du Bund€i par ISIN) — cette dernière étant
« la ligne au meilleur rapport effort/déblocage » puisqu'elle ferme D3 **et** `rdiff` côté D5.

**Aucune clé API** : service public, et le client n'a pas de paramètre de clé.

**On ne fabrique pas une clé par analogie.** La spec donne `R10XX` (10 ans) et `R05XX` (5 ans)
et précise que ce code encode la maturité résiduelle. Le motif saute aux yeux — et c'est
précisément le piège : `R02XX` pour 2 ans serait une INFÉRENCE, pas une clé vérifiée. Seuls les
ténors confirmés sont servis ; les autres renvoient au catalogue (doctrine C2 appliquée à un
motif de clé, pas seulement à un identifiant).

**Le dialecte CSV n'est pas donné par la spec** — en-têtes de métadonnées à sauter, jours fériés
écrits « . », séparateur inconnu. Le parser essaie plusieurs séparateurs et garde celui qui
produit des périodes : pas de devinette, un séparateur qui ne date rien n'est pas le bon.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from . import connectors as cx
from .catalog import BUNDEI, Provider, bundei_roll_state
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

BASE = "https://api.statistiken.bundesbank.de/rest/download"

__all__ = ["BundesbankClient", "DATASETS", "data_url", "svensson_key", "bundei_status",
           "fetch_series", "BASE", "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]

DATASETS: dict[str, str] = {
    "BBSIS": "structure des taux d'intérêt — courbe Svensson quotidienne (jambe nominale du "
             "breakeven EUR, D3 · Arb 2). Le code R{NN}XX encode la maturité résiduelle.",
    "BBK01": "séries de marché par ISIN — voie prévue pour le rendement du Bund€i (D3 · D5). "
             "Clé de série encore à relever au portail, thème W138.",
}

# Ténors dont la spec DONNE le code. Rien d'autre : le reste serait une inférence.
SVENSSON_TENORS: dict[int, str] = {10: "R10XX", 5: "R05XX"}
_SVENSSON_TEMPLATE = "BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.{code}.R.A.A._Z._Z.A"

_DATASET_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_+*.\-]{1,200}$")


def _check_dataset(dataset: object) -> str:
    if not isinstance(dataset, str) or not _DATASET_RE.match(dataset):
        raise cx.SeriesBlocked(
            f"« {dataset} » n'a pas la forme d'un dataset Bundesbank (majuscules, ≤ 20 "
            f"caractères) — refusé avant la requête. Datasets utilisés ici : {', '.join(DATASETS)}.")
    return dataset


def _check_key(key: object, dataset: str) -> str:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise cx.SeriesBlocked(
            f"{dataset} : « {key} » n'a pas la forme d'une clé de série — refusé avant "
            "construction de l'URL, où elle finirait dans le chemin.")
    return key


def data_url(dataset: str, key: str) -> str:
    """URL de téléchargement. `lang=en` évite les en-têtes localisés, `format=csv` est le seul
    format que le parser sait lire."""
    name = _check_dataset(dataset)
    series = _check_key(key, name)
    return f"{BASE}/{quote(name)}/{quote(series)}?format=csv&lang=en"


def svensson_key(years: object) -> str:
    """Clé de la courbe Svensson pour un ténor CONFIRMÉ par la spec (10 ou 5 ans).

    Le motif `R{NN}XX` est visible et tentant à généraliser — c'est exactement ce que la
    doctrine interdit : « ne jamais coder une clé en dur sans l'avoir confirmée au catalogue ».
    Un motif évident est un indice, pas une preuve."""
    code = SVENSSON_TENORS.get(years) if isinstance(years, int) and not isinstance(years, bool) \
        else None
    if code is None:
        connus = ", ".join(f"{y} ans" for y in sorted(SVENSSON_TENORS))
        raise cx.SeriesBlocked(
            f"ténor {years!r} non confirmé au catalogue Bundesbank — seuls {connus} sont donnés "
            "par la spec. Le motif R{NN}XX est visible, mais l'extrapoler produirait une clé "
            "qui a l'air vérifiée sans l'être : la relever au portail d'abord.")
    return _SVENSSON_TEMPLATE.format(code=code)


def bundei_status(now: float) -> dict:
    """État de la jambe RÉELLE du breakeven EUR : ce qui bloque, et ce qu'on hérite en le
    débloquant. Relever la clé ne suffira pas — l'écart de ténor contre la jambe US reste
    entier (voir `catalog.bundei_roll_state`)."""
    return {
        "bloque": True,
        "isin": BUNDEI["isin"],
        "a_faire": "relever la clé de série au portail Bundesbank, thème W138 — repli : "
                   "factsheet Finanzagentur, qui publie le rendement du même titre",
        "debloque": ("bundei_real (D3), ilsw_ez (breakeven EUR) et rdiff (D5) — donc la "
                     "dernière composante non résolue du BEER"),
        "roll": bundei_roll_state(now),
    }


class BundesbankClient(HttpSeriesClient):
    """Interrogateur REST Bundesbank. Aucun paramètre de clé API : le service est public."""

    LABEL = "Bundesbank"
    PROVIDER = Provider.BUNDESBANK
    PARSER = staticmethod(cx.parse_bundesbank_csv)

    def fetch(self, dataset: str, key: str) -> SeriesResult:
        return self._run(f"{dataset}/{key}", data_url(dataset, key))

    async def fetch_async(self, dataset: str, key: str) -> SeriesResult:
        return await self._run_async(f"{dataset}/{key}", data_url(dataset, key))

    def fetch_key(self, dotted: str, **kw) -> SeriesResult:
        """Clé complète telle que le registre l'écrit (`BBSIS.D.I.ZST…`)."""
        dataset, _, key = (dotted or "").partition(".")
        if not dataset or not key:
            raise cx.SeriesBlocked(
                f"« {dotted} » : clé Bundesbank incomplète — forme « DATASET.reste.de.la.clé »")
        return self.fetch(dataset, key, **kw)

    def _fetch_one(self, name: str, *, catalog: bool, **kw) -> SeriesResult:
        return self.fetch_catalog(name, **kw) if catalog else self.fetch_key(name, **kw)

    def fetch_catalog(self, catalog_key: str, **kw) -> SeriesResult:
        return self.fetch_key(self._spec_for(catalog_key).identifier or "", **kw)


def fetch_series(dataset: str, key: str, fetcher: Optional[object] = None) -> SeriesResult:
    return BundesbankClient(fetcher=fetcher).fetch(dataset, key)   # type: ignore[arg-type]
