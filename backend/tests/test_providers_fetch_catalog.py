"""`fetch_catalog` — le contrat commun des sept clients (filet de refactor, D-064).

**Écrit AVANT le refactor, et vert avant lui.** `fetch_catalog(clé_du_registre)` est implémenté
par les sept clients et n'était déclaré sur aucun : un contrat de fait, invisible à la lecture de
la classe de base, que le typage ne pouvait pas vérifier (D-063 le contournait par un `cast`).

Ces tests fixent le comportement OBSERVABLE avant de le remonter dans `HttpSeriesClient` :
- l'identifiant part bien du REGISTRE, jamais de l'appelant ;
- les filtres déclarés au registre s'appliquent d'office ;
- une clé bloquée est refusée par POLITIQUE (elle lève), pas silencieusement ;
- une clé inconnue ne devine rien.

Aucun test n'ouvre de socket : chaque client reçoit un `fetcher` qui capture l'URL.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

import pytest

from app.providers.bundesbank import BundesbankClient
from app.providers.catalog import BY_KEY
from app.providers.cftc import CftcClient
from app.providers.connectors import SeriesBlocked
from app.providers.ecb import EcbClient
from app.providers.eurostat import EurostatClient
from app.providers.fred import FredClient
from app.providers.sdmx import SdmxClient
from app.providers.yahoo import YahooClient

# Une ligne C1 par fournisseur ayant un client écrit. `spf_us` est exclu : vérifié mais SANS REST.
CAS = [
    ("fred", FredClient, "pmi_us", {"api_key": "CLE"}),
    ("ecb", EcbClient, "output_gap_ez", {}),
    ("eurostat", EurostatClient, "pmi_ez", {}),
    ("bundesbank", BundesbankClient, "bund_nominal", {}),
    ("cftc", CftcClient, "cot_fx", {}),      # cf. test dédié : exige `value_field`
    ("sdmx", SdmxClient, "reer", {}),
    ("yahoo", YahooClient, "dax", {}),
]


class Capture:
    """Remplace l'étage réseau : retient l'URL demandée et rend une réponse vide mais lisible."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        return ""            # illisible → `SeriesResult.error`, ce qui suffit ici


def _extra(nom: str) -> dict[str, Any]:
    """Arguments que le CONTRAT exige en plus de la clé. Seul CFTC en a un : `value_field` est
    obligatoire SANS défaut (D-057), parce que deviner quelle colonne porte la valeur
    fabriquerait une donnée. C'est une asymétrie réelle du contrat, pas un oubli."""
    return {"value_field": "open_interest_all"} if nom == "cftc" else {}


def _client(cls: Any, kwargs: dict[str, Any]) -> tuple[Any, Capture]:
    capture = Capture()
    return cls(fetcher=capture, **kwargs), capture


@pytest.mark.parametrize("nom,cls,cle,kwargs", CAS, ids=[c[0] for c in CAS])
def test_fetch_catalog_prend_l_identifiant_du_REGISTRE(nom, cls, cle, kwargs):
    """Le chemin normal : on demande `pmi_us`, jamais `GACDISA066MSFRBNY`. C'est ce qui empêche
    un identifiant de fournisseur de se retrouver codé en dur chez l'appelant (doctrine C2)."""
    client, capture = _client(cls, kwargs)
    client.fetch_catalog(cle, **_extra(nom))
    assert capture.urls, f"{nom} : aucune requête construite"
    identifiant = BY_KEY[cle].identifier or ""
    # URL DÉCODÉE : Yahoo encode `^GDAXI` en `%5EGDAXI`. Comparer la chaîne brute ferait échouer
    # un connecteur parfaitement correct (ma première version du test s'y est prise).
    url = unquote(capture.urls[0])
    # L'identifiant peut être découpé par le connecteur (SDMX : dataflow/clé) — on vérifie que
    # chacun de ses segments s'y retrouve, pas la chaîne entière.
    for segment in identifiant.replace("/", ".").split("."):
        assert segment in url, (nom, segment, url)


@pytest.mark.parametrize("nom,cls,cle,kwargs", CAS, ids=[c[0] for c in CAS])
def test_fetch_catalog_rend_TOUJOURS_un_resultat_jamais_une_exception(nom, cls, cle, kwargs):
    """Condition de DONNÉE (réponse illisible) ≠ refus de politique : la première rend un
    résultat motivé, la seconde lève. Les confondre ferait planter un worker sur un flux vide."""
    client, _ = _client(cls, kwargs)
    res = client.fetch_catalog(cle, **_extra(nom))
    assert res.series is None and res.error


def test_les_FILTRES_du_registre_s_appliquent_d_office():
    """`unrate_ez` impose `geo=EA20` au registre : l'appelant n'a pas à s'en souvenir. C'est la
    SEULE ligne du catalogue qui porte des filtres — le comportement doit survivre au refactor."""
    client, capture = _client(EurostatClient, {})
    client.fetch_catalog("unrate_ez")
    assert "EA20" in capture.urls[0]


def test_un_filtre_de_l_APPELANT_complete_sans_contredire_en_silence():
    client, capture = _client(EurostatClient, {})
    client.fetch_catalog("unrate_ez", geo="DE")
    assert "DE" in capture.urls[0] and "EA20" not in capture.urls[0]


@pytest.mark.parametrize("cle", ["r_star_ez", "rr_current", "oecd_cli"])
def test_une_cle_BLOQUEE_par_le_registre_LEVE_au_lieu_de_deviner(cle):
    """Refus de POLITIQUE : il doit arrêter l'appelant, pas se glisser dans un résultat vide
    qu'on prendrait pour une donnée pas encore publiée (D-050)."""
    client, _ = _client(FredClient, {"api_key": "CLE"})
    with pytest.raises(SeriesBlocked):
        client.fetch_catalog(cle)


def test_CFTC_exige_value_field_et_ne_le_DEVINE_pas():
    """Asymétrie ASSUMÉE du contrat : deviner quelle colonne Socrata porte la valeur
    fabriquerait une donnée (D-057). `fetch_catalog` seul ne suffit donc pas pour CFTC — et le
    refus doit le DIRE, pas sortir un `TypeError` brut du fond de la pile."""
    client, _ = _client(CftcClient, {})
    with pytest.raises(SeriesBlocked) as e:
        client.fetch_catalog("cot_fx")
    assert "value_field" in str(e.value)


def test_une_cle_INCONNUE_du_registre_est_refusee():
    client, _ = _client(FredClient, {"api_key": "CLE"})
    with pytest.raises((SeriesBlocked, KeyError)):
        client.fetch_catalog("cle_qui_n_existe_pas")


@pytest.mark.parametrize("nom,cls,cle,kwargs", CAS, ids=[c[0] for c in CAS])
def test_les_SEPT_clients_exposent_le_meme_contrat(nom, cls, cle, kwargs):
    """Le point du refactor : un contrat implémenté sept fois et déclaré zéro fois n'est pas un
    contrat, c'est une coïncidence — et le typage ne peut rien en dire."""
    from app.providers.client import HttpSeriesClient

    assert issubclass(cls, HttpSeriesClient)
    assert callable(getattr(cls, "fetch_catalog", None)), nom
