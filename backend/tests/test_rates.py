"""Feature — courbe des taux et différentiels (D-053 tranche 2), bloc `yield_curve`.

Règle centrale, fixée AVANT le code : **un spread ne se calcule jamais à partir d'un trou**.
Un ténor manquant, périmé ou non fini fait disparaître TOUS les spreads qui en dépendent — et
seulement ceux-là. Un différentiel affiché sur une patte absente serait un chiffre inventé qui a
l'air d'une mesure (§3), la pire forme de mensonge dans un terminal.
"""
import math

from app.rates import SPREADS, TENORS, build_yield_curve


def _raw(**over):
    base = {"US02Y": 4.25, "US10Y": 4.05, "DE02Y": 2.10, "DE10Y": 2.35}
    base.update(over)
    return {"tenors": base}


def _by_code(out, kind):
    return {row["code"]: row for row in out[kind]}


# --- nominal ----------------------------------------------------------------------------------

def test_tenors_normalises_dans_l_ordre_de_la_courbe():
    out = build_yield_curve(_raw())
    assert [t["code"] for t in out["tenors"]] == [code for code, _ in TENORS]
    us10 = _by_code(out, "tenors")["US10Y"]
    assert us10["value_pct"] == 4.05 and us10["label"]


def test_spreads_calcules_en_POINTS_DE_BASE_et_signes():
    """4,05 % − 4,25 % = −20 bp. Le bp est l'unité de lecture du marché obligataire ; afficher
    « −0,2 » dans une colonne de taux serait illisible en séance."""
    out = build_yield_curve(_raw())
    spreads = _by_code(out, "spreads")
    assert spreads["US10Y-US02Y"]["value_bp"] == -20.0
    assert spreads["US10Y-DE10Y"]["value_bp"] == 170.0       # 4,05 − 2,35


def test_courbe_INVERSEE_marquee_comme_un_FAIT():
    """La pente négative est un fait observable, pas une prédiction de récession : le panneau
    l'étiquette, il n'en tire aucune conclusion (§2.1)."""
    out = build_yield_curve(_raw())
    assert _by_code(out, "spreads")["US10Y-US02Y"]["inverted"] is True
    normal = build_yield_curve(_raw(US02Y=3.50))             # 4,05 > 3,50 → pente positive
    assert _by_code(normal, "spreads")["US10Y-US02Y"]["inverted"] is False


def test_seuls_les_spreads_de_pente_portent_l_inversion():
    """« Inversé » n'a de sens que sur une pente (même courbe). Un différentiel transatlantique
    négatif n'est pas une « inversion » — l'étiquette serait un contresens."""
    out = build_yield_curve(_raw(US10Y=1.00))                # différentiel US-DE négatif
    assert _by_code(out, "spreads")["US10Y-DE10Y"]["inverted"] is None


def test_variation_en_bp_reprise_telle_quelle_quand_fournie():
    out = build_yield_curve({"tenors": {"US10Y": 4.05}, "changes_bp": {"US10Y": -3.5}})
    assert _by_code(out, "tenors")["US10Y"]["change_bp"] == -3.5


def test_variation_absente_reste_None_jamais_zero():
    """0 bp signifie « inchangé », ce qui est une information. L'absence de mesure n'en est pas
    une : elle reste None et le panneau affiche un tiret."""
    out = build_yield_curve(_raw())
    assert _by_code(out, "tenors")["US10Y"]["change_bp"] is None


# --- LA règle : pas de spread sur un trou ------------------------------------------------------

def test_tenor_manquant_fait_DISPARAITRE_les_spreads_qui_en_dependent():
    out = build_yield_curve(_raw(US02Y=None))
    codes = [s["code"] for s in out["spreads"]]
    assert "US10Y-US02Y" not in codes                        # dépend du ténor absent
    assert "US10Y-DE10Y" in codes                            # indépendant → conservé
    assert "US02Y" not in _by_code(out, "tenors")


def test_tenor_non_fini_traite_comme_absent():
    for bad in (math.nan, math.inf, -math.inf, "4.05", None, True):
        out = build_yield_curve(_raw(US10Y=bad))
        assert "US10Y" not in _by_code(out, "tenors"), bad
        # US10Y alimente les DEUX spreads : aucun ne doit survivre.
        assert out["spreads"] == [], bad


def test_taux_hors_bornes_plausibles_rejete():
    """Un taux à 900 % ou à −50 % est une erreur d'unité ou de parsing, pas un régime de marché.
    Mieux vaut un ténor absent qu'une échelle de graphique détruite par une valeur folle."""
    for bad in (900.0, -50.0):
        out = build_yield_curve(_raw(US10Y=bad))
        assert "US10Y" not in _by_code(out, "tenors"), bad


