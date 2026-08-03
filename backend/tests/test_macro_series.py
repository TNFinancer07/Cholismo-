"""Le pont registre → `ContextSchema` (D-063).

Ces tests protègent surtout ce que le pont REFUSE de faire : alimenter un champ dont la formule
n'est pas figée, calculer un score sur des composantes partielles, ou interroger des séries dont
personne n'a besoin.

Le point le plus important : **la faisabilité est DÉRIVÉE du registre, jamais déclarée**. Un
tableau écrit à la main mentirait le jour où un identifiant C2 est relevé — ou pire, resterait
« OK » après qu'une source soit passée C3.

Aucun test n'ouvre de socket : le `fetcher` est injecté.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from app.external.macro_series import (BY_FIELD, OWNED_FIELDS, RECIPES, MacroSeriesProvider,
                                       rapport)
from app.providers.connectors import Observation, ParsedSeries
from app.providers.client import SeriesResult

T0 = 1_785_600_000.0


class FauxState:
    """Redis remplacé par un dictionnaire."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, Any, str, Optional[float], list[str]]] = []

    async def write_raw(self, field, value, source, ts=None, flags=None):   # type: ignore[no-untyped-def]
        self.writes.append((field, value, source, ts, list(flags or [])))

    def last(self, field: str):   # type: ignore[no-untyped-def]
        return next(w for w in reversed(self.writes) if w[0] == field)


def _serie(*valeurs: float, cle: str = "dfii10") -> SeriesResult:
    obs = tuple(Observation(date=f"2026-07-{i + 1:02d}", value=v) for i, v in enumerate(valeurs))
    return SeriesResult(series_id=cle, series=ParsedSeries(observations=obs, dropped=0))


def _provider(reponses: Optional[dict[str, SeriesResult]] = None, **kw: Any) -> MacroSeriesProvider:
    table = reponses if reponses is not None else {"dfii10": _serie(1.8, 1.9, 2.05)}

    def fetcher(cle: str) -> SeriesResult:
        if cle not in table:
            raise AssertionError(f"série NON REQUISE interrogée : {cle}")
        return table[cle]

    return MacroSeriesProvider(fetcher=fetcher, clock=lambda: T0, **kw)


# =============================================================================================
# 1. La faisabilité est DÉRIVÉE du registre, jamais déclarée
# =============================================================================================


def test_chaque_champ_BLOQUE_porte_un_motif_non_vide():
    """Quinze `None` muets se lisent comme un marché calme. Chaque refus doit dire lequel."""
    for r in RECIPES:
        b = r.blocage()
        if b is not None:
            assert len(b) > 20, (r.field, b)


def test_les_motifs_des_recettes_DIRECT_et_CASCADE_viennent_du_REGISTRE():
    """Ils ne sont pas rédigés ici : ils sont recopiés de `fetch_block_reason`, donc ils
    changeront tout seuls quand le registre changera."""
    from app.providers.connectors import fetch_block_reason

    for r in RECIPES:
        if r.kind == "SANS_FORMULE":
            continue
        b = r.blocage()
        if b is None or "jambe manquante" in b:
            continue
        cle = b.split(" — ")[0]
        registre = fetch_block_reason(cle)
        assert registre is not None and registre in b, (r.field, cle)


def test_une_recette_CASCADE_a_jambe_manquante_est_bloquee_AVANT_tout_calcul():
    """`cascade.aggregate` refuserait de toute façon — mais le dire à la lecture du registre
    évite d'interroger des séries pour un score qu'on sait déjà impossible."""
    d1 = BY_FIELD["d1"]
    b = d1.blocage()
    assert b is not None
    for orpheline in ("lei", "sahm", "ip"):
        assert orpheline in b


def test_le_pont_ne_revendique_QUE_ce_qu_il_alimente_vraiment():
    """Revendiquer un champ qu'on ne remplit pas priverait le stack démo de son mock pour rien."""
    assert set(OWNED_FIELDS) == {r.field for r in RECIPES if r.blocage() is None}
    assert OWNED_FIELDS == ("real_rates",)      # état RÉEL du registre aujourd'hui


# =============================================================================================
# 2. Discipline de quota : on n'interroge que ce qui sert
# =============================================================================================


def test_seules_les_series_d_une_recette_FAISABLE_sont_interrogees():
    """Fetcher les 53 pour n'en utiliser qu'une brûlerait le quota et noierait l'unique appel
    utile dans le bruit."""
    requises = MacroSeriesProvider.required_series()
    assert requises == ("dfii10",)
    bloquees = {k for r in RECIPES if r.blocage() is not None for k in r.keys()}
    assert not (set(requises) & bloquees)


def test_une_serie_NON_REQUISE_interrogee_fait_ECHOUER_le_test():
    """Le `fetcher` d'essai lève sur toute clé hors périmètre : c'est ce qui rend la discipline
    de quota vérifiable au lieu d'être une intention."""
    p = _provider()
    assert asyncio.run(p.refresh())            # ne lève pas → aucune série superflue demandée


