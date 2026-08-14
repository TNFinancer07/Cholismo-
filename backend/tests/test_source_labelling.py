"""Le mock ne doit JAMAIS pouvoir se faire passer pour un fournisseur réel (D-093).

`CLAUDE §3` : « en absence de données → fail-closed, jamais une valeur inventée affichée comme
réelle ». La provenance fait partie de la valeur : un chiffre simulé étiqueté `rithmic` est une
valeur inventée présentée comme une mesure, même si le nombre lui-même est plausible.

Le défaut réel : `Engine._meta` affiche `raw["source"]` — l'étiquette apposée par le WRITER.
`ReplayDataSource` s'estampille honnêtement (`SOURCE_NAME = "replay"`) ; `MockDataSource`
empruntait le nom configuré dans `MICROSTRUCTURE_SOURCE`. Poser `MICROSTRUCTURE_SOURCE=rithmic`
suffisait donc à faire afficher « source : rithmic » sur une séance entièrement simulée.
"""
from __future__ import annotations

import asyncio

from app import config
from app.datasource.mock import SOURCES, MockDataSource, mock_label
from app.datasource.replay import SOURCE_NAME as REPLAY_SOURCE_NAME


class _StateEspion:
    """Enregistre ce que le mock ESTAMPILLE. Pas de Redis : on teste l'étiquette, pas le stockage."""

    def __init__(self, scenario: dict | None = None) -> None:
        self.writes: list[dict] = []
        self.gates: list[str] = []          # noms interrogés pour la coupure de source
        self._scenario = scenario

    async def scenario(self):
        return self._scenario

    async def source_up(self, source: str) -> bool:
        self.gates.append(source)
        return True

    async def write_raw(self, field, value, source, ts=None, flags=None) -> None:
        self.writes.append({"field": field, "source": source})


def _run_mock(monkeypatch=None) -> _StateEspion:
    state = _StateEspion()
    ds = MockDataSource()
    asyncio.run(ds.tick_fast(state))
    asyncio.run(ds.tick_slow(state))
    assert state.writes, "le mock n'a rien écrit — le test ne prouverait rien"
    return state


def test_le_mock_n_emprunte_JAMAIS_le_nom_d_un_fournisseur_reel(monkeypatch):
    """La reproduction du défaut. Avant correction, ce test échoue sur `rithmic`."""
    monkeypatch.setattr(config, "MICROSTRUCTURE_SOURCE", "rithmic")
    state = _run_mock()

    usurpes = sorted({w["source"] for w in state.writes if w["source"] == "rithmic"})
    assert not usurpes, (
        "une lecture SIMULÉE est estampillée du nom d'un fournisseur réel : "
        f"{usurpes} — l'opérateur lirait « source : rithmic » sur du mock")


def test_chaque_ecriture_du_mock_porte_la_marque_mock():
    """Systémique, pas au cas par cas : `cboe`, `cme`, `fx_feed`… relèvent du même danger que la
    microstructure. Une correction qui ne viserait que `MICROSTRUCTURE_SOURCE` laisserait six
    autres noms de fournisseurs usurpables."""
    state = _run_mock()

    nus = sorted({w["source"] for w in state.writes if not w["source"].startswith("mock:")})
    assert not nus, f"étiquettes sans marque de simulation : {nus}"


def test_aucune_etiquette_du_mock_ne_coincide_avec_un_nom_de_source_declare():
    """Le test qui MORD : aucune étiquette apposée ne doit être égale à un nom de source
    logique. C'est ce qui rend l'usurpation impossible, pas seulement improbable."""
    state = _run_mock()

    apposees = {w["source"] for w in state.writes}
    collisions = sorted(apposees & set(SOURCES))
    assert not collisions, f"étiquettes indiscernables d'une source réelle : {collisions}"


def test_la_coupure_de_source_reste_pilotee_par_le_nom_LOGIQUE():
    """La correction ne doit pas casser `/sources` : les bascules de coupure portent sur le nom
    logique (clé de `SOURCES`, clé Redis), pas sur l'étiquette apposée. Séparer les deux est tout
    l'intérêt — on estampille la provenance sans renommer l'identité."""
    state = _run_mock()

    assert state.gates, "aucune coupure interrogée — la garde ne serait plus exercée"
    inconnus = sorted({g for g in state.gates if g not in SOURCES})
    assert not inconnus, (
        f"coupure interrogée sur un nom absent de SOURCES : {inconnus} — "
        "les bascules de /sources ne l'atteindraient plus")


def test_mock_label_est_idempotent_et_ne_renomme_pas_l_identite():
    assert mock_label("cboe") == "mock:cboe"
    assert mock_label(mock_label("cboe")) == "mock:cboe", "double préfixe = étiquette illisible"
    assert mock_label("cboe").endswith("cboe"), "l'identité logique doit rester lisible"


def test_le_rejeu_garde_sa_propre_etiquette_honnete():
    """Le modèle qu'on imite : le rejeu s'annonce comme rejeu depuis toujours. Ce test verrouille
    la symétrie — les trois sources (mock, rejeu, live) doivent dire ce qu'elles sont."""
    assert REPLAY_SOURCE_NAME == "replay"
    assert REPLAY_SOURCE_NAME not in SOURCES, "un rejeu ne se déguise pas en fournisseur"
