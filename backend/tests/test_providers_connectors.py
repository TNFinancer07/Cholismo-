"""Sept connecteurs génériques — D-057.

« Sept connecteurs génériques couvrent les 49 lignes […] les coder une fois, les réutiliser
partout plutôt que dupliquer. » Ce fichier vérifie les deux moitiés du contrat :

- **construction d'URL** : conforme au registre, et REFUSÉE dès que la ligne ne l'autorise pas
  (C2/C3, paramètre, ou fournisseur sans REST) ;
- **parsing PUR** : un flux illisible rend `None` (l'appelant garde son ancien cache, doctrine
  D-050), une LIGNE corrompue est écartée et COMPTÉE — jamais de troncature silencieuse.
"""
from __future__ import annotations

import json

import pytest

from app.providers import catalog as cat
from app.providers import connectors as cx

# =============================================================================================
# Portillon d'accès — le registre commande, le connecteur obéit
# =============================================================================================


def test_une_ligne_C2_ne_produit_JAMAIS_d_URL():
    """Le cœur de la doctrine : pas d'identifiant → pas de requête. Une URL « probable »
    partirait chercher une clé inventée et ramènerait une erreur qu'on lirait comme une panne."""
    with pytest.raises(cx.SeriesBlocked) as e:
        cx.build_url("oecd_cli")
    assert "catalogue" in str(e.value).lower()


def test_un_parametre_ne_produit_JAMAIS_d_URL():
    with pytest.raises(cx.SeriesBlocked):
        cx.build_url("d4_coeff")


def test_une_ligne_C1_SANS_REST_le_dit_au_lieu_de_fabriquer_une_URL():
    """Le SPF de Philadelphie est vérifié (C1) mais n'a pas de REST : l'absence est
    STRUCTURELLE. Collectable et fetchable par HTTP ne sont pas la même chose."""
    assert cat.fetch_block_reason("spf_us") is None
    assert cx.has_rest_endpoint("spf_us") is False
    with pytest.raises(cx.SeriesBlocked) as e:
        cx.build_url("spf_us")
    assert "REST" in str(e.value)


def test_les_URL_des_lignes_C1_couvrent_les_sept_familles():
    families = {s.provider for s in cat.fetchable() if cx.has_rest_endpoint(s.key)}
    assert {cat.Provider.FRED, cat.Provider.ECB_SDMX, cat.Provider.EUROSTAT,
            cat.Provider.BUNDESBANK, cat.Provider.CFTC_SOCRATA, cat.Provider.SDMX_INTL,
            cat.Provider.YFINANCE} <= families


def test_toute_ligne_REST_collectable_construit_une_URL_plausible():
    for spec in cat.fetchable():
        if not cx.has_rest_endpoint(spec.key):
            continue
        url = cx.build_url(spec.key, api_key="K", contract="ZQZ26")
        assert url.startswith("https://"), spec.key
        assert " " not in url, spec.key


def test_ECB_le_dataflow_se_deduit_de_la_cle_pas_d_une_table_parallele():
    url = cx.build_url("hicp_ez")
    assert "/service/data/HICP/M.U2.N.000000.4.ANR" in url
    assert "format=csvdata" in url


def test_FRED_sans_cle_API_ne_part_pas_a_l_aveugle():
    with pytest.raises(cx.SeriesBlocked) as e:
        cx.build_url("vixcls", api_key="")
    assert "clé API" in str(e.value)


def test_la_cle_API_n_apparait_JAMAIS_dans_ce_qu_on_affiche():
    """Un registre exposé en REST ne doit pas publier le secret de l'opérateur."""
    described = cx.describe_endpoint("vixcls")
    assert "SECRET" not in described
    assert "{api_key}" in described
    url = cx.build_url("vixcls", api_key="SECRET")
    assert "SECRET" in url and "SECRET" not in cx.redact(url)


def test_ZQ_est_une_RACINE_pas_un_ticker():
    """`ois_usd` porte « ZQ » : sans le contrat (mois/année), il n'y a pas de série à demander."""
    with pytest.raises(cx.SeriesBlocked) as e:
        cx.build_url("ois_usd")
    assert "contrat" in str(e.value).lower()
    assert "ZQZ26" in cx.build_url("ois_usd", contract="ZQZ26")


# =============================================================================================
# Parsers — purs, défensifs, jamais silencieux
# =============================================================================================

