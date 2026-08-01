"""Client SDMX de la Banque centrale européenne — D-057.

« Un seul service couvre plusieurs dataflows qu'on utilise séparément : YC (courbe de rendement,
Arb 1), AME (AMECO, NAIRU pour Arb 2), SPF (consensus économistes, Arb 5). Même connecteur
générique, seuls le dataflow et la clé de série changent. » S'y ajoutent EST (€STR), ILM (bilan
Eurosystème) et HICP (inflation) côté dimensions — d'où une seule fonction générique
`fetch(dataflow, key)` plutôt qu'une par variable.

**Aucune clé API.** Le service est public, et c'est vérifié par un test plutôt que déclaré :
`EcbClient` n'a même pas de paramètre de clé, et l'URL construite n'en porte aucune. Un client
qui en exigerait une refuserait des séries parfaitement accessibles ; un client qui en enverrait
une la ferait fuiter chez un tiers qui ne l'a pas demandée.

**Le piège qui casse en silence** : le dataflow `ICP` est DISCONTINUÉ depuis le 04.02.2026
(changement de méthodologie Eurostat), remplacé par `HICP` à structure de clé identique. Une
clé ICP renvoie une erreur de service — qu'on lirait comme une panne réseau. Elle est donc
refusée ICI, avant la requête, avec le remplaçant nommé.

**L'avertissement le plus lourd de la spec**, rendu actionnable : « clé de série exacte :
télécharger le catalogue CSV du dataflow visé, ne jamais coder une clé en dur sans l'avoir
confirmée dedans ». `series_keys_url(dataflow)` donne l'adresse de ce catalogue.

Une réserve sur la jambe EUR, à garder en tête en lisant les chiffres qui sortent d'ici : `YC`
est une courbe **souveraine**, pas OIS. Elle porte une prime de terme et de rareté du collatéral
que l'OIS n'a pas — c'est la source du bruit asymétrique entre les deux jambes de l'Arb 1, dont
le seuil de 0,30 % suppose pourtant un bruit comparable des deux côtés.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from . import connectors as cx
from .catalog import AMECO_ZONE, Provider
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

BASE = "https://data-api.ecb.europa.eu/service/data"

__all__ = ["EcbClient", "DATAFLOWS", "RETIRED_DATAFLOWS", "series_keys_url", "fetch_series",
           "BASE", "AMECO_ZONE", "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]

# Ce que chaque dataflow sert, pour qu'on puisse répondre « YC, c'est quoi ? » sans rouvrir les
# artefacts. Ce n'est PAS une liste blanche : le connecteur reste générique et accepte tout
# dataflow bien formé — la liste documente, elle ne restreint pas.
DATAFLOWS: dict[str, str] = {
    "YC": "courbe de rendement zéro-coupon AAA — ois_spot / ois_term de l'Arb 1 (D2). "
          "SOUVERAINE, pas OIS : prime de terme et de rareté du collatéral incluses.",
    "AME": f"AMECO — output gap ({AMECO_ZONE}) et NAWRU (Arb 1 / Arb 2). Annuel : asymétrie de "
           "fréquence réelle et non résolue contre le trimestriel US.",
    "SPF": "Survey of Professional Forecasters — consensus croissance (Arb 5) et inflation "
           "ancrée (Arb 2).",
    "EST": "€STR — taux au jour le jour, moyenne tronquée pondérée par volume, publié 08:00 CET.",
    "ILM": "bilan Eurosystème — rythme QT/QE (D2). Le total est bruité par les refinancements.",
    "HICP": "inflation zone euro (D3) — REMPLACE le dataflow ICP, mort le 04.02.2026.",
}

# Refusés par leur nom, avec le remplaçant. Un dataflow retiré ne rend pas une valeur fausse :
# il rend une erreur — et c'est la bonne nouvelle, à condition de ne pas la prendre pour une panne.
RETIRED_DATAFLOWS: dict[str, str] = {
    "ICP": "HICP — discontinué le 04.02.2026 (changement de méthodologie Eurostat), remplacé "
           "par HICP à structure de clé IDENTIQUE",
}

_DATAFLOW_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
# Clé de série SDMX : segments séparés par des points, `+` pour plusieurs codes, segment vide
# pour « tous ». Tout le reste — espace, `?`, `&`, `/` — sort de la query string et n'a rien à
# faire là.
_KEY_RE = re.compile(r"^[A-Za-z0-9_+*.\-]{1,200}$")


def _check_dataflow(dataflow: object) -> str:
    if isinstance(dataflow, str) and dataflow in RETIRED_DATAFLOWS:
        raise cx.SeriesBlocked(
            f"dataflow « {dataflow} » RETIRÉ : utiliser {RETIRED_DATAFLOWS[dataflow]}")
    if not isinstance(dataflow, str) or not _DATAFLOW_RE.match(dataflow):
        connus = ", ".join(DATAFLOWS)
        raise cx.SeriesBlocked(
            f"« {dataflow} » n'a pas la forme d'un dataflow BCE (majuscules, ≤ 20 caractères) — "
            f"refusé avant la requête. Dataflows utilisés ici : {connus}.")
    return dataflow


def _check_key(key: object, dataflow: str) -> str:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise cx.SeriesBlocked(
            f"{dataflow} : « {key} » n'a pas la forme d'une clé de série SDMX — refusé avant "
            "construction de l'URL. Relever la clé exacte au catalogue du dataflow "
            f"({series_keys_url(dataflow)}) plutôt que de la deviner.")
    return key


def data_url(dataflow: str, key: str) -> str:
    """URL d'observations. Toujours `csvdata` : c'est le format que sait lire le parser, et
    proposer un format qu'on ne parse pas serait une promesse creuse."""
    flow = _check_dataflow(dataflow)
    series = _check_key(key, flow)
    return f"{BASE}/{quote(flow)}/{quote(series)}?format=csvdata"