def test_taux_negatif_PLAUSIBLE_accepte():
    """Le Bund a réellement coté en territoire négatif : refuser −0,5 % serait refuser la
    réalité de marché. La borne écarte l'absurde, pas l'inhabituel."""
    out = build_yield_curve(_raw(DE10Y=-0.55))
    assert _by_code(out, "tenors")["DE10Y"]["value_pct"] == -0.55
    assert _by_code(out, "spreads")["US10Y-DE10Y"]["value_bp"] == 460.0


# --- structures et fail-closed global ----------------------------------------------------------

def test_structures_inexploitables_rendent_None():
    for bad in (None, [], {}, {"tenors": None}, {"tenors": []}, {"tenors": "US10Y"}, 42, "x"):
        assert build_yield_curve(bad) is None, bad


def test_aucun_tenor_exploitable_rend_None():
    """Un objet à zéro ténor s'afficherait comme « connecté mais vide » — bloc ABSENT à la place."""
    assert build_yield_curve({"tenors": {"US10Y": math.nan, "US02Y": None}}) is None


def test_tenors_inconnus_ignores_sans_casser_le_reste():
    out = build_yield_curve(_raw(JP40Y=1.23, **{"": 4.0}))
    assert "JP40Y" not in _by_code(out, "tenors")
    assert _by_code(out, "tenors")["US10Y"]["value_pct"] == 4.05


def test_changes_bp_malforme_ignore_sans_perdre_les_taux():
    out = build_yield_curve({"tenors": {"US10Y": 4.05}, "changes_bp": "cassé"})
    assert _by_code(out, "tenors")["US10Y"]["change_bp"] is None


def test_toutes_les_paires_declarees_sont_calculables():
    """Garde-fou de cohérence : une paire déclarée sur un ténor inexistant ne produirait jamais
    rien et passerait inaperçue."""
    known = {code for code, _ in TENORS}
    for spec in SPREADS:
        assert spec["long"] in known and spec["short"] in known, spec["code"]


def test_fonction_PURE_aucune_lecture_d_horloge():
    import inspect

    from app import rates
    src = inspect.getsource(rates)
    for banned in ("time.time", "datetime", "perf_counter", "monotonic"):
        assert banned not in src, banned


# --- intégration : le bloc traverse-t-il jusqu'au flux ? ---------------------------------------

import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

from app.datasource.mock import MockDataSource  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.meta import Freshness  # noqa: E402
from app.redis_state import RedisState  # noqa: E402
from app.schema import SLOW_BLOCKS, ContextSchema  # noqa: E402


def _redis_available() -> bool:
    async def probe() -> bool:
        state = RedisState()
        try:
            return await state.ping()
        finally:
            await state.close()
    return asyncio.run(probe())


def test_bloc_declare_sur_le_canal_LENT():
    assert "yield_curve" in SLOW_BLOCKS and hasattr(ContextSchema(), "yield_curve")


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_moteur_publie_une_courbe_coherente():
    async def scenario():
        state = RedisState()
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up("rates_feed", True)
            engine = Engine(MockDataSource(), state)
            block = None
            for _ in range(8):
                await engine.ds.tick_slow(state)
                await engine._assemble_slow(time.time())
                candidate = engine.schema.yield_curve
                if candidate.freshness == Freshness.FRESH and candidate.value:
                    block = candidate
                    break
            assert block is not None, "la courbe n'est jamais devenue FRESH"
            value = block.value
            codes = {t["code"] for t in value["tenors"]}
            for spread in value["spreads"]:
                # LA propriété : aucun spread ne survit sans ses DEUX pattes.
                assert spread["long"] in codes and spread["short"] in codes, spread["code"]
        finally:
            await state.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_patte_manquante_dans_le_flux_supprime_le_spread_pas_la_courbe():
    async def scenario():
        state = RedisState()
        try:
            await state.set_source_up("rates_feed", True)
            engine = Engine(MockDataSource(), state)
            await state.write_raw("yields", {"tenors": {"US10Y": 4.05, "DE10Y": 2.35}},
                                  "rates_feed", ts=time.time(), flags=[])
            await engine._assemble_slow(time.time())
            value = engine.schema.yield_curve.value
            assert {t["code"] for t in value["tenors"]} == {"US10Y", "DE10Y"}
            assert [s["code"] for s in value["spreads"]] == ["US10Y-DE10Y"]   # la pente disparaît
        finally:
            await state.close()
    asyncio.run(scenario())
