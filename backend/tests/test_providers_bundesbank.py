"""Client REST Bundesbank — BBSIS et la jambe EUR du breakeven (D-057).

« Remplace la Finanzagentur, qui publie la donnée mais sans API. Jambe nominale (Svensson
quotidien) et rendements par ISIN. » Deux lignes du registre en dépendent :

- `bund_nominal` (C1) — courbe Svensson, `R10XX` encode la maturité résiduelle ;
- `bundei_real` (C2) — rendement du Bund€i par ISIN, clé encore à relever au portail. C'est
  « la ligne au meilleur rapport effort/déblocage » : elle ferme D3 **et** `rdiff` côté D5.

Ce que ces tests protègent : aucune clé API, le dialecte CSV réel (en-têtes de métadonnées,
jours fériés « . », séparateur), et surtout **on ne fabrique pas une clé de série par
analogie** — même quand le motif saute aux yeux.
"""
from __future__ import annotations

import asyncio

import pytest

from app.providers import bundesbank as bb
from app.providers import catalog as cat
from app.providers import connectors as cx

CSV = ("BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A,Rendement\n"
       "unit,Prozent\n"
       "TIME_PERIOD,VALUE\n"
       "2026-07-29,2.51\n"
       "2026-07-30,.\n"                                    # jour férié
       "2026-07-31,2.55\n")

CSV_PV = ("BBSIS.D.I.ZST;Rendite\n"
          "unit;Prozent\n"
          "2026-07-29;2,51\n"
          "2026-07-30;.\n"
          "2026-07-31;2,55\n")


def _client(payload=CSV, **kw):
    seen: list[str] = []

    def fetcher(url: str) -> str:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    return bb.BundesbankClient(fetcher=fetcher, **kw), seen


# =============================================================================================
# Aucune clé API
# =============================================================================================


def test_aucune_cle_API_n_est_requise_ni_envoyee(monkeypatch):
    monkeypatch.setattr("app.config.FRED_API_KEY", "SECRET-FRED")
    client, seen = _client()
    result = client.fetch("BBSIS", "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A")
    assert result.error is None
    assert "api_key" not in seen[0] and "SECRET-FRED" not in seen[0]


def test_le_client_n_accepte_meme_pas_de_parametre_de_cle():
    import inspect
    assert "api_key" not in inspect.signature(bb.BundesbankClient.__init__).parameters


# =============================================================================================
# Interrogation
# =============================================================================================


def test_l_endpoint_est_bien_celui_de_la_spec():
    client, seen = _client()
    client.fetch("BBSIS", "D.I.ZST")
    assert seen[0] == ("https://api.statistiken.bundesbank.de/rest/download/BBSIS/D.I.ZST"
                       "?format=csv&lang=en")


def test_lit_la_serie_en_sautant_les_metadonnees_et_les_jours_feries():
    client, _ = _client()
    result = client.fetch("BBSIS", "D.I.ZST")
    assert [(o.date, o.value) for o in result.series.observations] == [("2026-07-29", 2.51),
                                                                       ("2026-07-31", 2.55)]
    assert result.series.dropped >= 1


def test_une_cle_POINTEE_complete_se_decoupe_toute_seule():
    client, seen = _client()
    client.fetch_key("BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A")
    assert "/download/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?" in seen[0]


def test_serie_du_registre_par_sa_CLE_metier():
    client, seen = _client()
    result = client.fetch_catalog("bund_nominal")
    assert result.error is None
    assert "/download/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?" in seen[0]


def test_le_separateur_POINT_VIRGULE_est_reconnu():
    """Le dialecte exact n'est pas donné par la spec, et les exports allemands utilisent
    volontiers « ; » avec la virgule décimale. Sans reconnaissance, la réponse tombait en
    « illisible » : fail-closed, donc pas de fausse donnée — mais un cul-de-sac."""
    client, _ = _client(payload=CSV_PV)
    result = client.fetch("BBSIS", "D.I.ZST")
    assert [(o.date, o.value) for o in result.series.observations] == [("2026-07-29", 2.51),
                                                                       ("2026-07-31", 2.55)]


# =============================================================================================
# On ne fabrique pas une clé par analogie
# =============================================================================================