FRED_OK = json.dumps({"observations": [
    {"date": "2026-07-29", "value": "15.2"},
    {"date": "2026-07-30", "value": "."},          # marqueur FRED de valeur manquante
    {"date": "2026-07-31", "value": "16.0"},
]})


def test_FRED_le_point_est_un_TROU_pas_un_zero():
    parsed = cx.parse_fred_json(FRED_OK)
    assert [o.value for o in parsed.observations] == [15.2, 16.0]
    assert parsed.dropped == 1


def test_EUROSTAT_le_deux_points_est_un_TROU():
    """Eurostat marque le manquant par « : » — le lire comme un nombre serait une valeur
    inventée, le lire comme 0 serait pire."""
    payload = json.dumps({
        "value": {"0": 101.2, "1": ":", "2": 99.8},
        "dimension": {"time": {"category": {"index": {"2026-05": 0, "2026-06": 1, "2026-07": 2}}}},
    })
    parsed = cx.parse_eurostat_json(payload)
    assert [(o.date, o.value) for o in parsed.observations] == [("2026-05", 101.2),
                                                               ("2026-07", 99.8)]
    assert parsed.dropped == 1


def _cube(ordre, valeurs):
    """Réponse JSON-stat 3 pays × 3 mois. `ordre` fixe l'aplatissement (row-major sur `id`)."""
    dims = {"geo": {"category": {"index": {"EA20": 0, "DE": 1, "FR": 2}}},
            "time": {"category": {"index": {"2026-05": 0, "2026-06": 1, "2026-07": 2}}}}
    return json.dumps({"id": list(ordre), "size": [3, 3], "dimension": dims,
                       "value": {str(i): v for i, v in enumerate(valeurs)}})


def test_REGRESSION_un_cube_NON_FILTRE_ne_doit_JAMAIS_passer_pour_une_serie():
    """Défaut réel (D-057) : le parser indexait `value` par la position TEMPS, ce qui n'est
    correct que si toutes les autres dimensions sont réduites à une valeur.

    Avec `id = [time, geo]`, il rendait 6.1 / 3.1 / 7.1 — soit trois PAYS lus comme trois
    DATES. Un chômage zone euro affiché à 3,1 % puis 7,1 % : la valeur avait l'air d'une
    mesure. C'est le mensonge que ce terminal refuse (§3).

    Et avec `id = [geo, time]`, il rendait par HASARD la bonne série (celle de EA20) — que
    personne n'avait demandée. Les deux cas sont refusés : on ne choisit pas un pays à la place
    de l'opérateur."""
    piege = _cube(["time", "geo"], [6.1, 3.1, 7.1, 6.2, 3.2, 7.2, 6.3, 3.3, 7.3])
    chance = _cube(["geo", "time"], [6.1, 6.2, 6.3, 3.1, 3.2, 3.3, 7.1, 7.2, 7.3])
    assert cx.parse_eurostat_json(piege) is None
    assert cx.parse_eurostat_json(chance) is None


def test_le_motif_NOMME_les_dimensions_a_epingler():
    """Un « non » ne suffit pas : ce qu'on veut savoir, c'est QUOI filtrer."""
    assert cx.eurostat_open_dimensions(_cube(["time", "geo"], [0.0] * 9)) == ("geo",)


def test_un_cube_REDUIT_a_une_serie_passe_quel_que_soit_l_ordre():
    """Une fois `geo` épinglé, la dimension reste présente avec une seule valeur — c'est la
    forme normale d'une réponse filtrée, et elle doit passer dans les deux ordres."""
    for ordre, size in ((["geo", "time"], [1, 3]), (["time", "geo"], [3, 1])):
        payload = json.dumps({
            "id": ordre, "size": size,
            "dimension": {"geo": {"category": {"index": {"EA20": 0}}},
                          "time": {"category": {"index": {"2026-05": 0, "2026-06": 1,
                                                          "2026-07": 2}}}},
            "value": {"0": 6.1, "1": 6.2, "2": 6.3}})
        parsed = cx.parse_eurostat_json(payload)
        assert parsed is not None and [o.value for o in parsed.observations] == [6.1, 6.2, 6.3]
        assert cx.eurostat_open_dimensions(payload) == ()


def test_une_taille_qui_CONTREDIT_l_index_temps_est_illisible():
    """`size` et l'index doivent raconter la même chose : sinon l'aplatissement qu'on suppose
    n'est pas celui de la réponse."""
    payload = json.dumps({
        "id": ["time"], "size": [7],
        "dimension": {"time": {"category": {"index": {"2026-05": 0, "2026-06": 1}}}},
        "value": {"0": 1.0, "1": 2.0}})
    assert cx.parse_eurostat_json(payload) is None


