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


# =============================================================================================
# Sortie propre — un thread ne s'annule pas, donc il doit être BORNÉ
# =============================================================================================


@pytest.mark.parametrize("given,attendu", [
    (None, fred.DEFAULT_TIMEOUT_S),                       # absent → défaut
    (float("inf"), fred.DEFAULT_TIMEOUT_S),               # absurde → défaut
    (float("nan"), fred.DEFAULT_TIMEOUT_S),
    ("30", fred.DEFAULT_TIMEOUT_S),                       # pas un nombre → défaut
    (0.0, fred.MIN_TIMEOUT_S),
    (-5.0, fred.MIN_TIMEOUT_S),
    (1e9, fred.MAX_TIMEOUT_S),
    (5.0, 5.0),
])
def test_le_timeout_est_TOUJOURS_borne(given, attendu):
    """`fetch_async` part en `asyncio.to_thread`, et un thread ne s'annule pas : à l'arrêt, la
    boucle rend la main tout de suite mais le thread vit jusqu'au timeout de la socket.
    `timeout_s=None` se traduirait en `urlopen(timeout=None)` — un thread qui ne meurt jamais
    et un Ctrl-C qui n'en finit pas."""
    assert fred.FredClient(api_key="K", timeout_s=given).timeout_s == attendu


def test_l_annulation_libere_la_BOUCLE_tout_de_suite_mais_pas_le_THREAD():
    """Constat mesuré, et c'est lui qui justifie la borne de timeout.

    L'annulation rend la main à la boucle d'événements immédiatement. Le THREAD, lui, continue
    jusqu'au bout de sa socket — et `asyncio.run` attend son pool à la fermeture. La durée d'un
    arrêt propre est donc exactement le timeout du fetch : sans borne, un arrêt qui n'en finit
    jamais."""
    import threading
    import time
    parti, liberer = threading.Event(), threading.Event()
    fini = []

    def fetcher(url: str) -> str:
        parti.set()
        liberer.wait(5.0)                                 # simule une socket qui traîne
        fini.append(True)
        return OBS

    client = fred.FredClient(api_key="K", fetcher=fetcher)

    async def scenario():
        task = asyncio.create_task(client.fetch_async("UNRATE"))
        await asyncio.to_thread(parti.wait, 5.0)
        debut = time.perf_counter()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        libere_en = time.perf_counter() - debut
        assert not fini                                   # le thread, lui, tourne toujours
        liberer.set()                                     # (sinon la fermeture attendrait 5 s)
        return libere_en

    assert asyncio.run(scenario()) < 0.5


# =============================================================================================
# Assemblage tabulaire — `to_columns` (pur) et `to_dataframe` (pandas, optionnel)
# =============================================================================================

DEUX = {
    "UNRATE": json.dumps({"observations": [{"date": "2026-05-01", "value": "4.1"},
                                           {"date": "2026-06-01", "value": "4.2"}]}),
    "GDPC1": json.dumps({"observations": [{"date": "2026-04-01", "value": "23000"}]}),
    "DFF": json.dumps({"observations": [{"date": "2026-06-01", "value": "."}]}),   # que des trous
}


def _multi(payloads=DEUX, casse=()):
    def fetcher(url: str) -> str:
        sid = url.split("series_id=")[1].split("&")[0]
        if sid in casse:
            raise OSError("connection reset")
        return payloads[sid]
    return fred.FredClient(api_key="K", fetcher=fetcher)


def test_to_columns_aligne_les_series_sur_l_union_des_PERIODES():
    table = _multi().to_columns(["UNRATE", "GDPC1"])
    assert table.periods == ("2026-04-01", "2026-05-01", "2026-06-01")
    assert table.columns["UNRATE"] == (None, 4.1, 4.2)
    assert table.columns["GDPC1"] == (23000.0, None, None)


def test_une_serie_en_ECHEC_n_est_JAMAIS_une_colonne_de_NaN():
    """Le défaut central du script d'origine : un échec réseau et une observation absente
    devenaient indistinguables. Ici l'échec sort du tableau et porte son motif (§3)."""
    table = _multi(casse={"GDPC1"}).to_columns(["UNRATE", "GDPC1"])
    assert "GDPC1" not in table.columns
    assert "GDPC1" in table.failed and "injoignable" in table.failed["GDPC1"]
    assert "UNRATE" in table.columns                      # les autres passent quand même


def test_la_COUVERTURE_est_rendue_car_un_tableau_mixte_est_creux_par_nature():
    """Mêler du quotidien, du mensuel et du trimestriel produit un tableau très majoritairement
    vide. Ce n'est pas un défaut — mais le lire sans le savoir en est un."""
    table = _multi().to_columns(["UNRATE", "GDPC1"])
    assert table.coverage == {"UNRATE": 2, "GDPC1": 1}
    assert table.rows == 3


