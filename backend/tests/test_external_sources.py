"""Sources externes Niveau 3 — calendrier F5 et VIX F3 (D-062).

Ces tests protègent d'abord ce que le paquet **refuse de faire** : décider à la place des
couches déterministes, servir un souvenir comme une donnée, ou laisser une valeur de repli
passer pour une mesure.

Aucun test n'ouvre de socket : chaque fournisseur reçoit son `fetcher` ou son `client` injecté.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timezone
from typing import Any, Optional

import pytest

from app import config
from app.external import (ChainedCalendar, ChainedVix, ExternalDataModule, FinnhubCalendar,
                          FredVix, LocalCalendarFile, StaticVix, TermStructureVix,
                          get_vix_regime, is_high_impact_news_near)
from app.external.contracts import CalendarEvent, plausible_vix
from app.external.economic_calendar import is_tier1, parse_finnhub_json
from app.providers.connectors import redact

T0 = 1_785_600_000.0          # epoch fixe : aucune horloge lue, les tests sont reproductibles


class FauxState:
    """Redis remplacé par un dictionnaire : ces tests n'ouvrent aucune connexion."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, Any, str, Optional[float], list[str]]] = []

    async def write_raw(self, field, value, source, ts=None, flags=None):   # type: ignore[no-untyped-def]
        self.writes.append((field, value, source, ts, list(flags or [])))

    def fields(self) -> set[str]:
        return {w[0] for w in self.writes}

    def last(self, field: str) -> tuple[str, Any, str, Optional[float], list[str]]:
        return next(w for w in reversed(self.writes) if w[0] == field)


def _finnhub(*entries: dict[str, Any]) -> str:
    return json.dumps({"economicCalendar": list(entries)})


def _evt(ts: float, name: str = "NFP", impact: str = "HIGH") -> CalendarEvent:
    return CalendarEvent(ts=ts, name=name, country="US", currency="USD", impact=impact,  # type: ignore[typeddict-item]
                         consensus=None, previous=None, actual=None)


# =============================================================================================
# 1. Le piège n° 1 d'un calendrier tiers : le fuseau horaire, pas le format
# =============================================================================================


def test_une_date_NAIVE_recoit_le_fuseau_ASSUME_et_il_est_explicite():
    """Une heure d'écart déplace toute la fenêtre de blackout : le terminal autoriserait à
    trader pile pendant le NFP en affichant NORMAL — parfaitement crédible, complètement faux."""
    flux = _finnhub({"event": "Nonfarm Payrolls", "impact": "high", "country": "US",
                     "time": "2026-08-07 12:30:00"})
    utc = parse_finnhub_json(flux, assume_tz=timezone.utc)
    assert utc is not None and len(utc) == 1
    from datetime import datetime
    attendu = datetime(2026, 8, 7, 12, 30, tzinfo=timezone.utc).timestamp()
    assert utc[0]["ts"] == pytest.approx(attendu)


def test_un_fuseau_EXPLICITE_dans_la_donnee_prime_sur_l_hypothese():
    flux = _finnhub({"event": "CPI", "impact": "high", "time": "2026-08-07T12:30:00+02:00"})
    events = parse_finnhub_json(flux, assume_tz=timezone.utc)
    assert events is not None
    from datetime import datetime
    assert events[0]["ts"] == pytest.approx(
        datetime(2026, 8, 7, 10, 30, tzinfo=timezone.utc).timestamp())


# =============================================================================================
# 2. Le parser : corrompu ligne à ligne, obèse en entier
# =============================================================================================


def test_une_entree_corrompue_est_ecartee_SEULE():
    """Un calendrier ne meurt pas d'une entrée pourrie."""
    flux = _finnhub(
        {"event": "NFP", "impact": "high", "time": "2026-08-07 12:30:00"},
        {"impact": "high", "time": "2026-08-07 13:00:00"},          # sans nom
        {"event": "SansHeure", "impact": "high"},                    # sans heure
        {"event": "HeureIllisible", "impact": "high", "time": "demain"},
        "pas un objet",
        {"event": "CPI", "impact": "high", "time": "2026-08-08 12:30:00"})
    events = parse_finnhub_json(flux)
    assert events is not None
    assert [e["name"] for e in events] == ["NFP", "CPI"]


