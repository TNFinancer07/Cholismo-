"""Feature — extracteur de contexte historique (D-085, phase P2).

Construit le `contexte.json` en interrogeant FRED et Finnhub **sur une fenêtre passée**, là où
`app/external/` demande « la valeur maintenant ».

Tous les tests injectent leur `fetcher` : **aucun ne touche le réseau**. C'est la même discipline
que les fournisseurs live, et c'est ce qui rend ces tests reproductibles.

**Le point de vigilance : l'horodatage.** Une clôture VIX du 3 mars n'est pas connue le 3 mars à
00:00 — elle l'est après la clôture. La dater à minuit la rendrait disponible toute la séance
qu'on rejoue, soit un lookahead d'une journée entière, invisible dans le fichier produit.
"""
import json

import pytest

from app.mbo.build_context import (
    VIX_SERIES, build_context, fetch_calendar_window, fetch_vix_window,
)
from app.mbo.session_context import SessionContext

FRED_OK = json.dumps({"observations": [
    {"date": "2025-03-03", "value": "19.5"},
    {"date": "2025-03-04", "value": "22.1"},
    {"date": "2025-03-05", "value": "."},          # jour férié / pas de séance
]})


# ---------------------------------------------------------------------------
# L'horodatage — le point qui décide si la jointure est honnête
# ---------------------------------------------------------------------------

def test_une_cloture_est_datee_de_sa_CLOTURE_pas_de_minuit():
    """Le test central. À minuit, la clôture du jour n'existe pas encore."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    points, _ = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k",
                                 fetcher=lambda url: FRED_OK)
    first = points[0]
    stamped = datetime.fromtimestamp(first["ts"], ZoneInfo("America/New_York"))
    assert stamped.strftime("%Y-%m-%d") == "2025-03-03"
    assert (stamped.hour, stamped.minute) == (16, 0), "16:00 ET, pas 00:00"


def test_la_valeur_du_jour_n_est_pas_visible_AVANT_sa_cloture():
    """Bout en bout : l'extracteur produit un fichier que la jointure lit sans lookahead."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    points, _ = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k",
                                 fetcher=lambda url: FRED_OK)
    ctx = SessionContext.from_dict({"vix": points})
    ny = ZoneInfo("America/New_York")
    ouverture = datetime(2025, 3, 4, 9, 30, tzinfo=ny).timestamp()
    # À l'ouverture du 4, la clôture du 4 n'existe pas : on doit voir celle du 3.
    assert ctx.vix_at(ouverture) == 19.5
    apres_cloture = datetime(2025, 3, 4, 16, 30, tzinfo=ny).timestamp()
    assert ctx.vix_at(apres_cloture) == 22.1


# ---------------------------------------------------------------------------
# VIX — fenêtre, trous, pannes
# ---------------------------------------------------------------------------

def test_la_serie_VIX_est_extraite_avec_ses_valeurs():
    points, warnings = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k",
                                        fetcher=lambda url: FRED_OK)
    assert [p["value"] for p in points] == [19.5, 22.1]
    assert warnings == []


def test_un_jour_SANS_seance_est_ecarte_pas_comble():
    """FRED marque les jours fériés « . ». Combler par la veille fabriquerait une observation
    qui n'a jamais eu lieu."""
    points, _ = fetch_vix_window("2025-03-03", "2025-03-05", api_key="k",
                                 fetcher=lambda url: FRED_OK)
    assert len(points) == 2, "le 5 mars (« . ») n'est pas inventé"


def test_les_observations_HORS_fenetre_sont_ecartees():
    points, _ = fetch_vix_window("2025-03-03", "2025-03-03", api_key="k",
                                 fetcher=lambda url: FRED_OK)
    assert len(points) == 1


def test_une_panne_FRED_est_RAPPORTEE_pas_silencieuse():
    def boom(url):
        raise OSError("réseau coupé")

    points, warnings = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k", fetcher=boom)
    assert points == [] and warnings and "FRED" in warnings[0]


def test_une_serie_VIDE_est_signalee():
    points, warnings = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k",
                                        fetcher=lambda url: json.dumps({"observations": []}))
    assert points == [] and warnings != []


