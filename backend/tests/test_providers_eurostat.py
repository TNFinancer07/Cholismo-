"""Client Eurostat — API de dissémination (D-057).

Trois datasets : `ei_bssi_m_r2` (ESI, proxy PMI zone euro — D1, w 0.30), `nama_10_lp_ulc`
(productivité — D5 / BEER) et `une_rt_m` (chômage — Arb 2, jambe EUR de la courbe de Phillips).

Ce que ces tests protègent en priorité : **aucune clé API**, et surtout **le cube doit être
réduit avant d'être lu**. Un dataset Eurostat non filtré rend pays × unité × âge × temps aplati
en un seul tableau — le lire comme une série produit des nombres plausibles et faux (cf. le
correctif de régression dans `test_providers_connectors`).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.providers import connectors as cx
from app.providers import eurostat as es

SERIE = json.dumps({
    "id": ["geo", "time"], "size": [1, 3],
    "dimension": {"geo": {"category": {"index": {"EA20": 0}}},
                  "time": {"category": {"index": {"2026-05": 0, "2026-06": 1, "2026-07": 2}}}},
    "value": {"0": 6.1, "1": ":", "2": 6.3},           # « : » = trou Eurostat
})

CUBE = json.dumps({
    "id": ["time", "geo", "unit"], "size": [3, 3, 2],
    "dimension": {"time": {"category": {"index": {"2026-05": 0, "2026-06": 1, "2026-07": 2}}},
                  "geo": {"category": {"index": {"EA20": 0, "DE": 1, "FR": 2}}},
                  "unit": {"category": {"index": {"PC_ACT": 0, "THS_PER": 1}}}},
    "value": {str(i): float(i) for i in range(18)},
})


def _client(payload=SERIE, **kw):
    seen: list[str] = []

    def fetcher(url: str) -> str:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    return es.EurostatClient(fetcher=fetcher, **kw), seen


# =============================================================================================
# Aucune clé API
# =============================================================================================


def test_aucune_cle_API_n_est_requise_ni_envoyee(monkeypatch):
    monkeypatch.setattr("app.config.FRED_API_KEY", "SECRET-FRED")
    client, seen = _client()
    result = client.fetch("une_rt_m", geo="EA20")
    assert result.error is None
    assert "api_key" not in seen[0] and "SECRET-FRED" not in seen[0]


def test_le_client_n_accepte_meme_pas_de_parametre_de_cle():
    import inspect
    assert "api_key" not in inspect.signature(es.EurostatClient.__init__).parameters


# =============================================================================================
# Les trois datasets
# =============================================================================================


@pytest.mark.parametrize("dataset", ["ei_bssi_m_r2", "nama_10_lp_ulc", "une_rt_m"])
def test_interroge_les_trois_datasets(dataset):
    client, seen = _client()
    result = client.fetch(dataset, geo="EA20")
    assert result.error is None
    assert [(o.date, o.value) for o in result.series.observations] == [("2026-05", 6.1),
                                                                       ("2026-07", 6.3)]
    assert result.series.dropped == 1
    assert seen[0].startswith(
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/" + dataset)


def test_les_datasets_sont_DOCUMENTES_avec_ce_qu_ils_alimentent():
    for dataset in ("ei_bssi_m_r2", "nama_10_lp_ulc", "une_rt_m"):
        assert dataset in es.DATASETS and es.DATASETS[dataset]


def test_les_filtres_partent_dans_l_URL_et_sont_ORDONNES():
    """Ordre stable = URL stable : comparable d'un appel à l'autre, et testable."""
    client, seen = _client()
    client.fetch("une_rt_m", unit="PC_ACT", geo="EA20", s_adj="SA")
    assert seen[0].endswith("?format=JSON&geo=EA20&s_adj=SA&unit=PC_ACT")


def test_serie_du_registre_par_sa_CLE_metier_avec_ses_filtres():
    """`unrate_ez` porte `geo=EA20` dans le registre (« filtre geo=EA20 », spec Arb 2) : la
    clé métier doit suffire, sans que l'appelant ait à se souvenir du filtre."""
    client, seen = _client()
    result = client.fetch_catalog("unrate_ez")
    assert result.error is None
    assert "/data/une_rt_m?" in seen[0] and "geo=EA20" in seen[0]


