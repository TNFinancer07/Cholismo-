"""Feature — jointure des entrées externes sur une séance rejouée (D-084, phase P2).

VIX, calendrier et ATR rejoignent le flux MBO pour que F0/G2 cessent de refuser par manque
d'information. **Le risque de cette feature n'est pas qu'elle échoue : c'est qu'elle réussisse
trop bien.** Une jointure négligente injecte des données du futur, les gates s'ouvrent, les
chiffres deviennent excellents — et faux.

D'où l'ordre de priorité de ces tests : **d'abord l'absence de lookahead**, ensuite la
péremption, ensuite seulement le fonctionnement nominal.
"""
import json

import pytest

from app.mbo.session_context import (
    NEWS_BLACKOUT_AFTER_S, NEWS_BLACKOUT_BEFORE_S, AtrTracker, CalendarPoint, SessionContext,
    TimedValue,
)

T0 = 1_700_000_000.0


# ---------------------------------------------------------------------------
# 1. AUCUN LOOKAHEAD — le test qui compte plus que tous les autres
# ---------------------------------------------------------------------------

def test_une_valeur_PUBLIEE_APRES_l_instant_n_est_JAMAIS_rendue():
    """Le cœur de la feature. Interroger une API « au présent » pendant un rejeu injecterait le
    VIX d'aujourd'hui dans une séance d'alors — un lookahead d'autant plus coûteux qu'il est
    invisible : les chiffres sont réels, ils sont simplement de la mauvaise date."""
    ctx = SessionContext(vix=[TimedValue(T0 + 100, 18.0)])
    assert ctx.vix_at(T0) is None
    assert ctx.vix_at(T0 + 99) is None
    assert ctx.vix_at(T0 + 100) == 18.0, "publiée exactement à t, elle est connue à t"


def test_la_valeur_rendue_est_la_DERNIERE_publiee_pas_la_plus_proche():
    """« La plus proche » regarderait devant. On prend la dernière publiée, point."""
    ctx = SessionContext(vix=[TimedValue(T0, 15.0), TimedValue(T0 + 1000, 25.0)])
    # T0+900 est plus PROCHE de T0+1000 (100 s) que de T0 (900 s) — et pourtant c'est 15.0.
    assert ctx.vix_at(T0 + 900) == 15.0


def test_une_serie_DESORDONNEE_est_triee_a_la_construction():
    """La jointure suppose l'ordre ; un fichier fourni ne le garantit pas."""
    ctx = SessionContext(vix=[TimedValue(T0 + 200, 20.0), TimedValue(T0, 15.0),
                              TimedValue(T0 + 100, 18.0)])
    assert ctx.vix_at(T0 + 150) == 18.0


# ---------------------------------------------------------------------------
# 2. La péremption reste la péremption
# ---------------------------------------------------------------------------

def test_une_valeur_TROP_VIEILLE_devient_absente():
    """Un VIX de la veille n'est pas le VIX de la séance. Le traîner indéfiniment ferait passer
    une donnée d'une autre journée pour le contexte du moment."""
    ctx = SessionContext(vix=[TimedValue(T0, 15.0)], vix_max_age_s=3600.0)
    assert ctx.vix_at(T0 + 3599) == 15.0
    assert ctx.vix_at(T0 + 3601) is None


def test_une_serie_VIDE_ne_rend_aucun_defaut():
    """Injecter « VIX = 15 parce que c'est une valeur courante » fabriquerait le contexte qu'on
    prétend mesurer."""
    assert SessionContext().vix_at(T0) is None
    assert SessionContext().news_state_at(T0) is None


def test_un_instant_NON_FINI_ne_rend_rien():
    ctx = SessionContext(vix=[TimedValue(T0, 15.0)])
    for mauvais in (float("nan"), float("inf"), None, "x"):
        assert ctx.vix_at(mauvais) is None


def test_les_entrees_ILLISIBLES_sont_ECARTEES_a_la_construction():
    ctx = SessionContext(vix=[TimedValue(float("nan"), 15.0), TimedValue(T0, float("inf")),
                              TimedValue(T0 + 10, 16.0)])
    assert len(ctx.vix) == 1 and ctx.vix_at(T0 + 10) == 16.0


# ---------------------------------------------------------------------------
# 3. Le calendrier — annoncé à l'avance, et c'est légitime
# ---------------------------------------------------------------------------