def test_SDMX_CSV_lit_les_colonnes_par_NOM_pas_par_position():
    """Un fournisseur qui ajoute une colonne ne doit pas décaler toute la série."""
    csv = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
           "HICP.M.U2,M,2026-05,2.4,A\n"
           "HICP.M.U2,M,2026-06,2.2,A\n")
    parsed = cx.parse_sdmx_csv(csv)
    assert [(o.date, o.value) for o in parsed.observations] == [("2026-05", 2.4), ("2026-06", 2.2)]


def test_SDMX_CSV_sans_les_colonnes_attendues_est_ILLISIBLE_pas_vide():
    """`None` ≠ `[]` : illisible fait garder l'ancien cache, vide serait pris pour un fait."""
    assert cx.parse_sdmx_csv("a,b\n1,2\n") is None


def test_BUNDESBANK_saute_les_en_tetes_de_metadonnees_et_les_jours_feries():
    csv = ("BBSIS.D.I.ZST...,Rendement\n"
           "unit,Prozent\n"
           "TIME_PERIOD,VALUE\n"
           "2026-07-29,2.51\n"
           "2026-07-30,.\n"                        # jour férié
           "2026-07-31,2.55\n")
    parsed = cx.parse_bundesbank_csv(csv)
    assert [(o.date, o.value) for o in parsed.observations] == [("2026-07-29", 2.51),
                                                                ("2026-07-31", 2.55)]
    assert parsed.dropped >= 1


def test_SOCRATA_lit_le_champ_demande_et_ignore_les_lignes_sans_lui():
    payload = json.dumps([
        {"report_date_as_yyyy_mm_dd": "2026-07-28T00:00:00.000", "noncomm_positions_long_all": "1200"},
        {"report_date_as_yyyy_mm_dd": "2026-07-21T00:00:00.000"},          # champ absent
        {"report_date_as_yyyy_mm_dd": "2026-07-14T00:00:00.000", "noncomm_positions_long_all": "900"},
    ])
    parsed = cx.parse_socrata_json(payload, value_field="noncomm_positions_long_all")
    assert [(o.date, o.value) for o in parsed.observations] == [("2026-07-14", 900.0),
                                                                ("2026-07-28", 1200.0)]
    assert parsed.dropped == 1


def test_DBNOMICS_periode_et_valeur_sont_deux_listes_PARALLELES():
    payload = json.dumps({"series": {"docs": [
        {"period": ["2026-05", "2026-06", "2026-07"], "value": [99.1, None, 100.4]}]}})
    parsed = cx.parse_dbnomics_json(payload)
    assert [(o.date, o.value) for o in parsed.observations] == [("2026-05", 99.1),
                                                                ("2026-07", 100.4)]
    assert parsed.dropped == 1


def test_DBNOMICS_listes_de_longueurs_DIFFERENTES_sont_illisibles():
    """Un désalignement décale toute la série d'un cran : mieux vaut ne rien lire."""
    payload = json.dumps({"series": {"docs": [{"period": ["2026-05", "2026-06"], "value": [1.0]}]}})
    assert cx.parse_dbnomics_json(payload) is None


def test_YAHOO_prend_la_cloture_et_ecarte_les_lignes_nulles():
    csv = ("Date,Open,High,Low,Close,Adj Close,Volume\n"
           "2026-07-29,100,101,99,100.5,100.5,1000\n"
           "2026-07-30,null,null,null,null,null,null\n"
           "2026-07-31,101,102,100,101.5,101.5,1100\n")
    parsed = cx.parse_yahoo_csv(csv)
    assert [(o.date, o.value) for o in parsed.observations] == [("2026-07-29", 100.5),
                                                                ("2026-07-31", 101.5)]
    assert parsed.dropped == 1


@pytest.mark.parametrize("parser", [cx.parse_fred_json, cx.parse_eurostat_json,
                                    cx.parse_sdmx_csv, cx.parse_bundesbank_csv,
                                    cx.parse_dbnomics_json, cx.parse_yahoo_csv])
def test_flux_ILLISIBLE_rend_None_jamais_une_exception(parser):
    for junk in ("", "<html>503</html>", "{", "\x00\x01", "null"):
        assert parser(junk) is None