def test_la_serie_interrogee_est_bien_VIXCLS():
    vus = []

    def spy(url):
        vus.append(url)
        return FRED_OK

    fetch_vix_window("2025-03-03", "2025-03-04", api_key="k", fetcher=spy)
    assert vus and VIX_SERIES in vus[0]


# ---------------------------------------------------------------------------
# Calendrier — les bornes, et le vide honnête
# ---------------------------------------------------------------------------

def test_les_BORNES_de_date_sont_envoyees_a_Finnhub():
    """L'endpoint live n'envoie pas de bornes (il veut « maintenant ») ; l'historique en a
    besoin, sinon on récupérerait le calendrier du jour."""
    vus = []

    def spy(url):
        vus.append(url)
        return json.dumps({"economicCalendar": []})

    fetch_calendar_window("2025-03-03", "2025-03-07", api_key="k", fetcher=spy)
    assert "from=2025-03-03" in vus[0] and "to=2025-03-07" in vus[0]


def test_sans_cle_le_calendrier_n_est_PAS_recupere_et_le_dit():
    points, warnings = fetch_calendar_window("2025-03-03", "2025-03-07", api_key="")
    assert points == [] and "fail-closed" in warnings[0]


def test_un_calendrier_VIDE_est_signale_avec_ses_DEUX_causes_possibles():
    """« Aucun événement ce jour-là » et « le plan ne sert pas l'historique » se ressemblent
    dans la réponse, pas dans les conséquences."""
    points, warnings = fetch_calendar_window("2025-03-03", "2025-03-07", api_key="k",
                                             fetcher=lambda url: json.dumps(
                                                 {"economicCalendar": []}))
    assert points == []
    assert "aucun événement" in warnings[0] and "Finnhub" in warnings[0]


def test_un_calendrier_vide_ne_fabrique_JAMAIS_un_SAFE():
    """La conséquence qui compte : sans calendrier, F0 reste fail-closed (D-050)."""
    context = build_context("2025-03-03", "2025-03-04", fred_key="k", finnhub_key="",
                            fred_fetcher=lambda url: FRED_OK)
    ctx = SessionContext.from_dict(context)
    assert ctx.news_state_at(1_740_000_000.0) is None, "None = inconnu, jamais SAFE"


def test_une_panne_Finnhub_est_rapportee():
    def boom(url):
        raise OSError("timeout")

    points, warnings = fetch_calendar_window("2025-03-03", "2025-03-07", api_key="k",
                                             fetcher=boom)
    assert points == [] and "Finnhub" in warnings[0]


# ---------------------------------------------------------------------------
# Le fichier produit
# ---------------------------------------------------------------------------

def test_le_contexte_produit_est_LISIBLE_par_la_jointure():
    """Le contrat entre les deux modules : ce que l'extracteur écrit, la jointure le lit."""
    context = build_context("2025-03-03", "2025-03-04", fred_key="k", finnhub_key="k",
                            fred_fetcher=lambda url: FRED_OK,
                            finnhub_fetcher=lambda url: json.dumps({"economicCalendar": []}))
    json.loads(json.dumps(context))
    ctx = SessionContext.from_dict(context)
    assert ctx.diagnostics()["vix_points"] == 2


def test_la_PROVENANCE_accompagne_le_fichier():
    """Un fichier de contexte silencieusement incomplet produirait une passe de calibration
    d'allure normale sur un contexte troué. Le rapport fait partie du livrable."""
    context = build_context("2025-03-03", "2025-03-04", fred_key="k", finnhub_key="",
                            fred_fetcher=lambda url: FRED_OK)
    prov = context["provenance"]
    assert prov["vix_series"] == VIX_SERIES
    assert "16:00 ET" in prov["vix_timestamped_at"]
    assert prov["warnings"], "l'absence de clé Finnhub doit apparaître"


def test_la_fenetre_demandee_est_conservee_dans_le_fichier():
    context = build_context("2025-03-03", "2025-03-07", fred_key="k",
                            fred_fetcher=lambda url: FRED_OK)
    assert context["window"] == {"from": "2025-03-03", "to": "2025-03-07"}