# =============================================================================================
# 3. Le calcul : les formules EXISTANTES, jamais une nouvelle
# =============================================================================================


def test_real_rates_prend_la_DERNIERE_observation():
    p = _provider({"dfii10": _serie(1.8, 1.9, 2.05)})
    asyncio.run(p.refresh())
    assert p.value("real_rates", T0) == pytest.approx(2.05)


def test_une_serie_VIDE_ne_produit_AUCUNE_valeur():
    """Zéro n'est pas une absence : un taux réel à 0,0 est une mesure, pas un trou."""
    p = _provider({"dfii10": SeriesResult(series_id="DFII10", series=None,
                                          error="série inconnue")})
    bilan = asyncio.run(p.refresh())
    assert p.value("real_rates", T0) is None
    assert "série inconnue" in bilan["real_rates"]


def test_un_champ_BLOQUE_n_est_JAMAIS_calcule_ni_publie():
    p = _provider()
    bilan = asyncio.run(p.refresh())
    assert set(bilan) == {"real_rates"}
    state = FauxState()
    assert asyncio.run(p.publish(state)) == ["real_rates"]
    assert {w[0] for w in state.writes} == {"real_rates"}


def test_le_calcul_de_cascade_DELEGUE_au_module_existant():
    """Recoder ici le z-score ou le `tanh` donnerait deux définitions de la même mesure."""
    import ast
    import inspect

    from app.external import macro_series as mod
    source = inspect.getsource(mod)
    assert "math.tanh" not in source and "def zscore" not in source
    # Aucun SEUIL numérique en dur : les bornes vivent dans le registre et dans `cascade`.
    # Les contrôles d'ARITÉ (`len(...) != 1`) sont exclus — ce n'est pas un seuil de marché, et
    # ma première version du garde les attrapait, ce qui l'aurait fait désactiver plutôt
    # qu'affiner.
    def _est_arite(noeud: ast.Compare) -> bool:
        gauche = noeud.left
        return (isinstance(gauche, ast.Call) and isinstance(gauche.func, ast.Name)
                and gauche.func.id == "len")

    literaux = [c.value for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Compare) and not _est_arite(n)
                for c in [n.left, *n.comparators]
                if isinstance(c, ast.Constant) and isinstance(c.value, (int, float))
                and not isinstance(c.value, bool)]
    assert literaux == [], f"seuil numérique EN DUR dans le module : {literaux}"


# =============================================================================================
# 4. Cache, aveuglement, publication
# =============================================================================================


def test_un_cache_FOSSILE_ne_publie_RIEN():
    """Passé `max_age_s`, une valeur macro n'est plus une donnée : la republier avec un
    horodatage frais la blanchirait en mesure courante."""
    horloge = {"t": T0}
    p = MacroSeriesProvider(fetcher=lambda c: _serie(2.05), clock=lambda: horloge["t"],
                            max_age_s=100.0)
    asyncio.run(p.refresh())
    assert p.value("real_rates", horloge["t"]) is not None
    horloge["t"] += 101
    assert p.value("real_rates", horloge["t"]) is None
    state = FauxState()
    assert asyncio.run(p.publish(state)) == []


def test_un_fetch_RATE_conserve_la_valeur_precedente():
    etat = {"ok": True}

    def fetcher(cle: str) -> SeriesResult:
        if not etat["ok"]:
            raise OSError("réseau mort")
        return _serie(2.05)

    p = MacroSeriesProvider(fetcher=fetcher, clock=lambda: T0)
    asyncio.run(p.refresh())
    etat["ok"] = False
    asyncio.run(p.refresh())                     # ne lève pas
    assert p.value("real_rates", T0) == pytest.approx(2.05)


def test_une_source_qui_LEVE_est_tracee_par_serie_pas_avalee():
    def fetcher(cle: str) -> SeriesResult:
        raise RuntimeError("fournisseur cassé")

    p = MacroSeriesProvider(fetcher=fetcher, clock=lambda: T0)
    asyncio.run(p.refresh())
    etat = p.state_dict(T0)
    assert "dfii10" in etat["echecs"] and "RuntimeError" in etat["echecs"]["dfii10"]
    assert etat["alimentes"] == []


def test_la_publication_porte_la_source_macro_feed_et_son_drapeau():
    p = _provider()
    asyncio.run(p.refresh())
    state = FauxState()
    asyncio.run(p.publish(state))
    champ, valeur, source, ts, flags = state.last("real_rates")
    assert source == "macro_feed" and "MACRO_SERIES" in flags
    assert ts == pytest.approx(T0)               # horodatage d'OBSERVATION, pas `now`


# =============================================================================================
# 5. Le rapport dit ce qui est alimenté ET pourquoi le reste ne l'est pas
# =============================================================================================


def test_le_rapport_montre_chaque_champ_avec_son_motif():
    texte = rapport()
    for r in RECIPES:
        assert r.field in texte
    assert "ABSENT" in texte                     # la conséquence est dite, pas seulement le statut
    assert "C2" in texte                         # les blocages du registre remontent tels quels