def test_un_flux_OBESE_est_rejete_ENTIER_jamais_tronque():
    """Tronquer serait pire : si la publication imminente tombe au-delà de la coupe, le verrou
    F5 s'ouvrirait à tort (leçon D-050)."""
    from app.external.contracts import MAX_EVENTS
    gros = _finnhub(*[{"event": f"E{i}", "impact": "high", "time": "2026-08-07 12:30:00"}
                      for i in range(MAX_EVENTS + 1)])
    assert parse_finnhub_json(gros) is None


@pytest.mark.parametrize("flux", ["", "pas du json", "{", json.dumps({"autre": 1})])
def test_un_flux_ILLISIBLE_rend_None_pour_que_l_appelant_garde_son_cache(flux):
    assert parse_finnhub_json(flux) is None


def test_un_flux_LISIBLE_et_VIDE_est_un_etat_CONNU_pas_une_panne():
    """Semaine calme ≠ feed mort. Les confondre ferait clignoter une panne inexistante."""
    assert parse_finnhub_json(_finnhub()) == []


# =============================================================================================
# 3. La promotion Tier-1 — elle va dans le sens du VERROU, jamais dans l'autre
# =============================================================================================


@pytest.mark.parametrize("nom", [
    "Nonfarm Payrolls", "Core CPI m/m", "FOMC Statement", "PPI y/y",
    "Initial Jobless Claims", "US Unemployment Rate", "Fed Interest Rate Decision"])
def test_les_publications_TIER1_demandees_sont_reconnues(nom):
    assert is_tier1(nom), nom


def test_un_impact_ABSENT_sur_un_TIER1_promeut_vers_le_verrou():
    """`build_macro_calendar` écarte un événement sans impact lisible. Écarter un NFP pour cette
    raison OUVRIRAIT le verrou au pire moment — un fail-OPEN déguisé en fail-closed."""
    flux = _finnhub({"event": "Nonfarm Payrolls", "time": "2026-08-07 12:30:00"},
                    {"event": "Réunion de comité local", "time": "2026-08-07 13:00:00"})
    events = parse_finnhub_json(flux)
    assert events is not None
    assert [(e["name"], e["impact"]) for e in events] == [("Nonfarm Payrolls", "HIGH")]


def test_un_impact_EXPLICITE_n_est_JAMAIS_contredit():
    """Le fournisseur qui dit « low » est cru : le corriger serait inventer."""
    flux = _finnhub({"event": "Nonfarm Payrolls", "impact": "low",
                     "time": "2026-08-07 12:30:00"})
    events = parse_finnhub_json(flux)
    assert events is not None and events[0]["impact"] == "LOW"


def test_la_promotion_peut_etre_COUPEE_et_alors_l_evenement_disparait():
    flux = _finnhub({"event": "Nonfarm Payrolls", "time": "2026-08-07 12:30:00"})
    assert parse_finnhub_json(flux, promote_tier1=False) == []


# =============================================================================================
# 4. Indisponible ≠ en échec (leçon D-050)
# =============================================================================================


def test_sans_cle_Finnhub_le_fournisseur_est_INDISPONIBLE_il_n_essaie_pas():
    """Une clé absente est une CONFIGURATION manquante, pas une panne. Les confondre enverrait
    chercher une panne réseau qui n'existe pas."""
    c = FinnhubCalendar(None)
    motif = c.unavailable_reason()
    assert motif is not None and "FINNHUB_API_KEY" in motif


def test_un_refus_HTTP_dit_le_PLAN_pas_injoignable():
    """Le calendrier éco Finnhub est payant sur la plupart des plans : un 403 veut dire « plan
    insuffisant », pas « clé fausse » ni « service injoignable » (leçon D-057)."""
    import urllib.error

    def refus(url: str) -> str:
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)   # type: ignore[arg-type]

    res = FinnhubCalendar("CLE", fetcher=refus).fetch(now=T0)
    assert not res.ok and res.error is not None
    assert "403" in res.error and "payant" in res.error
    assert "injoignable" not in res.error