def test_flux_OBESE_est_EMPOISONNE_donc_refuse_ENTIER():
    """Doctrine D-050 : tronquer masquerait des observations sans le dire — et sur une série
    macro, la coupe tomberait sur les points les plus récents."""
    huge = json.dumps({"observations": [{"date": "2026-01-01", "value": "1"}]}) + " " * (
        cx.MAX_FEED_BYTES + 1)
    assert cx.parse_fred_json(huge) is None


def test_valeur_NON_FINIE_est_ecartee_pas_propagee():
    payload = json.dumps({"observations": [{"date": "2026-07-31", "value": "NaN"},
                                           {"date": "2026-08-01", "value": "Infinity"},
                                           {"date": "2026-08-02", "value": "2.0"}]})
    parsed = cx.parse_fred_json(payload)
    assert [o.value for o in parsed.observations] == [2.0]
    assert parsed.dropped == 2


def test_doublons_de_periode_le_PREMIER_gagne_et_le_reste_est_compte():
    payload = json.dumps({"observations": [{"date": "2026-07-31", "value": "1.0"},
                                           {"date": "2026-07-31", "value": "9.9"}]})
    parsed = cx.parse_fred_json(payload)
    assert [o.value for o in parsed.observations] == [1.0]
    assert parsed.dropped == 1


def test_observations_toujours_rendues_en_ordre_CHRONOLOGIQUE():
    payload = json.dumps({"observations": [{"date": "2026-08-02", "value": "3"},
                                           {"date": "2026-07-31", "value": "1"},
                                           {"date": "2026-08-01", "value": "2"}]})
    parsed = cx.parse_fred_json(payload)
    assert [o.value for o in parsed.observations] == [1.0, 2.0, 3.0]


def test_la_periode_n_est_JAMAIS_convertie_en_jour_qu_on_ne_connait_pas():
    """« 2026-Q2 » reste « 2026-Q2 » : lui donner un jour inventerait une précision que la
    source ne publie pas."""
    csv = "TIME_PERIOD,OBS_VALUE\n2026-Q2,1.5\n"
    parsed = cx.parse_sdmx_csv(csv)
    assert parsed.observations[0].date == "2026-Q2"


def test_observation_IMMUABLE():
    o = cx.Observation(date="2026-07-31", value=1.0)
    with pytest.raises(Exception):
        o.value = 2.0                                   # type: ignore[misc]


def test_module_PURE_aucune_lecture_d_horloge():
    """Les connecteurs construisent et parsent ; ils ne datent rien eux-mêmes."""
    import inspect
    src = inspect.getsource(cx)
    for banned in ("time.time", "perf_counter", "monotonic"):
        assert banned not in src, banned


# =============================================================================================
# Porte d'entrée unique — quel connecteur pour quelle ligne (/polish)
# =============================================================================================


def test_client_for_rend_le_bon_connecteur_sans_que_l_appelant_ait_a_le_savoir():
    from app.providers.client import client_for
    from app.providers.ecb import EcbClient
    from app.providers.eurostat import EurostatClient
    from app.providers.fred import FredClient
    assert isinstance(client_for("vixcls"), FredClient)
    assert isinstance(client_for("hicp_ez"), EcbClient)
    assert isinstance(client_for("unrate_ez"), EurostatClient)


def test_client_for_dit_quand_le_connecteur_reste_a_ECRIRE():
    """Cas qu'aucun autre garde ne couvrait : la ligne est collectable, l'endpoint existe, et
    pourtant on ne sait pas aller la chercher. Le motif doit dire que c'est du CODE à produire,
    pas un relevé de catalogue."""
    from app.providers.client import client_for
    with pytest.raises(cx.SeriesBlocked) as e:
        client_for("bund_nominal")
    assert "pas encore écrit" in str(e.value) and "code à produire" in str(e.value)


def test_client_for_applique_le_portillon_du_registre():
    from app.providers.client import client_for
    for key, attendu in (("oecd_cli", "catalogue"), ("d4_coeff", "calibr"),
                         ("spf_us", "REST"), ("inconnue", "registre")):
        with pytest.raises(cx.SeriesBlocked) as e:
            client_for(key)
        assert attendu.lower() in str(e.value).lower(), key


def test_client_for_transmet_les_options_au_client():
    from app.providers.client import client_for
    assert client_for("hicp_ez", timeout_s=42.0).timeout_s == 42.0