def test_le_rapport_n_ouvre_AUCUNE_connexion():
    """Lecture du registre, pas interrogation des fournisseurs : il doit pouvoir tourner hors
    ligne, y compris sans aucune clé d'API."""
    import socket

    vrai = socket.socket

    def interdit(*a: Any, **k: Any) -> Any:
        raise AssertionError("le rapport a tenté d'ouvrir une socket")

    socket.socket = interdit          # type: ignore[assignment]
    try:
        assert "CHOLISMO" in rapport()
    finally:
        socket.socket = vrai          # type: ignore[assignment]


# =============================================================================================
# 6. Bout à bout : la série arrive VRAIMENT dans le ContextSchema
# =============================================================================================


def _redis_available() -> bool:
    from app.redis_state import RedisState

    async def probe() -> bool:
        state = RedisState()
        try:
            return await state.ping()
        finally:
            await state.close()
    return asyncio.run(probe())


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_une_serie_du_REGISTRE_arrive_jusque_dans_le_bloc_cascade(tmp_path):
    """Le test qui compte : registre → client → provider → Redis → moteur → `ContextSchema`,
    sans qu'`engine.py` ait été modifié d'une ligne. Le mode replay isole la démonstration —
    `tick_slow` n'y écrit rien, donc le pont est le seul producteur de `real_rates`."""
    import time

    from app.datasource.replay import ReplayDataSource
    from app.engine import Engine
    from app.redis_state import RedisState
    from app.replay.mock_data_generator import generer

    tape = tmp_path / "tape.csv"
    generer(tape, 200)

    async def scenario():   # type: ignore[no-untyped-def]
        state = RedisState()
        p = MacroSeriesProvider(fetcher=lambda c: _serie(1.92, 1.95, 2.03))
        await p.refresh()
        assert await p.publish(state) == ["real_rates"]
        engine = Engine(ReplayDataSource(str(tape), speed=50.0), state)
        await engine._assemble_slow(time.time())
        champ = engine.schema.s2_state.cascade.real_rates
        await state.close()
        return champ

    champ = asyncio.run(scenario())
    assert champ.value == pytest.approx(2.03)          # la DERNIÈRE observation
    assert champ.source == "macro_feed"
    assert "MACRO_SERIES" in champ.flags
    assert champ.freshness.value == "FRESH"


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_un_pont_MUET_laisse_le_champ_ABSENT_jamais_un_zero(tmp_path):
    """Le contrôle négatif, et la promesse §3 : sans donnée, le panneau doit afficher PAS DE
    DONNÉES. Un `real_rates` à 0,0 serait une mesure — et un taux réel nul, une information."""
    import time

    from app.datasource.replay import ReplayDataSource
    from app.engine import Engine
    from app.redis_state import RedisState
    from app.replay.mock_data_generator import generer

    tape = tmp_path / "tape.csv"
    generer(tape, 200)

    async def scenario():   # type: ignore[no-untyped-def]
        state = RedisState()
        await state._redis.delete("cholismo:raw:real_rates")     # table rase
        p = MacroSeriesProvider(fetcher=lambda c: SeriesResult(series_id="DFII10", series=None,
                                                               error="service injoignable"))
        await p.refresh()
        assert await p.publish(state) == []
        engine = Engine(ReplayDataSource(str(tape), speed=50.0), state)
        await engine._assemble_slow(time.time())
        champ = engine.schema.s2_state.cascade.real_rates
        await state.close()
        return champ

    champ = asyncio.run(scenario())
    assert champ.value is None
    assert champ.freshness.value == "ABSENT"


# =============================================================================================
# 7. /devil — ce qui aurait cassé le worker
# =============================================================================================


def test_une_recette_DIRECT_mal_formee_est_BLOQUEE_pas_un_IndexError():
    """`recette.series[0]` sur une recette vide tuerait le worker de fond, et la macro entière
    avec — pour une faute de frappe dans la table."""
    from app.external.macro_series import Recipe

    for series in ((), ("a", "b")):
        b = Recipe("essai", "DIRECT", series=series).blocage()
        assert b is not None and "mal formée" in b


def test_une_cle_API_absente_est_un_REFUS_DE_POLITIQUE_pas_une_panne_reseau():
    """Distinction D-050 tenue jusqu'ici : la confondre avec un échec réseau enverrait chercher
    un pare-feu là où il manque une variable d'environnement."""
    p = MacroSeriesProvider(clock=lambda: T0)      # aucun fetcher injecté → vrai client, sans clé
    asyncio.run(p.refresh())
    motif = p.state_dict(T0)["echecs"].get("dfii10", "")
    assert "refus de politique" in motif and "FRED_API_KEY" in motif
    assert p.value("real_rates", T0) is None       # et le champ reste ABSENT


def test_un_worker_ne_MEURT_jamais_d_une_source_bloquee():
    """Le tuer priverait la macro de tout, avec une trace de pile, là où le champ doit
    simplement rester ABSENT."""
    p = MacroSeriesProvider(clock=lambda: T0)
    for _ in range(3):
        assert asyncio.run(p.refresh()) is not None
