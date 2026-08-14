"""Bout à bout : les sources externes pilotent RÉELLEMENT les verrous F5 et F3 (D-062).

Le test qui compte. Les tests unitaires prouvent que chaque pièce se comporte bien ; celui-ci
prouve la seule chose qui intéresse l'opérateur : **une publication au calendrier fait
effectivement basculer Phase 0 en BLOQUÉ, et un VIX externe déclenche effectivement le veto** —
sans qu'`engine.py` ait été modifié d'une ligne.

C'est aussi ce qui justifie le choix d'architecture : le module écrit `macro_releases` sous
`econ_feed` et `vix` sous `cboe`, les noms de source que le moteur attend DÉJÀ. Si ce test passe,
tout le pipeline aval (normalisation D-040, `compute_macro_risk`, `MACRO_BLACKOUT`, panneaux)
fonctionne sans avoir été prévenu.

Le mode replay est choisi à dessein pour les premiers tests : `ReplayDataSource.tick_slow`
n'écrit rien, donc le module externe est trivialement le seul producteur.

La dernière section couvre le cas MOCK, qui posait un vrai conflit d'écriture — deux producteurs
pour une même clé, donc une valeur décidée par l'ordonnancement. Il est résolu par la PROPRIÉTÉ
déclarée (`external.OWNED_FIELDS` → `MockDataSource(skip_fields=…)`) : le mock ne produit plus
ces champs, il n'est pas simplement écrasé. La différence n'est pas cosmétique — être écrasé
donne le même écran par accident, et le jour où l'ordre change, la valeur change aussi.
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


# =============================================================================================
# Le conflit d'écriture est RÉSOLU, pas silencé
# =============================================================================================


def test_le_mock_ne_produit_PLUS_les_champs_appartenant_a_la_source_externe():
    """Deux producteurs pour une même clé, c'est le dernier tick qui gagne : une valeur qui
    dépend de l'ordonnancement, donc de rien. Le mock ne les produit plus — il n'est pas
    simplement écrasé, ce qui donnerait le même écran par accident."""
    from app.datasource.mock import MockDataSource
    from app.external import OWNED_FIELDS

    class Capture:
        """Redis remplacé par un dictionnaire — couvre les trois méthodes que le mock utilise."""

        def __init__(self) -> None:
            self.champs: set[str] = set()

        async def write_raw(self, field, value, source, ts=None, flags=None):  # type: ignore[no-untyped-def]
            self.champs.add(field)

        async def source_up(self, source):   # type: ignore[no-untyped-def]
            return True

        async def scenario(self):            # type: ignore[no-untyped-def]
            return None          # scénario par défaut : `resolve(None)` le gère

    async def scenario() -> tuple[set[str], set[str]]:
        libre, bride = Capture(), Capture()
        for src, cap in ((MockDataSource(), libre),
                         (MockDataSource(skip_fields=OWNED_FIELDS), bride)):
            await src.tick_fast(cap)
            await src.tick_slow(cap)
        return libre.champs, bride.champs

    libre, bride = asyncio.run(scenario())
    assert set(OWNED_FIELDS) <= libre, "le mock produisait bien ces champs auparavant"
    assert not (set(OWNED_FIELDS) & bride), f"le mock produit encore : {set(OWNED_FIELDS) & bride}"
    # Le reste de la production du mock est INTACT : on retire deux champs, pas une source.
    assert len(bride) >= len(libre) - len(OWNED_FIELDS)
    assert "econ_calendar" in bride            # même source `econ_feed`, mais pas le même champ


def test_la_valeur_EXTERNE_survit_a_un_tick_complet_du_mock(tmp_path):
    """Le test qui aurait attrapé le conflit : sans la propriété, `vix` valait ce que le dernier
    tick du mock avait écrit, et la valeur externe disparaissait en silence."""
    from app.datasource.mock import MockDataSource
    from app.external import OWNED_FIELDS, ExternalDataModule, StaticVix

    async def scenario() -> float:
        state = RedisState()
        module = ExternalDataModule(calendar=None, vix=StaticVix(28.5))
        await module.refresh()
        await module.publish(state)
        mock = MockDataSource(skip_fields=OWNED_FIELDS)
        for _ in range(5):
            await mock.tick_fast(state)
        brut = await state.read_raw("vix")
        await state.close()
        return float(brut["value"])

    assert asyncio.run(scenario()) == pytest.approx(28.5)


def test_sans_source_externe_le_mock_garde_TOUTE_sa_production():
    """Le contrôle négatif : la bride ne doit s'appliquer que lorsqu'un propriétaire existe,
    sinon `EXTERNAL_DATA` absent priverait le stack démo de son VIX."""
    from app.datasource.mock import MockDataSource

    class Capture:
        """Redis remplacé par un dictionnaire — couvre les trois méthodes que le mock utilise."""

        def __init__(self) -> None:
            self.champs: set[str] = set()

        async def write_raw(self, field, value, source, ts=None, flags=None):  # type: ignore[no-untyped-def]
            self.champs.add(field)

        async def source_up(self, source):   # type: ignore[no-untyped-def]
            return True

        async def scenario(self):            # type: ignore[no-untyped-def]
            return None          # scénario par défaut : `resolve(None)` le gère

    cap = Capture()

    async def scenario() -> None:
        src = MockDataSource()
        await src.tick_fast(cap)
        await src.tick_slow(cap)

    asyncio.run(scenario())
    assert {"vix", "macro_releases"} <= cap.champs
