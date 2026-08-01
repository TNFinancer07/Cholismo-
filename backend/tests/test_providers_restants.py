"""Les trois derniers clients — Socrata CFTC, SDMX international, Yahoo (D-057).

Ils complètent les sept connecteurs. Ce que ces tests protègent : aucune clé API, aucun champ
ni aucune échéance devinés à la place de l'opérateur, et le bon parser pour le bon format.
"""
from __future__ import annotations

import json

import pytest

from app.providers import cftc, connectors as cx, sdmx, yahoo

SOCRATA = json.dumps([{"report_date_as_yyyy_mm_dd": "2026-07-28T00:00:00.000",
                       "noncomm_positions_long_all": "1200"},
                      {"report_date_as_yyyy_mm_dd": "2026-07-21T00:00:00.000",
                       "noncomm_positions_long_all": "900"}])
BIS_CSV = "KEY,TIME_PERIOD,OBS_VALUE\nX,2026-06,101.2\nX,2026-07,102.0\n"
DBN = json.dumps({"series": {"docs": [{"period": ["2026-06", "2026-07"], "value": [1.0, 2.0]}]}})
YCSV = "Date,Open,Close,Adj Close\n2026-07-30,1,100.5,100.5\n2026-07-31,1,101.5,101.5\n"


def _c(cls, payload):
    seen = []
    return cls(fetcher=lambda u: (seen.append(u), payload)[1]), seen


# --- Socrata CFTC ---------------------------------------------------------------------------

def test_CFTC_le_champ_de_valeur_est_OBLIGATOIRE_jamais_devine():
    """La ressource porte des dizaines de colonnes ; en deviner une produirait une série
    fausse ET plausible — le pire cas."""
    client, _ = _c(cftc.CftcClient, SOCRATA)
    with pytest.raises(TypeError):
        client.fetch("gpe5-46if")                          # pas de défaut possible


def test_CFTC_lit_le_champ_demande():
    client, seen = _c(cftc.CftcClient, SOCRATA)
    r = client.fetch("gpe5-46if", value_field="noncomm_positions_long_all")
    assert [(o.date, o.value) for o in r.series.observations] == [("2026-07-21", 900.0),
                                                                  ("2026-07-28", 1200.0)]
    assert "$limit=" in seen[0] and "api_key" not in seen[0]


def test_CFTC_la_borne_de_lignes_est_TOUJOURS_posee():
    """Sans `$limit`, Socrata plafonne à 1 000 lignes EN SILENCE — une troncature invisible."""
    assert "$limit=" in cftc.data_url("gpe5-46if")


def test_CFTC_filtre_de_date_et_formes_refusees():
    assert "report_date_as_yyyy_mm_dd>'2020-01-01'" in cftc.data_url("gpe5-46if",
                                                                     since="2020-01-01")
    for mauvais in ("GPE5-46IF", "gpe546if", "gpe5-46if?x", "", None):
        with pytest.raises(cx.SeriesBlocked):
            cftc.data_url(mauvais)
    with pytest.raises(cx.SeriesBlocked):
        cftc.data_url("gpe5-46if", since="hier")


def test_CFTC_par_la_cle_metier_du_registre():
    client, seen = _c(cftc.CftcClient, SOCRATA)
    r = client.fetch_catalog("cot_fx", value_field="noncomm_positions_long_all")
    assert r.error is None and "/gpe5-46if.json" in seen[0]


# --- SDMX international ---------------------------------------------------------------------

def test_SDMX_BIS_lit_du_CSV_et_DBNOMICS_du_JSON_sans_les_confondre():
    """Deux formats, deux parsers — choisis par la MÉTHODE, pas par un attribut d'instance
    qu'un appel précédent aurait laissé traîner."""
    client, seen = _c(sdmx.SdmxClient, BIS_CSV)
    assert [o.value for o in client.fetch("WS_EER_M", "M.R.B.XM").series.observations] == [101.2,
                                                                                            102.0]
    client2, _ = _c(sdmx.SdmxClient, DBN)
    assert [o.value for o in client2.fetch_dbnomics("OECD", "MEI", "X").series.observations] == [
        1.0, 2.0]
    assert seen[0] == "https://stats.bis.org/api/v1/data/WS_EER_M/M.R.B.XM/all"


def test_SDMX_ordre_des_appels_SANS_effet_de_bord():
    """Le même client sert les deux formats à la suite : si le parser était un état, le second
    appel casserait le premier."""
    client, _ = _c(sdmx.SdmxClient, BIS_CSV)
    client.fetch("WS_EER_M", "M.R.B.XM")
    client._fetcher = lambda u: DBN
    assert client.fetch_dbnomics("OECD", "MEI", "X").series is not None
    client._fetcher = lambda u: BIS_CSV
    assert client.fetch("WS_EER_M", "M.R.B.XM").series is not None


def test_SDMX_par_la_cle_metier_du_registre():
    client, seen = _c(sdmx.SdmxClient, BIS_CSV)
    assert client.fetch_catalog("reer").error is None
    assert "/WS_EER_M/M.R.B.XM/all" in seen[0]


def test_SDMX_les_lignes_C2_restent_bloquees():
    client, _ = _c(sdmx.SdmxClient, BIS_CSV)
    for key in ("nfa", "tot", "oecd_cli"):
        with pytest.raises(cx.SeriesBlocked):
            client.fetch_catalog(key)


# --- Yahoo ----------------------------------------------------------------------------------

def test_YAHOO_lit_la_cloture():
    client, seen = _c(yahoo.YahooClient, YCSV)
    r = client.fetch("^GDAXI")
    assert [o.value for o in r.series.observations] == [100.5, 101.5]
    assert "%5EGDAXI" in seen[0] and "api_key" not in seen[0]


def test_YAHOO_ZQ_est_une_RACINE_pas_un_ticker():
    client, _ = _c(yahoo.YahooClient, YCSV)
    with pytest.raises(cx.SeriesBlocked) as e:
        client.fetch("ZQ")
    assert "racine" in str(e.value)
    assert "ZQZ26" in yahoo.data_url("ZQ", contract="ZQZ26")


def test_YAHOO_la_reserve_CGU_est_ECRITE_dans_le_module():
    """« Prévoir que ça casse un jour et que le remplacement sera manuel » — écrit ici plutôt
    que découvert un matin."""
    assert "pas une api officielle" in yahoo.__doc__.lower().replace("**", "")
    assert "^MOVE" in yahoo.TICKERS and "supprimable" in yahoo.TICKERS["^MOVE"].lower()


def test_YAHOO_par_la_cle_metier_du_registre():
    client, seen = _c(yahoo.YahooClient, YCSV)
    assert client.fetch_catalog("dax").error is None and "%5EGDAXI" in seen[0]


# --- les sept connecteurs sont désormais complets --------------------------------------------

def test_LES_SEPT_connecteurs_ont_un_client():
    from app.providers import catalog as cat
    from app.providers.client import has_client
    for provider in (cat.Provider.FRED, cat.Provider.ECB_SDMX, cat.Provider.EUROSTAT,
                     cat.Provider.BUNDESBANK, cat.Provider.CFTC_SOCRATA,
                     cat.Provider.SDMX_INTL, cat.Provider.YFINANCE):
        assert has_client(provider), provider
