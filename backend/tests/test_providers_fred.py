"""Client FRED — interroger n'importe quelle série (D-057).

FRED est « le socle · ~30 lignes sur 5 dimensions » : un endpoint, un format, une clé gratuite.
Le client sépare strictement deux natures d'échec, parce qu'elles n'appellent pas la même
réaction :

- **refus de politique** (`SeriesBlocked`) — clé absente, identifiant qui n'en est pas un, ligne
  du registre non confirmée. C'est une erreur de programme : elle doit s'arrêter, pas se
  transformer en série vide qu'on lirait comme un marché calme ;
- **condition de données** (`FredResult.error`) — réseau mort, flux illisible. On rend un motif,
  l'appelant garde ce qu'il avait (doctrine D-050).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.providers import connectors as cx
from app.providers import fred

OBS = json.dumps({"observations": [
    {"date": "2026-07-29", "value": "4.1"},
    {"date": "2026-07-30", "value": "."},
    {"date": "2026-07-31", "value": "4.2"},
]})


def _client(payload=OBS, **kw):
    """Client à fetcher INJECTÉ — aucun test ne touche le réseau."""
    seen: list[str] = []

    def fetcher(url: str) -> str:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    return fred.FredClient(api_key="CLE-TEST", fetcher=fetcher, **kw), seen


# =============================================================================================
# Interroger n'importe quelle série
# =============================================================================================


@pytest.mark.parametrize("series_id", ["UNRATE", "DFF", "SP500", "T10YIE"])
def test_interroge_n_importe_quelle_serie(series_id):
    client, seen = _client()
    result = client.fetch(series_id)
    assert result.error is None
    assert result.series is not None
    assert [o.value for o in result.series.observations] == [4.1, 4.2]
    assert result.series.dropped == 1                     # le « . » de FRED est un TROU
    assert f"series_id={series_id}" in seen[0]
    assert "file_type=json" in seen[0]


def test_l_endpoint_est_bien_celui_de_la_spec():
    client, seen = _client()
    client.fetch("UNRATE")
    assert seen[0].startswith("https://api.stlouisfed.org/fred/series/observations?")


def test_la_cle_vient_de_FRED_API_KEY_quand_on_ne_la_passe_pas(monkeypatch):
    monkeypatch.setattr("app.config.FRED_API_KEY", "CLE-ENV")
    seen: list[str] = []
    client = fred.FredClient(fetcher=lambda url: seen.append(url) or OBS)
    client.fetch("DFF")
    assert "api_key=CLE-ENV" in seen[0]


def test_borne_de_debut_transmise_telle_quelle():
    client, seen = _client()
    client.fetch("SP500", start="2020-01-01")
    assert "observation_start=2020-01-01" in seen[0]


def test_serie_du_registre_par_sa_CLE_metier():
    """Le registre reste le chemin normal : on demande `vixcls`, pas `VIXCLS`."""
    client, seen = _client()
    result = client.fetch_catalog("vixcls")
    assert result.error is None and result.series is not None
    assert "series_id=VIXCLS" in seen[0]


# =============================================================================================
# Refus de politique — ça s'arrête, ça ne se dégrade pas en série vide
# =============================================================================================


def test_sans_cle_API_on_ne_part_pas():
    client = fred.FredClient(api_key="", fetcher=lambda url: OBS)
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch("UNRATE")
    assert "clé API" in str(e.value)


@pytest.mark.parametrize("bad", ["UNRATE&api_key=vole", "../../etc/passwd", "UN RATE",
                                 "", "A" * 65, None, 42])
def test_identifiant_qui_n_en_est_pas_un_est_refuse_AVANT_la_requete(bad):
    """Sans ce garde, `series_id` écrit dans la query string : un `&` suffit à ajouter un
    paramètre à l'appel."""
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch(bad)
    assert seen == []                                     # rien n'est parti


def test_une_ligne_C2_du_registre_reste_bloquee_meme_avec_un_client_pret():
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("oecd_cli")
    assert "catalogue" in str(e.value).lower()
    assert seen == []


def test_une_ligne_du_registre_qui_n_est_pas_FRED_est_refusee():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("hicp_ez")
    assert "FRED" in str(e.value)


# =============================================================================================
# Conditions de données — motif, jamais exception, jamais secret
# =============================================================================================


def test_reseau_mort_rend_un_MOTIF_pas_une_exception():
    client, _ = _client(payload=OSError("connection reset"))
    result = client.fetch("UNRATE")
    assert result.series is None
    assert result.error and "injoignable" in result.error


def test_le_motif_d_erreur_ne_FUIT_JAMAIS_la_cle():
    client, _ = _client(payload=OSError("échec sur ?api_key=CLE-TEST&x=1"))
    result = client.fetch("UNRATE")
    assert "CLE-TEST" not in (result.error or "")
    assert "{api_key}" in (result.error or "")


def test_flux_illisible_est_un_MOTIF_pas_une_serie_vide():
    """`None` ≠ `[]` : une série vide se lirait comme un fait observé."""
    client, _ = _client(payload="<html>503 Service Unavailable</html>")
    result = client.fetch("UNRATE")
    assert result.series is None
    assert result.error and "illisible" in result.error


def test_reponse_geante_est_refusee_entiere():
    client, _ = _client(payload="{" + " " * (cx.MAX_FEED_BYTES + 10))
    result = client.fetch("UNRATE")
    assert result.series is None and result.error


def test_resultat_IMMUABLE():
    client, _ = _client()
    result = client.fetch("UNRATE")
    with pytest.raises(Exception):
        result.series_id = "AUTRE"                        # type: ignore[misc]


# =============================================================================================
# Étage async — l'I/O part en thread, la boucle d'événements ne gèle jamais (§7)
# =============================================================================================


def test_fetch_async_ne_bloque_pas_la_boucle():
    client, seen = _client()

    async def scenario():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(3):
                await asyncio.sleep(0)
                ticks += 1

        result, _ = await asyncio.gather(client.fetch_async("T10YIE"), heartbeat())
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result.series is not None and ticks == 3
    assert "series_id=T10YIE" in seen[0]


def test_fetch_async_propage_le_refus_de_politique():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked):
        asyncio.run(client.fetch_async("UNRATE&x=1"))
