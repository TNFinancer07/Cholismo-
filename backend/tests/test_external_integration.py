"""Bout à bout : les sources externes pilotent RÉELLEMENT les verrous F5 et F3 (D-062).

Le test qui compte. Les tests unitaires prouvent que chaque pièce se comporte bien ; celui-ci
prouve la seule chose qui intéresse l'opérateur : **une publication au calendrier fait
effectivement basculer Phase 0 en BLOQUÉ, et un VIX externe déclenche effectivement le veto** —
sans qu'`engine.py` ait été modifié d'une ligne.

C'est aussi ce qui justifie le choix d'architecture : le module écrit `macro_releases` sous
`econ_feed` et `vix` sous `cboe`, les noms de source que le moteur attend DÉJÀ. Si ce test passe,
tout le pipeline aval (normalisation D-040, `compute_macro_risk`, `MACRO_BLACKOUT`, panneaux)
fonctionne sans avoir été prévenu.

Le mode replay est choisi à dessein : `ReplayDataSource.tick_slow` n'écrit rien, donc le module
externe est le SEUL à écrire ces champs. En mode mock, le mock les réécrirait à chaque tick —
c'est le conflit que `main.py` signale par un WARNING au démarrage.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from app.datasource.replay import ReplayDataSource
from app.engine import Engine
from app.external import ChainedCalendar, ExternalDataModule, LocalCalendarFile, StaticVix
from app.redis_state import RedisState
from app.replay.mock_data_generator import generer


def _redis_available() -> bool:
    async def probe() -> bool:
        state = RedisState()
        try:
            return await state.ping()
        finally:
            await state.close()
    return asyncio.run(probe())


pytestmark = pytest.mark.skipif(not _redis_available(),
                                reason="Redis indisponible — intégration sautée")


async def _monter(tmp_path: Path, *, delta_s: float, vix: float) -> Engine:
    """Un terminal en replay + un calendrier local portant UNE publication à `now + delta_s`."""
    tape = tmp_path / "tape.csv"
    generer(tape, 200)
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps([{"ts": time.time() + delta_s, "name": "Nonfarm Payrolls",
                                "impact": "HIGH", "country": "US"}]), encoding="utf-8")
    state = RedisState()
    module = ExternalDataModule(calendar=ChainedCalendar([LocalCalendarFile(str(cal))]),
                                vix=StaticVix(vix))
    await module.refresh()
    ecrits = await module.publish(state)
    assert set(ecrits) == {"macro_releases", "vix"}
    engine = Engine(ReplayDataSource(str(tape), speed=50.0), state)
    await engine._assemble_slow(time.time())
    await engine._assemble_fast(time.time())
    return engine


def _bloqueurs(engine: Engine) -> dict[str, str]:
    return {b.rule: b.detail for b in engine.schema.session_identity.phase0_blockers}


def test_une_publication_IMMINENTE_bloque_reellement_Phase_0(tmp_path):
    """F5 de bout en bout : fichier local → module → Redis → moteur → règle déterministe."""
    engine = asyncio.run(_monter(tmp_path, delta_s=60, vix=21.5))
    bloqueurs = _bloqueurs(engine)
    assert "MACRO_BLACKOUT" in bloqueurs
    assert "Nonfarm Payrolls" in bloqueurs["MACRO_BLACKOUT"]      # le POURQUOI, pas juste BLOQUÉ
    assert engine.schema.macro_risk.value["regime"] == "EXECUTION_PAUSED"


def test_la_MEME_publication_LOINTAINE_ne_bloque_pas(tmp_path):
    """Le contrôle négatif : sans lui, un verrou toujours fermé passerait pour un verrou qui
    marche."""
    engine = asyncio.run(_monter(tmp_path, delta_s=7200, vix=21.5))
    assert "MACRO_BLACKOUT" not in _bloqueurs(engine)
    assert engine.schema.macro_risk.value["regime"] == "NORMAL"


def test_un_VIX_EXTERNE_au_dessus_du_seuil_AUTORITE_declenche_le_veto(tmp_path):
    """F3 de bout en bout — et c'est bien `VIX_CRIT` (AUTORITÉ) qui tranche, pas le paquet."""
    engine = asyncio.run(_monter(tmp_path, delta_s=7200, vix=34.0))
    bloqueurs = _bloqueurs(engine)
    assert "VIX_LIMIT" in bloqueurs and "34" in bloqueurs["VIX_LIMIT"]


def test_un_VIX_EXTERNE_sous_le_seuil_ne_declenche_rien(tmp_path):
    engine = asyncio.run(_monter(tmp_path, delta_s=7200, vix=21.5))
    assert "VIX_LIMIT" not in _bloqueurs(engine)


def test_la_PROVENANCE_de_repli_arrive_INTACTE_jusque_dans_le_schema(tmp_path):
    """La leçon REPLAY (D-058) tenue jusqu'au bout de la chaîne : une valeur de secours reste
    reconnaissable dans le champ que le panneau lit. Sans cela, un VIX simulé serait
    indiscernable d'un VIX mesuré — le seul état vraiment dangereux."""
    engine = asyncio.run(_monter(tmp_path, delta_s=7200, vix=21.5))
    champ = engine.schema.s2_state.cascade.vix
    assert champ.value == pytest.approx(21.5)
    assert "EXTERNAL" in champ.flags and "EXTERNAL_FALLBACK" in champ.flags