def test_une_serie_LISIBLE_mais_SANS_aucune_valeur_est_un_echec_explicite():
    """`DFF` ne renvoie que des trous : la série est lisible, mais il n'y a rien dedans. Une
    colonne entièrement vide se lirait comme « pas encore publié »."""
    table = _multi().to_columns(["UNRATE", "DFF"])
    assert "DFF" not in table.columns and "DFF" in table.failed


def test_to_columns_ne_REMPLIT_jamais_les_trous():
    """Aucun `ffill` : une valeur reportée est une valeur inventée, et un z-score calculé sur
    une série interpolée n'est pas un z-score. Le remplissage, s'il a lieu, est une décision
    de l'appelant — jamais un défaut de la couche d'accès (§3)."""
    import ast
    import inspect
    # Sur le CODE, pas sur la prose : la docstring nomme volontiers ce qu'elle interdit.
    arbre = ast.parse(inspect.getsource(fred))
    appels = {n.attr for n in ast.walk(arbre) if isinstance(n, ast.Attribute)}
    appels |= {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    for interdit in ("ffill", "fillna", "bfill", "interpolate", "pad", "reindex", "asfreq"):
        assert interdit not in appels, interdit


def test_to_columns_par_les_CLES_METIER_du_registre():
    table = _multi({"VIXCLS": DEUX["UNRATE"]}).to_columns(["vixcls"], catalog=True)
    assert "vixcls" in table.columns                       # colonne nommée par la clé métier
    assert table.coverage["vixcls"] == 2


def test_to_columns_applique_le_portillon_du_registre():
    with pytest.raises(cx.SeriesBlocked):
        _multi().to_columns(["oecd_cli"], catalog=True)


def test_to_columns_vide_ne_ment_pas():
    table = _multi(casse={"UNRATE", "GDPC1"}).to_columns(["UNRATE", "GDPC1"])
    assert table.columns == {} and table.periods == () and table.rows == 0
    assert set(table.failed) == {"UNRATE", "GDPC1"}


def test_to_dataframe_rend_un_DataFrame_indexe_par_la_PERIODE():
    pd = pytest.importorskip("pandas")
    frame = _multi().to_dataframe(["UNRATE", "GDPC1"])
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.index) == ["2026-04-01", "2026-05-01", "2026-06-01"]
    assert list(frame.columns) == ["UNRATE", "GDPC1"]
    assert frame.loc["2026-06-01", "UNRATE"] == 4.2
    assert pd.isna(frame.loc["2026-04-01", "UNRATE"])


def test_to_dataframe_garde_la_periode_TELLE_QUELLE_par_defaut():
    """« 2026-Q2 » ne devient pas un jour : la source ne publie pas ce jour-là. L'index
    horodaté existe, mais il est OPT-IN — c'est l'appelant qui accepte la précision inventée."""
    pytest.importorskip("pandas")
    trimestre = json.dumps({"observations": [{"date": "2026", "value": "1.0"}]})
    frame = _multi({"X": trimestre}).to_dataframe(["X"])
    assert list(frame.index) == ["2026"]


def test_to_dataframe_index_horodate_est_OPT_IN():
    pd = pytest.importorskip("pandas")
    frame = _multi().to_dataframe(["UNRATE"], datetime_index=True)
    assert isinstance(frame.index, pd.DatetimeIndex)


def test_to_dataframe_expose_les_ECHECS_sans_les_noyer_dans_le_tableau():
    pytest.importorskip("pandas")
    client = _multi(casse={"GDPC1"})
    table = client.to_columns(["UNRATE", "GDPC1"])
    frame = client.to_dataframe(["UNRATE", "GDPC1"])
    assert "GDPC1" not in frame.columns
    assert table.failed["GDPC1"]                            # le motif reste consultable


def test_to_dataframe_SANS_pandas_dit_quoi_installer(monkeypatch):
    """pandas n'est PAS une dépendance du terminal : le hot path n'a pas à porter une pile
    numérique de plusieurs dizaines de Mo pour une commodité d'exploration. L'absence doit donc
    produire un message actionnable, pas un ImportError nu."""
    import builtins
    vrai_import = builtins.__import__

    def sans_pandas(name, *a, **kw):
        if name == "pandas":
            raise ImportError("No module named 'pandas'")
        return vrai_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", sans_pandas)
    with pytest.raises(RuntimeError) as e:
        _multi().to_dataframe(["UNRATE"])
    assert "pip install pandas" in str(e.value)