def test_une_panne_RESEAU_se_distingue_d_un_refus():
    import urllib.error

    def mort(url: str) -> str:
        raise urllib.error.URLError("dns")

    res = FinnhubCalendar("CLE", fetcher=mort).fetch(now=T0)
    assert res.error is not None and "injoignable" in res.error


def test_le_JETON_n_apparait_JAMAIS_dans_un_motif():
    """`redact` ne couvrait que `api_key=` ; Finnhub utilise `token=`. Un rédacteur qui rate un
    nom de paramètre est une fuite en attente."""
    import urllib.error

    def mort(url: str) -> str:
        raise urllib.error.URLError("dns")

    res = FinnhubCalendar("SECRET-ABC123", fetcher=mort).fetch(now=T0)
    assert res.error is not None and "SECRET-ABC123" not in res.error
    assert "SECRET" not in redact("https://x/y?token=SECRET-ABC123&z=1")
    assert "SECRET" not in redact("https://x/y?api_key=SECRET&z=1")


def test_la_source_Finnhub_est_marquee_NON_VERIFIEE():
    """Doctrine C2 (D-057) : le format vient de la documentation, jamais d'une réponse réelle —
    l'egress était bloqué. Le présenter comme acquis serait le mensonge habituel."""
    res = FinnhubCalendar("CLE", fetcher=lambda u: _finnhub()).fetch(now=T0)
    assert res.ok and res.verified is False
    assert "SOURCE_NON_VERIFIEE" in res.flags


# =============================================================================================
# 5. Le repli local — hors ligne, mais jamais confondu avec du réel
# =============================================================================================


def test_le_repli_local_porte_TOUJOURS_son_drapeau(tmp_path):
    """Une donnée de secours indiscernable de la vraie est le seul état vraiment dangereux d'un
    terminal qui journalise des décisions (leçon REPLAY, D-058)."""
    f = tmp_path / "cal.json"
    f.write_text(json.dumps([{"ts": T0 + 600, "name": "NFP", "impact": "HIGH",
                              "country": "US"}]), encoding="utf-8")
    res = LocalCalendarFile(str(f)).fetch(now=T0)
    assert res.ok and res.fallback is True
    assert "EXTERNAL_FALLBACK" in res.flags
    assert res.events is not None and res.events[0]["currency"] == "USD"


def test_aucun_calendrier_n_est_embarque_EN_DUR_dans_le_code(tmp_path):
    """Des dates de NFP inventées, servies sans réseau et indiscernables d'un vrai calendrier,
    seraient le chiffre-qui-a-l'air-d'une-mesure que la §3 interdit."""
    assert LocalCalendarFile(None).unavailable_reason() is not None
    manquant = LocalCalendarFile(str(tmp_path / "absent.json"))
    motif = manquant.unavailable_reason()
    assert motif is not None and "introuvable" in motif
    assert not manquant.fetch(now=T0).ok            # jamais « vide », qui serait un état connu


