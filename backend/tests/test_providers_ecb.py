"""Client SDMX de la BCE — YC, AME, SPF et les autres (D-057).

« Un seul service couvre plusieurs dataflows qu'on utilise séparément : YC (courbe de
rendement), AME (AMECO), SPF (consensus économistes). Même connecteur générique, seuls le
dataflow et la clé de série changent. » Et l'avertissement qui pèse le plus lourd :

    « clé de série exacte : télécharger le catalogue CSV du dataflow visé,
      ne jamais coder une clé en dur sans l'avoir confirmée dedans »

Trois choses que ces tests protègent en priorité : **aucune clé API n'est jamais requise ni
envoyée**, le dataflow **ICP est mort** et doit être refusé avant la requête, et une clé mal
formée ne doit pas pouvoir s'écrire dans la query string.
"""
from __future__ import annotations

import asyncio

import pytest

from app.providers import connectors as cx
from app.providers import ecb

CSV = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
       "YC.B.U2.EUR,B,2026-07-29,2.41,A\n"
       "YC.B.U2.EUR,B,2026-07-30,2.38,A\n"
       "YC.B.U2.EUR,B,2026-07-31,.,A\n")          # trou : la BCE écrit « . » comme FRED


def _client(payload=CSV, **kw):
    seen: list[str] = []

    def fetcher(url: str) -> str:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    return ecb.EcbClient(fetcher=fetcher, **kw), seen


# =============================================================================================
# Aucune clé API — et c'est prouvable, pas déclaré
# =============================================================================================


def test_aucune_cle_API_n_est_requise(monkeypatch):
    """Le service est public. Un client qui exigerait une clé refuserait des séries
    parfaitement accessibles — et un client qui en enverrait une la ferait fuiter."""
    monkeypatch.setattr("app.config.FRED_API_KEY", "SECRET-FRED")
    client, seen = _client()
    result = client.fetch("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y")
    assert result.error is None and result.series is not None
    assert "api_key" not in seen[0] and "SECRET-FRED" not in seen[0]
    assert "SECRET-FRED" not in result.url


def test_le_client_n_accepte_meme_pas_de_parametre_de_cle():
    import inspect
    params = inspect.signature(ecb.EcbClient.__init__).parameters
    assert "api_key" not in params


# =============================================================================================
# Interrogation générique — un connecteur, trois dataflows
# =============================================================================================


@pytest.mark.parametrize("dataflow,key", [
    ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y"),         # courbe — Arb 1 / D2
    ("AME", f"A.{ecb.AMECO_ZONE}.1.0.0.0.AVGDGP"),     # AMECO output gap — Arb 1
    ("SPF", "Q.U2.RGDP.POINT.M0M.Q.ECB"),              # consensus croissance — Arb 5
])
def test_interroge_les_trois_dataflows_demandes(dataflow, key):
    client, seen = _client()
    result = client.fetch(dataflow, key)
    assert result.error is None
    assert [o.value for o in result.series.observations] == [2.41, 2.38]
    assert result.series.dropped == 1
    assert seen[0] == f"https://data-api.ecb.europa.eu/service/data/{dataflow}/{key}?format=csvdata"


def test_l_endpoint_est_bien_celui_de_la_spec():
    client, seen = _client()
    client.fetch("EST", "B.EU000A2X2A25.WT")
    assert seen[0].startswith("https://data-api.ecb.europa.eu/service/data/")
    assert seen[0].endswith("?format=csvdata")


def test_une_cle_POINTEE_complete_se_decoupe_toute_seule():
    """Le registre écrit les clés `dataflow.reste` — c'est la forme des artefacts."""
    client, seen = _client()
    client.fetch_key("HICP.M.U2.N.000000.4.ANR")
    assert "/data/HICP/M.U2.N.000000.4.ANR?" in seen[0]


def test_serie_du_registre_par_sa_CLE_metier():
    client, seen = _client()
    result = client.fetch_catalog("yc_spot")
    assert result.error is None
    assert "/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y?" in seen[0]