# =============================================================================================
# Le cube — refusé, avec ce qu'il faut épingler
# =============================================================================================


def test_un_cube_NON_FILTRE_ne_devient_pas_une_serie_et_le_motif_NOMME_les_dimensions():
    client, _ = _client(payload=CUBE)
    result = client.fetch("une_rt_m")
    assert result.series is None
    assert "geo" in result.error and "unit" in result.error
    assert "filtr" in result.error.lower()


def test_le_motif_du_cube_est_DISTINCT_de_celui_d_une_reponse_illisible():
    """Deux causes, deux messages : chercher un défaut de parsing quand il manque juste un
    filtre fait perdre l'après-midi."""
    cube, _ = _client(payload=CUBE)
    casse, _ = _client(payload="<html>503</html>")
    assert cube.fetch("une_rt_m").error != casse.fetch("une_rt_m").error
    assert "illisible" in casse.fetch("une_rt_m").error


# =============================================================================================
# Refus de politique — rien ne part
# =============================================================================================


@pytest.mark.parametrize("dataset", ["Une_Rt_M", "une rt m", "une_rt_m?x=1", "../etc",
                                     "", None, 42, "a" * 80])
def test_dataset_mal_forme_refuse_AVANT_la_requete(dataset):
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch(dataset)
    assert seen == []


@pytest.mark.parametrize("nom,valeur", [("geo", "EA20&unit=X"), ("ge o", "EA20"),
                                        ("geo", "EA 20"), ("geo", None), ("format", "CSV")])
def test_filtre_mal_forme_refuse_AVANT_la_requete(nom, valeur):
    """Sans ce garde, un filtre s'écrit dans la query string — et `format` est réservé : le
    parser ne sait lire que le JSON-stat."""
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch("une_rt_m", **{nom: valeur})
    assert seen == []


def test_une_ligne_du_registre_qui_n_est_pas_EUROSTAT_est_refusee():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("vixcls")
    assert "EUROSTAT" in str(e.value)


def test_UNE_SEULE_construction_d_URL_EUROSTAT_pour_les_deux_chemins():
    from app.providers import catalog as cat
    for key in ("pmi_ez", "prod_ez", "unrate_ez"):
        spec = cat.BY_KEY[key]
        assert cx.build_url(key) == es.data_url(spec.identifier, dict(spec.filters)), key


# =============================================================================================
# Conditions de données & async
# =============================================================================================


def test_reseau_mort_rend_un_MOTIF_pas_une_exception():
    client, _ = _client(payload=OSError("connection reset"))
    result = client.fetch("une_rt_m", geo="EA20")
    assert result.series is None and "Eurostat injoignable" in result.error


def test_fetch_async_ne_bloque_pas_la_boucle():
    client, seen = _client()

    async def scenario():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(3):
                await asyncio.sleep(0)
                ticks += 1

        result, _ = await asyncio.gather(client.fetch_async("ei_bssi_m_r2", geo="EA20"),
                                         heartbeat())
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result.series is not None and ticks == 3
    assert "/data/ei_bssi_m_r2?" in seen[0]


def test_fetch_async_propage_le_refus_de_politique():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked):
        asyncio.run(client.fetch_async("une rt m"))


def test_le_timeout_est_borne_comme_ailleurs():
    assert es.EurostatClient(timeout_s=None).timeout_s == es.DEFAULT_TIMEOUT_S
    assert es.EurostatClient(timeout_s=1e9).timeout_s == es.MAX_TIMEOUT_S