def test_un_fichier_local_ILLISIBLE_le_dit_utilement(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text("{ pas du json", encoding="utf-8")
    res = LocalCalendarFile(str(f)).fetch(now=T0)
    assert not res.ok and res.error is not None and "attendu une LISTE" in res.error


# =============================================================================================
# 6. La chaîne de repli — elle bascule, et elle le DIT
# =============================================================================================


def test_la_chaine_bascule_sur_le_repli_et_NOMME_ce_qui_a_servi(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps([{"ts": T0 + 600, "name": "CPI", "impact": "HIGH"}]),
                 encoding="utf-8")
    chaine = ChainedCalendar([FinnhubCalendar(None), LocalCalendarFile(str(f))])
    res = chaine.fetch(now=T0)
    assert res.ok and res.fallback is True
    assert any("finnhub" in a and "indisponible" in a for a in chaine.attempts)
    assert len(chaine.attempts) == 2                # un repli SILENCIEUX ferait croire au succès


def test_une_chaine_TOUTE_indisponible_rend_les_motifs_de_chacun():
    chaine = ChainedCalendar([FinnhubCalendar(None), LocalCalendarFile(None)])
    res = chaine.fetch(now=T0)
    assert not res.ok and res.error is not None
    assert "FINNHUB_API_KEY" in res.error and "EXTERNAL_CALENDAR_FILE" in res.error


def test_la_source_PRINCIPALE_gagne_quand_elle_repond(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps([{"ts": T0, "name": "LOCAL", "impact": "HIGH"}]), encoding="utf-8")
    flux = _finnhub({"event": "DISTANT", "impact": "high", "time": "2026-08-07 12:30:00"})
    chaine = ChainedCalendar([FinnhubCalendar("CLE", fetcher=lambda u: flux),
                              LocalCalendarFile(str(f))])
    res = chaine.fetch(now=T0)
    assert res.ok and res.fallback is False
    assert res.events is not None and res.events[0]["name"] == "DISTANT"


# =============================================================================================
# 7. La fenêtre F5 — DÉLÉGUÉE, et détectée exactement
# =============================================================================================


def test_dans_la_fenetre_le_verdict_est_VRAI_et_NOMME_l_evenement():
    """Un « BLOQUÉ » qui ne dit pas POURQUOI est un cul-de-sac pour l'opérateur."""
    v = is_high_impact_news_near([_evt(T0 + 300, "Nonfarm Payrolls")], T0, window_minutes=15)
    assert v["near"] is True and v["regime"] == "EXECUTION_PAUSED"
    assert v["event"]["name"] == "Nonfarm Payrolls"
    assert v["seconds_until"] == pytest.approx(300.0)


def test_hors_de_la_fenetre_le_verdict_est_FAUX():
    v = is_high_impact_news_near([_evt(T0 + 3600)], T0, window_minutes=15)
    assert v["near"] is False


def test_la_fenetre_est_SYMETRIQUE_le_chaos_ne_s_arrete_pas_a_l_heure_pile():
    avant = is_high_impact_news_near([_evt(T0 + 300)], T0, window_minutes=15)
    apres = is_high_impact_news_near([_evt(T0 - 300)], T0, window_minutes=15)
    assert avant["near"] is True and apres["near"] is True


def test_la_BORNE_EXACTE_est_INCLUSE_le_doute_penche_vers_le_verrou():
    pile = is_high_impact_news_near([_evt(T0 + 900)], T0, window_minutes=15)
    juste_apres = is_high_impact_news_near([_evt(T0 + 900.1)], T0, window_minutes=15)
    assert pile["near"] is True
    assert juste_apres["near"] is False


@pytest.mark.parametrize("impact", ["MED", "LOW"])
def test_un_evenement_NON_fort_impact_n_enclenche_JAMAIS_le_verrou(impact):
    v = is_high_impact_news_near([_evt(T0 + 60, "ISM", impact)], T0, window_minutes=15)
    assert v["near"] is False


def test_le_verdict_F5_DELEGUE_au_garde_deterministe_existant():
    """Recoder la fenêtre ici donnerait deux réponses à « sommes-nous en blackout ? », et le
    jour où elles divergeraient personne ne saurait laquelle a raison."""
    from app.macro_risk import compute_macro_risk
    events = [_evt(T0 + 120), _evt(T0 + 4000, "CPI")]
    direct = compute_macro_risk(list(events), T0, 15 * 60.0, 15 * 60.0)
    via = is_high_impact_news_near(events, T0, window_minutes=15)
    assert via["near"] == direct["in_window"]
    assert via["regime"] == direct["regime"] and via["event"] == direct["event"]


# =============================================================================================
# 8. VIX — les bornes de plausibilité, et l'absence de conversion d'unité
# =============================================================================================


@pytest.mark.parametrize("brut", [0.14, 0.0, -3.0, 500.0, float("nan"), float("inf"),
                                  True, "18", None])
def test_une_valeur_VIX_implausible_est_REFUSEE_jamais_convertie(brut):
    """Un VIX à 0,14 (une fraction lue pour un pourcentage) passerait tous les seuils en VERT.
    Diviser par 100 « au cas où » fabriquerait une lecture que personne n'a publiée."""
    assert plausible_vix(brut) is None


@pytest.mark.parametrize("brut", [5.0, 18.5, 32.0, 200.0])
def test_une_valeur_VIX_plausible_passe(brut):
    assert plausible_vix(brut) == pytest.approx(brut)


def test_FredVix_delegue_au_client_existant_et_prend_la_DERNIERE_observation():
    """Réécrire ici un appel HTTP FRED donnerait deux façons d'interroger le même fournisseur,
    qui divergeraient à la première correction."""
    charge = json.dumps({"observations": [
        {"date": "2026-07-30", "value": "16.20"},
        {"date": "2026-07-31", "value": "18.42"}]})
    res = FredVix(api_key="CLE", fetcher=lambda url: charge).fetch(now=T0)
    assert res.ok and res.value == pytest.approx(18.42)
    assert res.as_of == "2026-07-31" and res.verified is True


def test_FredVix_dit_que_sa_valeur_est_une_CLOTURE():
    """Lue en séance, elle décrit hier. Le taire la ferait lire comme un niveau de séance."""
    charge = json.dumps({"observations": [{"date": "2026-07-31", "value": "18.42"}]})
    res = FredVix(api_key="CLE", fetcher=lambda url: charge).fetch(now=T0)
    assert res.as_of == "2026-07-31"
    assert "clôture" in res.resume


def test_FredVix_sans_cle_est_INDISPONIBLE():
    v = FredVix(api_key="")
    motif = v.unavailable_reason()
    assert motif is not None and "FRED_API_KEY" in motif


def test_une_serie_FRED_SANS_valeur_utilisable_oriente_vers_le_JOUR_FERIE():
    """Limite CONNUE et héritée : `providers._finish` pose « rien de lisible = illisible, pas
    vide » (choix délibéré D-057). Un jour de fermeture, VIXCLS ne publie que des « . » et le
    motif remonte « illisible ». On n'invente pas la distinction qu'on n'a pas — on ajoute
    l'indice qui évite de chercher une panne là où il y a un jour férié."""
    for charge in (json.dumps({"observations": []}),
                   json.dumps({"observations": [{"date": "2026-07-04", "value": "."}]})):
        res = FredVix(api_key="CLE", fetcher=lambda url: charge).fetch(now=T0)
        assert not res.ok and res.error is not None
        assert "fermeture" in res.error


@pytest.mark.parametrize("brut,attendu", [
    ({"VIX": 18.4}, 18.4),
    ({"points": [{"tenor": "VIX9D", "value": 15.0}, {"tenor": "VIX", "value": 19.1}]}, 19.1),
    ([{"tenor": "VIX", "value": 21.0}], 21.0),
])
def test_le_repli_STRUCTURE_DE_VOL_lit_le_tenor_30_jours(brut, attendu):
    """Aucune socket ouverte pour un chiffre qu'on a déjà sous la main — et aucun panneau ne
    montre deux VIX différents au même instant."""
    res = TermStructureVix(lambda: brut).fetch(now=T0)
    assert res.ok and res.value == pytest.approx(attendu) and res.fallback is True


def test_un_tenor_ABSENT_ne_donne_lieu_a_AUCUNE_interpolation():
    res = TermStructureVix(lambda: {"points": [{"tenor": "VIX9D", "value": 15.0}]}).fetch(now=T0)
    assert not res.ok and res.error is not None and "absent" in res.error


def test_un_lecteur_de_structure_QUI_LEVE_n_emporte_pas_la_chaine():
    def casse() -> dict[str, float]:
        raise RuntimeError("schéma pas prêt")

    res = TermStructureVix(casse).fetch(now=T0)
    assert not res.ok and res.error is not None and "RuntimeError" in res.error


def test_le_VIX_SIMULE_porte_toujours_son_drapeau():
    res = StaticVix(17.0).fetch(now=T0)
    assert res.ok and res.fallback is True and "EXTERNAL_FALLBACK" in res.flags


def test_un_VIX_simule_ABSURDE_est_refuse_a_la_configuration():
    motif = StaticVix(0.17).unavailable_reason()
    assert motif is not None and "plausibilité" in motif


def test_la_chaine_VIX_bascule_et_nomme(tmp_path):
    chaine = ChainedVix([FredVix(api_key=""), StaticVix(17.0)])
    res = chaine.fetch(now=T0)
    assert res.ok and res.fallback is True
    assert any("FRED" in a and "indisponible" in a for a in chaine.attempts)


# =============================================================================================
# 9. Le régime F3 — délégué, et les DEUX seuils gardés séparés
# =============================================================================================


def test_get_vix_regime_DELEGUE_l_hysteresis_au_moteur_existant():
    from app.strategies.youssef import update_regime
    for vix in (12.0, 19.0, 27.0, 38.0, 21.0):
        for precedent in ("GREEN", "YELLOW", "ORANGE", "RED"):
            assert get_vix_regime(vix, previous_tier=precedent).tier == \
                update_regime(precedent, vix, None)


def test_l_HYSTERESIS_a_bien_des_zones_mortes():
    """Entrée ≠ sortie : un classificateur « sans mémoire » écrit ici donnerait un palier
    différent du reste du terminal aux frontières."""
    assert get_vix_regime(16.0, previous_tier="GREEN").tier == "GREEN"
    assert get_vix_regime(16.0, previous_tier="YELLOW").tier == "YELLOW"


def test_un_VIX_a_32_est_un_VETO_mais_seulement_ORANGE():
    """Le constat gênant, posé plutôt qu'enfoui : `VIX_CRIT = 30` (AUTORITÉ) et l'hystérésis D4
    (ORANGE 26 → RED 37) ne coïncident pas. Les fusionner en un mot perdrait justement
    l'information qu'ils ne s'accordent pas."""
    r = get_vix_regime(32.0, previous_tier="YELLOW")
    assert r.veto is True                                  # > VIX_CRIT
    assert r.tier == "ORANGE"                              # pas encore RED au sens D4
    assert r.tier != "RED"


def test_le_veto_suit_EXACTEMENT_le_seuil_AUTORITE():
    assert get_vix_regime(config.VIX_CRIT, previous_tier="GREEN").veto is False   # strict
    assert get_vix_regime(config.VIX_CRIT + 0.01, previous_tier="GREEN").veto is True


def test_un_VIX_ABSENT_ne_bouge_pas_le_palier_et_ne_prononce_aucun_veto():
    r = get_vix_regime(None, previous_tier="ORANGE")
    assert r.tier == "ORANGE" and r.veto is False and r.vix is None
    assert "indisponible" in r.resume


def test_aucun_TROISIEME_jeu_de_seuils_n_est_defini_dans_le_paquet():
    """Falsification directe de la promesse du module : les seuils vivent dans `config` et
    `strategies.youssef`, jamais ici."""
    import ast
    import inspect

    from app.external import vix as mod
    # Par l'AST, pas par grep : ma première version fouillait la DOCSTRING, où les seuils sont
    # documentés à dessein — elle échouait sur la prose en laissant passer le code.
    literaux = []
    for noeud in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(noeud, ast.Compare):
            for cote in [noeud.left, *noeud.comparators]:
                if isinstance(cote, ast.Constant) and isinstance(cote.value, (int, float)) \
                        and not isinstance(cote.value, bool):
                    literaux.append(cote.value)
    assert literaux == [], f"seuil numérique EN DUR dans le module : {literaux}"


# =============================================================================================
# 10. ExternalDataModule — cache, aveuglement, publication
# =============================================================================================


class Horloge:
    """Horloge INJECTÉE : on avance le temps sans dormir."""

    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _module(horloge: Horloge, *, cal_flux: Optional[str] = None,
            vix_val: Optional[float] = 17.0, **kw: Any) -> ExternalDataModule:
    calendrier = FinnhubCalendar("CLE", fetcher=lambda u: cal_flux or _finnhub())
    return ExternalDataModule(calendar=calendrier, vix=StaticVix(vix_val),
                              clock=horloge, **kw)


def test_le_cache_evite_de_refetcher_a_chaque_lecture():
    """Les accesseurs sont PURS : zéro I/O sur le chemin d'évaluation (§7)."""
    appels = {"n": 0}

    def compte(url: str) -> str:
        appels["n"] += 1
        return _finnhub({"event": "NFP", "impact": "high", "time": "2026-08-07 12:30:00"})

    h = Horloge()
    m = ExternalDataModule(calendar=FinnhubCalendar("CLE", fetcher=compte),
                           vix=StaticVix(17.0), clock=h)
    asyncio.run(m.refresh())
    for _ in range(20):
        m.calendar_events(h.t)
        m.news_near(h.t)
        m.vix_regime(h.t)
    assert appels["n"] == 1


def test_un_fetch_RATE_conserve_l_ancien_cache():
    h = Horloge()
    bon = _finnhub({"event": "NFP", "impact": "high", "time": "2026-08-07 12:30:00"})
    etat = {"flux": bon}

    def bascule(url: str) -> str:
        if etat["flux"] is None:
            raise OSError("réseau mort")
        return etat["flux"]

    m = ExternalDataModule(calendar=FinnhubCalendar("CLE", fetcher=bascule),
                           vix=StaticVix(17.0), clock=h)
    asyncio.run(m.refresh())
    etat["flux"] = None                                   # le feed meurt
    h.t += 60
    asyncio.run(m.refresh())
    events = m.calendar_events(h.t)
    assert events is not None and len(events) == 1        # l'ancien cache tient


def test_un_cache_FOSSILE_rend_AVEUGLE_et_ne_publie_RIEN():
    """Passé `max_age_s`, le cache n'est plus une donnée : c'est un souvenir. Le republier avec
    un horodatage frais le blanchirait en donnée courante et ouvrirait le verrou F5 sur un
    calendrier périmé."""
    h = Horloge()
    m = _module(h, max_age_s=100.0)
    asyncio.run(m.refresh())
    assert m.calendar_events(h.t) is not None
    h.t += 101                                            # le cache passe fossile
    assert m.calendar_events(h.t) is None
    assert m.vix_value(h.t) is None
    state = FauxState()
    assert asyncio.run(m.publish(state)) == []                   # rien n'est écrit
    assert state.writes == []


def test_AVEUGLE_n_est_PAS_calme():
    """Sans calendrier utilisable, rendre `near=False` serait une autorisation de trader fondée
    sur rien — même doctrine que `SAFETY_UNKNOWN` côté Porte F0 (D-050)."""
    h = Horloge()
    m = _module(h)
    v = m.news_near(h.t)                                  # jamais rafraîchi
    assert v["blind"] is True and v["regime"] == "SAFETY_UNKNOWN"
    assert v["near"] is False and "refuser" in v["motif"]


def test_un_cache_horodate_dans_le_FUTUR_est_traite_comme_fossile():
    h = Horloge()
    m = _module(h)
    asyncio.run(m.refresh())
    h.t -= 3600                                           # l'horloge recule (désync §4)
    assert m.calendar_events(h.t) is None


def test_la_publication_utilise_les_noms_de_source_que_le_moteur_attend_DEJA():
    """Zéro modification d'`engine.py` : tout le pipeline aval (D-040, Phase 0, panneaux)
    fonctionne tel quel."""
    h = Horloge()
    m = _module(h, cal_flux=_finnhub({"event": "NFP", "impact": "high",
                                      "time": "2026-08-07 12:30:00"}))
    asyncio.run(m.refresh())
    state = FauxState()
    ecrits = asyncio.run(m.publish(state))
    assert set(ecrits) == {"macro_releases", "vix"}
    assert state.last("macro_releases")[2] == "econ_feed"
    assert state.last("vix")[2] == "cboe"


def test_la_provenance_survit_jusque_dans_REDIS():
    """La leçon REPLAY : une donnée de secours doit rester reconnaissable jusqu'au panneau."""
    h = Horloge()
    m = _module(h, vix_val=17.0)
    asyncio.run(m.refresh())
    state = FauxState()
    asyncio.run(m.publish(state))
    drapeaux = state.last("vix")[4]
    assert "EXTERNAL" in drapeaux and "EXTERNAL_FALLBACK" in drapeaux


def test_la_publication_porte_l_horodatage_d_OBSERVATION_pas_now():
    """C'est ce qui laisse la couche de fraîcheur faire son travail sans être prévenue."""
    h = Horloge()
    m = _module(h)
    asyncio.run(m.refresh())
    observe = h.t
    h.t += 300
    state = FauxState()
    asyncio.run(m.publish(state))
    assert state.last("vix")[3] == pytest.approx(observe)      # pas h.t


def test_le_module_ne_detient_AUCUN_second_etat_d_hysteresis():
    """`engine` tient déjà `self._regime_tier` ; en garder un second ici ferait deux paliers D4
    qui divergent. Le palier est donc un PARAMÈTRE, jamais une mémoire."""
    h = Horloge()
    m = ExternalDataModule(calendar=None, vix=StaticVix(16.0), clock=h)
    asyncio.run(m.refresh())
    assert m.vix_regime(h.t, previous_tier="GREEN").tier == "GREEN"
    assert m.vix_regime(h.t, previous_tier="YELLOW").tier == "YELLOW"   # aucune contamination
    assert m.vix_regime(h.t, previous_tier="GREEN").tier == "GREEN"


def test_une_source_QUI_LEVE_devient_une_absence_pas_un_crash():
    def explose(url: str) -> str:
        raise RuntimeError("bug du fournisseur")

    h = Horloge()
    m = ExternalDataModule(calendar=FinnhubCalendar("CLE", fetcher=explose),
                           vix=StaticVix(17.0), clock=h)
    asyncio.run(m.refresh())                                     # ne lève pas
    assert m.calendar_events(h.t) is None
    assert m.vix_value(h.t) == pytest.approx(17.0)        # l'autre source n'est pas emportée


def test_l_etat_du_module_est_LISIBLE_pas_un_dict_de_compteurs():
    h = Horloge()
    m = _module(h)
    asyncio.run(m.refresh())
    etat = m.state_dict(h.t)
    assert etat["calendrier"]["utilisable"] is True
    assert "événement" in etat["calendrier"]["resume"]
    assert etat["vix"]["fallback"] is True


# =============================================================================================
# 11. /devil — trois défauts trouvés en maltraitant ce paquet
# =============================================================================================


def test_un_JSON_profondement_imbrique_ne_fait_pas_EXPLOSER_la_pile():
    """`json` lève une `RecursionError`, qui n'est PAS une `ValueError` : sans branche dédiée
    elle traversait le parser et remontait au worker. Un flux qui fait exploser la pile est
    empoisonné, pas illisible — même issue, `None`, l'appelant garde son cache."""
    assert parse_finnhub_json("[" * 2000 + "]" * 2000) is None


def test_un_fournisseur_QUI_LEVE_n_emporte_pas_la_CHAINE():
    """Le repli est toute la raison d'être de la chaîne : un fournisseur cassé qui l'emporte
    supprime exactement ce qu'elle est censée garantir."""
    class Casse:
        name = "casse"

        def unavailable_reason(self) -> Optional[str]:
            raise RuntimeError("bug de configuration")

        def fetch(self, *, now: float) -> Any:
            raise RuntimeError

    chaine = ChainedCalendar([Casse(), FinnhubCalendar("CLE", fetcher=lambda u: _finnhub())])
    res = chaine.fetch(now=T0)
    assert res.ok                                        # le suivant a bien été essayé
    assert any("a levé" in a and "écarté" in a for a in chaine.attempts)


@pytest.mark.parametrize("fenetre", [float("nan"), float("inf"), float("-inf")])
def test_une_fenetre_F5_NON_FINIE_LEVE_au_lieu_de_devenir_permissive(fenetre):
    """`max(0.0, nan)` rend `0.0` en Python : une fenêtre NaN devenait donc PERMISSIVE et
    autorisait à trader. Une fenêtre absurde est une faute d'APPEL, pas une condition de donnée
    — elle lève, comme un refus de politique (doctrine D-050)."""
    with pytest.raises(ValueError) as e:
        is_high_impact_news_near([_evt(T0)], T0, fenetre)
    assert "non finie" in str(e.value)


def test_le_compte_rendu_de_chaine_ne_REDOUBLE_pas_le_nom_du_fournisseur():
    chaine = ChainedVix([FredVix(api_key=""), StaticVix(17.0)])
    chaine.fetch(now=T0)
    assert not any(a.count("VIX simulé") > 1 for a in chaine.attempts), chaine.attempts