def test_un_evenement_FUTUR_est_visible_car_le_calendrier_est_ANNONCE():
    """Contrairement au VIX, les entrées futures d'un calendrier sont légitimement connues :
    c'est tout l'intérêt de F5, qui protège d'une publication À VENIR."""
    ctx = SessionContext(calendar=[CalendarPoint(T0 + 3600, "CPI", tier1=True)])
    assert ctx.events_known_at(T0) != []


def test_un_evenement_HORS_HORIZON_n_est_pas_remonte():
    ctx = SessionContext(calendar=[CalendarPoint(T0 + 90_000, "FOMC", tier1=True)])
    assert ctx.events_known_at(T0, horizon_s=3600) == []


def test_le_blackout_TIER_1_verrouille_la_porte_F0():
    ctx = SessionContext(calendar=[CalendarPoint(T0, "NFP", tier1=True)])
    assert ctx.news_state_at(T0 - NEWS_BLACKOUT_BEFORE_S + 1) == "HARD_LOCK"
    assert ctx.news_state_at(T0) == "HARD_LOCK"
    assert ctx.news_state_at(T0 + NEWS_BLACKOUT_AFTER_S - 1) == "HARD_LOCK"


def test_hors_blackout_avec_un_calendrier_CONNU_la_porte_peut_dire_SAFE():
    """C'est l'apport de la jointure : sans calendrier, F0 restait fail-closed faute de savoir.
    Avec lui, on peut répondre `SAFE` en connaissance de cause."""
    ctx = SessionContext(calendar=[CalendarPoint(T0, "NFP", tier1=True)])
    assert ctx.news_state_at(T0 + 3600) == "SAFE"


def test_un_evenement_NON_tier1_ne_verrouille_pas():
    ctx = SessionContext(calendar=[CalendarPoint(T0, "Discours mineur", tier1=False)])
    assert ctx.news_state_at(T0) == "SAFE"


# ---------------------------------------------------------------------------
# 4. Chargement
# ---------------------------------------------------------------------------

def test_les_deux_formes_de_ligne_sont_acceptees():
    """`{"ts":…,"value":…}` et `[ts, value]` circulent tous deux dans les exports ; exiger la
    seule qu'on préfère ferait rejeter un fichier valide."""
    ctx = SessionContext.from_dict({"vix": [{"ts": T0, "value": 15.0}, [T0 + 10, 16.0]]})
    assert ctx.vix_at(T0) == 15.0 and ctx.vix_at(T0 + 10) == 16.0


def test_un_dict_ABERRANT_ne_leve_pas():
    for mauvais in (None, 42, "x", {"vix": "pas une liste"}, {"vix": [None, {}, [1]]}):
        assert SessionContext.from_dict(mauvais).vix_at(T0) is None


def test_chargement_depuis_un_fichier_JSON(tmp_path):
    path = tmp_path / "contexte.json"
    path.write_text(json.dumps({
        "vix": [{"ts": T0, "value": 17.5}],
        "calendar": [{"ts": T0 + 600, "name": "CPI", "tier1": True}],
    }), encoding="utf-8")
    ctx = SessionContext.from_json_file(str(path))
    assert ctx.vix_at(T0 + 60) == 17.5
    assert ctx.diagnostics()["tier1_events"] == 1


# ---------------------------------------------------------------------------
# 5. L'ATR — dérivé du flux, pas d'une source externe
# ---------------------------------------------------------------------------

def test_l_ATR_reste_None_sous_la_fenetre_complete():
    """Une moyenne sur 3 barres annoncée comme un ATR 14 serait un chiffre au nom trompeur."""
    atr = AtrTracker(bar_seconds=60, fast=14, slow=50)
    for i in range(5):
        atr.observe(5000.0 + i, T0 + i * 60)
    assert atr.atr_fast is None and atr.atr_slow is None


def test_l_ATR_se_calcule_une_fois_la_fenetre_remplie():
    atr = AtrTracker(bar_seconds=60, fast=3, slow=5)
    for i in range(10):
        atr.observe(5000.0, T0 + i * 60)             # amplitude nulle sur chaque barre
        atr.observe(5001.0, T0 + i * 60 + 30)        # → range de 1,0
    assert atr.atr_fast == pytest.approx(1.0)
    assert atr.atr_slow == pytest.approx(1.0)


def test_l_ATR_ne_vient_d_AUCUNE_source_externe():
    """Une seconde source produirait des barres qui ne coïncideraient pas avec celles qu'on
    mesure — donc deux vérités sur le même instrument."""
    import inspect

    from app.mbo import session_context
    src = inspect.getsource(session_context.AtrTracker)
    for interdit in ("fetch", "requests", "httpx", "FredVix", "url"):
        assert interdit not in src