def test_UNE_SEULE_construction_d_URL_BCE_pour_les_deux_chemins():
    """Le registre (`connectors.build_url`) et le client doivent produire la même URL — deux
    constructions séparées, c'est deux endroits où se tromper, et une divergence qu'on ne verrait
    qu'en production. Corollaire utile : les gardes du client valent aussi pour le registre."""
    from app.providers import catalog as cat
    for key in ("hicp_ez", "yc_spot", "estr", "spf_ez", "output_gap_ez"):
        spec = cat.BY_KEY[key]
        dataflow, _, series = spec.identifier.partition(".")
        assert cx.build_url(key) == ecb.data_url(dataflow, series), key


def test_les_dataflows_connus_sont_DOCUMENTES_avec_ce_qu_ils_servent():
    """Un opérateur doit pouvoir répondre « YC, c'est quoi ? » sans rouvrir les artefacts."""
    for code in ("YC", "AME", "SPF", "EST", "ILM", "HICP"):
        assert code in ecb.DATAFLOWS and ecb.DATAFLOWS[code]


# =============================================================================================
# Le piège qui casse en silence — ICP est mort
# =============================================================================================


def test_le_dataflow_ICP_est_REFUSE_avant_la_requete_et_nomme_son_remplacant():
    """Discontinué le 04.02.2026, remplacé par HICP à structure de clé identique. Laisser
    partir la requête ramènerait une erreur de service qu'on lirait comme une panne."""
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch("ICP", "M.U2.N.000000.4.ANR")
    assert "HICP" in str(e.value) and "04.02.2026" in str(e.value)
    assert seen == []


def test_le_refus_ICP_vaut_aussi_par_la_cle_pointee():
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch_key("ICP.M.U2.N.000000.4.ANR")
    assert seen == []


# =============================================================================================
# Refus de politique — rien ne part
# =============================================================================================


@pytest.mark.parametrize("dataflow", ["yc", "Y C", "YC?x=1", "YC/../", "", None, 42, "A" * 40])
def test_dataflow_mal_forme_refuse_AVANT_la_requete(dataflow):
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch(dataflow, "B.U2.EUR")
    assert seen == []


@pytest.mark.parametrize("key", ["B.U2 EUR", "B.U2?format=json", "B.U2&x=1", "B/U2",
                                 "", None, 42, "B." + "X" * 300])
def test_cle_mal_formee_refusee_AVANT_la_requete(key):
    """Sans ce garde, la clé s'écrit dans la query string : un `&` suffit à ajouter un
    paramètre à l'appel."""
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch("YC", key)
    assert seen == []


def test_une_ligne_C2_du_registre_reste_bloquee():
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("nairu_ez")
    assert "catalogue" in str(e.value).lower()
    assert seen == []


def test_une_ligne_du_registre_qui_n_est_pas_BCE_est_refusee():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("vixcls")
    assert "ECB_SDMX" in str(e.value)


# =============================================================================================
# Conditions de données — motif, jamais exception
# =============================================================================================


def test_reseau_mort_rend_un_MOTIF_pas_une_exception():
    client, _ = _client(payload=OSError("connection reset"))
    result = client.fetch("YC", "B.U2.EUR")
    assert result.series is None
    assert result.error and "SDMX BCE injoignable" in result.error


def test_reponse_illisible_est_un_MOTIF_pas_une_serie_vide():
    client, _ = _client(payload="<html>503</html>")
    result = client.fetch("YC", "B.U2.EUR")
    assert result.series is None and "illisible" in result.error


def test_reponse_geante_est_refusee_entiere():
    client, _ = _client(payload="TIME_PERIOD,OBS_VALUE\n" + " " * (cx.MAX_FEED_BYTES + 10))
    assert client.fetch("YC", "B.U2.EUR").series is None


# =============================================================================================
# Relever une clé au catalogue — l'avertissement le plus lourd de la spec, rendu actionnable
# =============================================================================================


def test_l_URL_du_catalogue_de_cles_est_fournie_pour_chaque_dataflow():
    """« Ne jamais coder une clé en dur sans l'avoir confirmée dans le catalogue » : encore
    faut-il savoir où le chercher."""
    url = ecb.series_keys_url("AME")
    assert url.startswith("https://data-api.ecb.europa.eu/service/data/AME")
    assert "serieskeysonly" in url and "api_key" not in url