def test_le_CLI_ecrit_le_fichier_et_remonte_en_amont(tmp_path, monkeypatch):
    """`--pad-days` : sans clôture ANTÉRIEURE au début de séance, `vix_at()` n'aurait rien à
    rendre sur les premières minutes — la jointure ne regarde jamais devant."""
    from app.mbo import build_context as module

    vus = []
    monkeypatch.setattr(module, "_http", lambda url, timeout_s=10.0: (vus.append(url), FRED_OK)[1])
    out = tmp_path / "ctx.json"
    assert module.main(["--from", "2025-03-10", "--to", "2025-03-10", "-o", str(out),
                        "--fred-key", "k"]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["window"]["from"] == "2025-03-05", "5 jours de marge en amont"
    assert out.exists()


def test_une_date_ILLISIBLE_ne_produit_pas_de_point():
    points, _ = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k",
                                 fetcher=lambda url: json.dumps(
                                     {"observations": [{"date": "pas-une-date", "value": "19"}]}))
    assert points == []


@pytest.mark.parametrize("payload", ["", "pas du json", "{}", '{"observations": null}'])
def test_une_reponse_FRED_ABERRANTE_ne_leve_pas(payload):
    points, warnings = fetch_vix_window("2025-03-03", "2025-03-04", api_key="k",
                                        fetcher=lambda url: payload)
    assert points == [] and warnings != []


# ---------------------------------------------------------------------------
# Régression — le calendrier NON vide, cas que les tests initiaux ne couvraient pas
# ---------------------------------------------------------------------------

CAL_OK = json.dumps({"economicCalendar": [
    {"time": "2023-11-14 08:30:00", "event": "CPI YoY", "country": "US", "impact": "high"},
    {"time": "2023-11-14 10:00:00", "event": "Discours mineur", "country": "US", "impact": "low"},
]})


def test_un_calendrier_NON_VIDE_est_reellement_extrait():
    """Régression (D-085), trouvée à l'essai réel. `CalendarEvent` est un DICT, pas un objet :
    `getattr(ev, "ts")` rendait `None` pour chaque entrée et jetait TOUS les événements valides.
    Les tests initiaux ne couvraient que le calendrier vide — ils passaient tous."""
    points, warnings = fetch_calendar_window("2023-11-13", "2023-11-14", api_key="k",
                                             fetcher=lambda url: CAL_OK)
    assert len(points) == 2, "un flux Finnhub valide doit produire des événements"
    assert warnings == []
    assert points[0]["name"] == "CPI YoY"


def test_la_severite_TIER_1_se_lit_sur_impact():
    """`tier1` n'existe pas sur `CalendarEvent` : la sévérité se lit sur `impact`, que le
    parseur a déjà promu pour les publications sensibles à impact absent."""
    points, _ = fetch_calendar_window("2023-11-13", "2023-11-14", api_key="k",
                                      fetcher=lambda url: CAL_OK)
    par_nom = {p["name"]: p["tier1"] for p in points}
    assert par_nom["CPI YoY"] is True
    assert par_nom["Discours mineur"] is False


def test_un_flux_ILLISIBLE_est_distingue_d_une_fenetre_VIDE():
    """Le parseur distingue `None` (illisible/empoisonné) de `[]` (lisible et vide). Les
    confondre écrirait un calendrier vide sur une réponse corrompue."""
    points, warnings = fetch_calendar_window("2023-11-13", "2023-11-14", api_key="k",
                                             fetcher=lambda url: "pas du json")
    assert points == []
    assert "ILLISIBLE" in warnings[0], "un flux corrompu ne se lit pas comme une semaine calme"


def test_le_blackout_fonctionne_bout_en_bout_depuis_le_flux_Finnhub():
    """La chaîne complète : Finnhub → extracteur → jointure → porte F0."""
    context = build_context("2023-11-13", "2023-11-14", fred_key="k", finnhub_key="k",
                            fred_fetcher=lambda url: FRED_OK,
                            finnhub_fetcher=lambda url: CAL_OK)
    ctx = SessionContext.from_dict(context)
    cpi_ts = next(c["ts"] for c in context["calendar"] if c["name"] == "CPI YoY")
    assert ctx.news_state_at(cpi_ts) == "HARD_LOCK"
    assert ctx.news_state_at(cpi_ts + 3600) == "SAFE"