def test_les_tenors_Svensson_CONFIRMES_par_la_spec_sont_disponibles():
    """La spec donne `R10XX` (10 ans) et `R05XX` (5 ans) — et dit que le code encode la
    maturité résiduelle."""
    assert "R10XX" in bb.svensson_key(10)
    assert "R05XX" in bb.svensson_key(5)
    assert bb.svensson_key(10) == cat.BY_KEY["bund_nominal"].identifier


@pytest.mark.parametrize("annees", [2, 7, 30, 0, -1, None, "10"])
def test_un_tenor_NON_confirme_est_refuse_meme_si_le_motif_saute_aux_yeux(annees):
    """`R02XX` pour 2 ans est une inférence, pas une clé vérifiée. C'est exactement ce que la
    doctrine interdit : « ne jamais coder une clé en dur sans l'avoir confirmée au catalogue ».
    Le motif évident est le piège, pas la preuve."""
    with pytest.raises(cx.SeriesBlocked) as e:
        bb.svensson_key(annees)
    assert "confirm" in str(e.value).lower()


def test_la_ligne_du_Bund_ei_reste_BLOQUEE_et_dit_ou_relever():
    """`bundei_real` est C2 : ISIN choisi, connecteur écrit, il ne manque que le relevé."""
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("bundei_real")
    assert "W138" in str(e.value)
    assert seen == []


def test_le_statut_du_Bund_ei_rappelle_l_ecart_de_tenor_hérité():
    """Relever la clé ne suffira pas : la jambe EUR sera à 6,7 ans contre 10 ans côté US."""
    etat = bb.bundei_status(now=1785542400.0)                # 2026-08-01
    assert etat["bloque"] is True and "W138" in etat["a_faire"]
    assert etat["roll"]["status"] == "BASCULE_REQUISE"
    assert 3.2 < etat["roll"]["tenor_drift_years"] < 3.4


# =============================================================================================
# Refus de politique
# =============================================================================================


@pytest.mark.parametrize("dataset", ["bbsis", "BB SIS", "BBSIS?x=1", "", None, 42, "A" * 40])
def test_dataset_mal_forme_refuse_AVANT_la_requete(dataset):
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch(dataset, "D.I.ZST")
    assert seen == []


@pytest.mark.parametrize("key", ["D.I ZST", "D.I?format=json", "D.I&x=1", "D/I", "", None, 42])
def test_cle_mal_formee_refusee_AVANT_la_requete(key):
    client, seen = _client()
    with pytest.raises(cx.SeriesBlocked):
        client.fetch("BBSIS", key)
    assert seen == []


def test_une_ligne_du_registre_qui_n_est_pas_BUNDESBANK_est_refusee():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch_catalog("vixcls")
    assert "BUNDESBANK" in str(e.value)


def test_UNE_SEULE_construction_d_URL_BUNDESBANK_pour_les_deux_chemins():
    spec = cat.BY_KEY["bund_nominal"]
    dataset, _, key = spec.identifier.partition(".")
    assert cx.build_url("bund_nominal") == bb.data_url(dataset, key)


# =============================================================================================
# Conditions de données & async
# =============================================================================================


def test_reseau_mort_rend_un_MOTIF_pas_une_exception():
    client, _ = _client(payload=OSError("connection reset"))
    result = client.fetch("BBSIS", "D.I.ZST")
    assert result.series is None and "Bundesbank injoignable" in result.error


def test_reponse_sans_aucune_ligne_datee_est_illisible_pas_vide():
    client, _ = _client(payload="unit,Prozent\nsource,Bundesbank\n")
    result = client.fetch("BBSIS", "D.I.ZST")
    assert result.series is None and "illisible" in result.error


def test_fetch_async_ne_bloque_pas_la_boucle():
    client, seen = _client()

    async def scenario():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(3):
                await asyncio.sleep(0)
                ticks += 1

        result, _ = await asyncio.gather(client.fetch_async("BBSIS", "D.I.ZST"), heartbeat())
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result.series is not None and ticks == 3
    assert "/download/BBSIS/" in seen[0]


def test_fetch_async_propage_le_refus_de_politique():
    client, _ = _client()
    with pytest.raises(cx.SeriesBlocked):
        asyncio.run(client.fetch_async("BBSIS", "D.I&x=1"))


def test_le_timeout_est_borne_comme_ailleurs():
    assert bb.BundesbankClient(timeout_s=None).timeout_s == bb.DEFAULT_TIMEOUT_S
    assert bb.BundesbankClient(timeout_s=1e9).timeout_s == bb.MAX_TIMEOUT_S