def test_le_catalogue_de_cles_refuse_lui_aussi_ICP_et_le_mal_forme():
    for bad in ("ICP", "yc", "YC?x"):
        with pytest.raises(cx.SeriesBlocked):
            ecb.series_keys_url(bad)


# =============================================================================================
# Étage async
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

        result, _ = await asyncio.gather(
            client.fetch_async("SPF", "Q.U2.RGDP.POINT.M0M.Q.ECB"), heartbeat())
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result.series is not None and ticks == 3
    assert "/data/SPF/" in seen[0]


def test_fetch_async_propage_le_refus_de_politique():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked):
        asyncio.run(client.fetch_async("ICP", "M.U2.N.000000.4.ANR"))


def test_le_timeout_est_borne_comme_ailleurs():
    assert ecb.EcbClient(timeout_s=None).timeout_s == ecb.DEFAULT_TIMEOUT_S
    assert ecb.EcbClient(timeout_s=1e9).timeout_s == ecb.MAX_TIMEOUT_S


# =============================================================================================
# Borne de période — `startPeriod` / `endPeriod` (repris d'un script opérateur)
# =============================================================================================


def test_startPeriod_borne_la_requete_au_lieu_de_tout_telecharger():
    """Manquait au client : il ramenait l'historique complet à chaque appel. La borne est un
    paramètre SDMX REST standard, et elle change l'ordre de grandeur du transfert."""
    client, seen = _client()
    client.fetch("YC", "B.U2.EUR", start="2023-01-01")
    assert "startPeriod=2023-01-01" in seen[0] and "format=csvdata" in seen[0]


def test_endPeriod_aussi_et_les_deux_ensemble():
    client, seen = _client()
    client.fetch("YC", "B.U2.EUR", start="2023-01-01", end="2024-12-31")
    assert "startPeriod=2023-01-01" in seen[0] and "endPeriod=2024-12-31" in seen[0]


@pytest.mark.parametrize("periode", ["2023", "2023-01", "2023-01-02", "2023-Q1", "2023-S1",
                                     "2023-W05"])
def test_toutes_les_granularites_SDMX_sont_acceptees(periode):
    """SDMX borne aussi en trimestres, semestres et semaines — un client qui n'accepterait que
    des jours rendrait `AME` (annuel) et `SPF` (trimestriel) inbornables."""
    client, seen = _client()
    client.fetch("YC", "B.U2.EUR", start=periode)
    assert f"startPeriod={periode}" in seen[0]


@pytest.mark.parametrize("mauvaise", ["hier", "2023-13", "2023-01-02&x=1", "01/2023", 2023,
                                      "2023-Q5"])
def test_une_borne_mal_formee_est_refusee_AVANT_la_requete(mauvaise):
    """Elle finirait dans la query string : un `&` y ajouterait un paramètre."""
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch("YC", "B.U2.EUR", start=mauvaise)
    assert "période" in str(e.value).lower()
    assert seen == []


def test_la_borne_passe_aussi_par_la_cle_pointee_et_la_cle_metier():
    client, seen = _client()
    client.fetch_key("HICP.M.U2.N.000000.4.ANR", start="2023-01")
    client.fetch_catalog("yc_spot", start="2020")
    assert "startPeriod=2023-01" in seen[0] and "startPeriod=2020" in seen[1]


def test_l_ordre_des_parametres_est_STABLE():
    """URL stable = comparable d'un appel à l'autre, et testable."""
    client, seen = _client()
    client.fetch("YC", "B.U2.EUR", start="2023-01-01", end="2024-12-31")
    assert seen[0].endswith("?format=csvdata&startPeriod=2023-01-01&endPeriod=2024-12-31")


def test_assemblage_tabulaire_disponible_cote_BCE():
    """Hérité du harnais : le connecteur BCE n'a pas eu à le réécrire."""
    client, _ = _client()
    table = client.to_columns(["YC.B.U2.EUR", "HICP.M.U2.N"], start="2023-01-01")
    assert set(table.columns) == {"YC.B.U2.EUR", "HICP.M.U2.N"}
    assert table.rows == 2 and table.failed == {}