def test_l_ATR_ne_leve_jamais_et_borne_sa_memoire():
    atr = AtrTracker(bar_seconds=60, fast=3, slow=5)
    for mauvais in (None, "x", float("nan"), -1.0, 0.0):
        atr.observe(mauvais, T0)
    for i in range(500):
        atr.observe(5000.0 + (i % 3), T0 + i * 60)
    assert atr.diagnostics()["bars_closed"] <= 5 * 4


# ---------------------------------------------------------------------------
# 6. Branchement sur le détecteur — l'apport réel
# ---------------------------------------------------------------------------

def _ev(action, side, price, size, order_id=0, ms=0):
    from app.mbo.events import MboEvent
    base = 1_700_000_000_000_000_000
    return MboEvent(ts_event=base + ms * 1_000_000, ts_recv=base + ms * 1_000_000,
                    action=action, side=side, price=price, size=size,
                    order_id=order_id, sequence=ms, symbol="MESZ4")


def _book():
    from app.mbo.book import MboBook
    from app.mbo.events import MboAction, MboSide
    book = MboBook(tick_size=0.25)
    for i in range(5):
        book.apply(_ev(MboAction.ADD, MboSide.BID, 5000.00 - i * 0.25, 40, order_id=100 + i))
        book.apply(_ev(MboAction.ADD, MboSide.ASK, 5000.25 + i * 0.25, 40, order_id=200 + i))
    return book


def test_le_VIX_joint_apparait_FRESH_dans_le_schema():
    from app.mbo.lsr_adapter import MboLsrDetector
    ctx = SessionContext(vix=[TimedValue(T0 - 60, 17.5)])
    detector = MboLsrDetector(tick_size=0.25, context=ctx)
    schema = detector.build_schema(_book(), now=T0)
    field = schema.s2_state.cascade.vix
    assert field.freshness.value == "FRESH" and field.value == 17.5
    assert field.source == "session_context"


def test_SANS_contexte_le_VIX_reste_ABSENT_et_les_gates_refusent():
    from app.mbo.lsr_adapter import MboLsrDetector
    schema = MboLsrDetector(tick_size=0.25).build_schema(_book(), now=T0)
    assert schema.s2_state.cascade.vix.freshness.value == "ABSENT"


def test_un_VIX_du_FUTUR_n_est_pas_joint_meme_avec_contexte():
    """L'invariant anti-lookahead vérifié jusqu'au bout de la chaîne, pas seulement dans le
    module de jointure."""
    from app.mbo.lsr_adapter import MboLsrDetector
    ctx = SessionContext(vix=[TimedValue(T0 + 3600, 30.0)])
    schema = MboLsrDetector(tick_size=0.25, context=ctx).build_schema(_book(), now=T0)
    assert schema.s2_state.cascade.vix.freshness.value == "ABSENT"


def test_le_diagnostic_dit_ce_qui_est_JOINT_et_ce_qui_est_DERIVE():
    from app.mbo.lsr_adapter import MboLsrDetector
    ctx = SessionContext(vix=[TimedValue(T0, 15.0)],
                         calendar=[CalendarPoint(T0 + 600, "CPI", tier1=True)])
    diag = MboLsrDetector(tick_size=0.25, context=ctx).diagnostics()
    assert set(diag["inputs_joined_from_context"]) == {"vix", "econ_calendar", "news_state"}
    assert set(diag["inputs_derived_from_flow"]) == {"atr_session", "vpoc"}
    assert diag["inputs_absent_from_mbo"] == [], "plus rien ne manque structurellement (D-085)"
    assert diag["context"]["vix_points"] == 1 and diag["context"]["tier1_events"] == 1


def test_l_etat_F0_du_CONTEXTE_prime_sur_celui_passe_a_la_construction():
    """Le contexte est la source datée ; la valeur de construction n'est qu'un défaut pour les
    rejeux sans calendrier. Laisser le défaut gagner ferait ignorer un blackout réel."""
    from app.mbo.lsr_adapter import MboLsrDetector
    ctx = SessionContext(calendar=[CalendarPoint(T0, "NFP", tier1=True)])
    detector = MboLsrDetector(tick_size=0.25, context=ctx, news_state="SAFE")
    assert detector.context.news_state_at(T0) == "HARD_LOCK"