def series_keys_url(dataflow: str) -> str:
    """Adresse du catalogue de clés d'un dataflow — la réponse concrète à « ne jamais coder une
    clé en dur sans l'avoir confirmée ».

    `detail=serieskeysonly` est le paramètre SDMX REST standard pour ne ramener que les clés,
    sans les observations. Réserve assumée dans l'esprit C2 : il n'a **pas été vérifié contre
    le service de la BCE** dans cette session — si la réponse déçoit, le repli est le catalogue
    CSV complet du dataflow, ce que la spec décrit."""
    flow = _check_dataflow(dataflow)
    return f"{BASE}/{quote(flow)}?detail=serieskeysonly&format=csvdata"


class EcbClient(HttpSeriesClient):
    """Interrogateur SDMX BCE. Aucun paramètre de clé API : le service est public (voir
    docstring du module). `fetcher` est INJECTÉ — les tests n'ouvrent aucune socket."""

    LABEL = "SDMX BCE"
    PROVIDER = Provider.ECB_SDMX
    PARSER = staticmethod(cx.parse_sdmx_csv)

    # -- interrogation générique : un connecteur, tous les dataflows --

    def fetch(self, dataflow: str, key: str) -> SeriesResult:
        """Observations d'une série (`YC` + `B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y`, `AME` + …).

        Lève `SeriesBlocked` si la demande est refusée par politique ; sinon rend toujours un
        résultat, motif à l'appui quand la donnée n'est pas venue."""
        url = data_url(dataflow, key)
        return self._run(f"{dataflow}/{key}", url)

    async def fetch_async(self, dataflow: str, key: str) -> SeriesResult:
        """Même chose, I/O en thread : la boucle d'événements ne gèle jamais (§7). Le refus de
        politique est levé AVANT de partir en thread."""
        url = data_url(dataflow, key)
        return await self._run_async(f"{dataflow}/{key}", url)

    # -- formes d'appel dérivées --

    def fetch_key(self, dotted: str) -> SeriesResult:
        """Clé complète telle que le registre et les artefacts l'écrivent
        (`HICP.M.U2.N.000000.4.ANR`) : le dataflow est le premier segment."""
        dataflow, _, key = (dotted or "").partition(".")
        if not dataflow or not key:
            raise cx.SeriesBlocked(
                f"« {dotted} » : clé SDMX incomplète — forme attendue « DATAFLOW.reste.de.la.clé »")
        return self.fetch(dataflow, key)

    def _fetch_one(self, name: str, *, catalog: bool, **kw) -> SeriesResult:
        """Côté BCE, « un nom = une série » veut dire la clé POINTÉE (`HICP.M.U2.…`) — c'est
        ainsi que le registre et les artefacts l'écrivent. Sans cette précision, l'assemblage
        tabulaire appellerait `fetch(dataflow, key)` avec un seul argument."""
        return self.fetch_catalog(name, **kw) if catalog else self.fetch_key(name, **kw)

    def fetch_catalog(self, catalog_key: str) -> SeriesResult:
        """Chemin normal : on demande `yc_spot`, pas la clé SDMX. Le portillon du registre
        s'applique (C1 seulement) et le fournisseur est vérifié."""
        return self.fetch_key(self._spec_for(catalog_key).identifier or "")


def fetch_series(dataflow: str, key: str,
                 fetcher: Optional[object] = None) -> SeriesResult:
    """Raccourci sans état pour un script ou une session d'exploration."""
    return EcbClient(fetcher=fetcher).fetch(dataflow, key)   # type: ignore[arg-type]
