"""Filet — remontée de l'âge de la donnée sur coupure de source (finding /loop-check).

Fige le contrat « no signal without data » (CLAUDE §2.3/§8) à deux niveaux :
1. `make_meta` (pure) : FRESH → STALE → ABSENT selon l'âge ; NaN/None → ABSENT ;
   au-delà du seuil ABSENT la valeur est RETIRÉE (None), jamais affichée comme réelle.
2. Moteur + mock + Redis réels, HORLOGE CONTRÔLÉE (le `now` passé à `_assemble_fast`
   avance, zéro sleep) : couper `sierra_chart` → `svs_score` FRESH → STALE (valeur
   encore montrée, badge d'âge) → ABSENT (valeur None) → Phase 0 BLOQUÉ (fail-closed).

Le badge écran (`MetaValue`) est une fonction pure de ce contrat sérialisé
(`freshness` + `last_update_ts` + `value`) — c'est lui qui est figé ici ; le rendu a été
vérifié par captures E2E (`docs/`).
"""
import asyncio
import math
import time

import pytest

from app import config
from app.datasource.mock import MockDataSource
from app.engine import Engine
from app.meta import Freshness, make_meta
from app.redis_state import RedisState
from app.schema import Phase0State


# ---------- 1. make_meta — escalade pure ----------

def test_make_meta_escalates_fresh_stale_absent():
    now = 1_000_000.0
    fresh = make_meta(42.0, "src", now - 1.0, stale_after=3.0, absent_after=15.0, now=now)
    stale = make_meta(42.0, "src", now - 5.0, stale_after=3.0, absent_after=15.0, now=now)
    absent = make_meta(42.0, "src", now - 20.0, stale_after=3.0, absent_after=15.0, now=now)

    assert fresh.freshness == Freshness.FRESH and fresh.value == 42.0
    assert stale.freshness == Freshness.STALE and stale.value == 42.0  # grisé + âge à l'écran
    # Trop vieux pour être fiable : la valeur est RETIRÉE, jamais inventée/affichée réelle.
    assert absent.freshness == Freshness.ABSENT and absent.value is None
    assert absent.last_update_ts == now - 20.0  # l'âge réel reste calculable à l'écran


def test_make_meta_nan_or_missing_ts_is_absent():
    now = 1_000_000.0
    nan = make_meta(math.nan, "src", now, stale_after=3.0, absent_after=15.0, now=now)
    no_ts = make_meta(42.0, "src", None, stale_after=3.0, absent_after=15.0, now=now)
    assert nan.freshness == Freshness.ABSENT and nan.value is None
    assert no_ts.freshness == Freshness.ABSENT and no_ts.value is None


# ---------- 2. moteur — coupure de source, horloge contrôlée ----------

def _redis_available() -> bool:
    async def probe() -> bool:
        state = RedisState()
        try:
            return await state.ping()
        finally:
            await state.close()
    return asyncio.run(probe())


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_source_cut_escalates_to_absent_and_phase0_blocks():
    async def scenario() -> None:
        state = RedisState()
        previous_scenario = await state.scenario()
        engine = Engine(MockDataSource(), state)
        try:
            # État déterministe : scénario calme, fenêtre simulée (D-020), source up.
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, True)

            await engine.ds.tick_fast(state)
            await engine.ds.tick_slow(state)
            t0 = time.time()
            await engine._assemble_fast(t0)
            svs = engine.schema.s1_state.svs_score
            assert svs.freshness == Freshness.FRESH and svs.value is not None

            # Coupure : le mock cesse d'écrire, Redis garde le dernier ts → l'âge court.
            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, False)

            await engine._assemble_fast(t0 + config.FAST_STALE_SECONDS + 2)
            svs = engine.schema.s1_state.svs_score
            assert svs.freshness == Freshness.STALE
            assert svs.value is not None            # encore montrée, grisée + âge

            await engine._assemble_fast(t0 + config.FAST_ABSENT_SECONDS + 5)
            svs = engine.schema.s1_state.svs_score
            assert svs.freshness == Freshness.ABSENT
            assert svs.value is None                # jamais une valeur inventée
            si = engine.schema.session_identity
            assert si.phase0 == Phase0State.BLOCKED  # fail-closed (CLAUDE §2.2/§2.3)
            assert any("absent" in b.detail.lower() for b in si.phase0_blockers)
        finally:
            await state.set_source_up(config.MICROSTRUCTURE_SOURCE, True)
            if previous_scenario is not None:
                await state.set_scenario(previous_scenario)
            await state.close()

    asyncio.run(scenario())


def test_le_nom_de_la_source_de_MICROSTRUCTURE_est_pilotable(monkeypatch):
    """Il était codé en dur à vingt endroits : changer de plateforme demandait un renommage
    global, et une occurrence oubliée aurait fait vieillir un champ vers ABSENT sans que rien
    ne l'explique. Une seule constante, pilotable par l'environnement."""
    from app import config
    from app.datasource.mock import SOURCES
    assert config.MICROSTRUCTURE_SOURCE == "bookmap"       # défaut
    # Les champs de microstructure appartiennent tous à CETTE source, pas à un nom en dur.
    possede = SOURCES[config.MICROSTRUCTURE_SOURCE]
    for champ in ("order_book", "tape", "vpoc", "cvd", "absorption"):
        assert champ in possede, champ


def test_aucun_nom_de_plateforme_ne_reste_CODE_EN_DUR_dans_app():
    """Le garde qui empêche la régression : un `"bookmap"` littéral réintroduit ailleurs
    échapperait à la constante et casserait le prochain changement de plateforme."""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parent.parent / "app"
    coupables = []
    for f in racine.rglob("*.py"):
        texte = f.read_text(encoding="utf-8")
        for interdit in ('"bookmap"', "'bookmap'", '"sierra_chart"', "'sierra_chart'"):
            if interdit in texte and f.name != "config.py":
                coupables.append(f"{f.relative_to(racine)} → {interdit}")
    assert not coupables, "nom de plateforme en dur hors config : " + ", ".join(coupables)
