"""Feature — positionnement Long/Short agrégé (D-053 tranche 1), bloc `long_short_ratio`.

Le module ne produit AUCUN signal : il normalise un flux de positionnement brut (venue retail,
COT…) et refuse tout ce qui n'est pas exploitable. Les tests décrivent d'abord ce qui doit être
REJETÉ — c'est là qu'un panneau ment (§3 « no signal without data »).
"""
import math
import time

from app import config
from app.sentiment import build_long_short


def _raw(rows, venue="retail_ssi"):
    return {"venue": venue, "rows": rows}


def _row(symbol="EURUSD", long_pct=60.0, short_pct=40.0, **over):
    row = {"symbol": symbol, "long_pct": long_pct, "short_pct": short_pct,
           "delta_24h_pct": 1.5, "accounts": 12_000}
    row.update(over)
    return row


# --- nominal ---------------------------------------------------------------------------------

def test_valeur_nominale_ratio_et_venue():
    out = build_long_short(_raw([_row()]))
    assert out["venue"] == "retail_ssi" and out["dropped"] == 0
    inst = out["instruments"][0]
    assert inst["symbol"] == "EURUSD"
    assert (inst["long_pct"], inst["short_pct"]) == (60.0, 40.0)
    assert inst["ratio"] == 1.5                              # 60 / 40
    assert inst["delta_24h_pct"] == 1.5


def test_desequilibre_marque_au_dela_du_seuil():
    """Fait observable, pas interprétation : « ≥ seuil d'un côté ». Aucun signal contrarien
    n'est déduit ici — le terminal montre la donnée, l'opérateur décide (§2.1)."""
    over = config.SENTIMENT_EXTREME_PCT + 1.0
    out = build_long_short(_raw([_row(long_pct=over, short_pct=100.0 - over),
                                 _row(symbol="ES", long_pct=55.0, short_pct=45.0)]))
    # Repérage par SYMBOLE, pas par position : l'ordre d'affichage est trié (/devil), et un test
    # qui dépend de la position casserait au moindre changement de tri sans rien prouver de plus.
    by_symbol = {i["symbol"]: i for i in out["instruments"]}
    assert by_symbol["EURUSD"]["imbalanced"] is True
    assert by_symbol["ES"]["imbalanced"] is False


def test_desequilibre_cote_SHORT_aussi():
    over = config.SENTIMENT_EXTREME_PCT + 2.0
    out = build_long_short(_raw([_row(long_pct=100.0 - over, short_pct=over)]))
    assert out["instruments"][0]["imbalanced"] is True


# --- rejets : c'est ici qu'un panneau ment ----------------------------------------------------

def test_pourcentages_qui_ne_totalisent_pas_100_rejetes():
    """60/30 : la venue a perdu une catégorie. Afficher la jauge reviendrait à inventer les 10 %
    manquants."""
    out = build_long_short(_raw([_row(long_pct=60.0, short_pct=30.0), _row(symbol="ES")]))
    assert [i["symbol"] for i in out["instruments"]] == ["ES"]
    assert out["dropped"] == 1                               # écart SIGNALÉ, pas silencieux


def test_tolerance_d_arrondi_de_venue_acceptee():
    """59,7 + 40,2 = 99,9 : arrondi de venue, pas une donnée cassée."""
    out = build_long_short(_raw([_row(long_pct=59.7, short_pct=40.2)]))
    assert out["instruments"] and out["dropped"] == 0


def test_valeurs_non_finies_ou_hors_bornes_rejetees():
    for bad in ({"long_pct": math.nan}, {"short_pct": math.inf}, {"long_pct": -5.0},
                {"long_pct": 140.0}, {"long_pct": "60"}, {"short_pct": None}):
        out = build_long_short(_raw([_row(**bad)]))
        assert out is None, bad                              # rien d'exploitable → bloc ABSENT


def test_symbole_manquant_ou_vide_rejete():
    for bad in ({"symbol": ""}, {"symbol": None}, {"symbol": 42}):
        assert build_long_short(_raw([_row(**bad)])) is None, bad


def test_short_a_zero_garde_la_ligne_mais_PAS_de_ratio_infini():
    """Tout le monde long : les pourcentages sont une donnée réelle, le ratio ne l'est plus.
    On garde la jauge, on retire le ratio — jamais « ∞ » ni un nombre géant inventé."""
    out = build_long_short(_raw([_row(long_pct=100.0, short_pct=0.0)]))
    inst = out["instruments"][0]
    assert inst["long_pct"] == 100.0 and inst["ratio"] is None


def test_delta_24h_non_fini_retire_sans_perdre_la_ligne():
    out = build_long_short(_raw([_row(delta_24h_pct=math.nan)]))
    assert out["instruments"][0]["delta_24h_pct"] is None
    assert out["instruments"][0]["long_pct"] == 60.0         # le reste survit


def test_doublon_de_symbole_ecarte():
    """Deux lignes contradictoires pour le même instrument : on garde la PREMIÈRE et on compte
    l'écart — choisir « la plus favorable » serait un mensonge silencieux."""
    out = build_long_short(_raw([_row(), _row(long_pct=20.0, short_pct=80.0)]))
    assert len(out["instruments"]) == 1 and out["instruments"][0]["long_pct"] == 60.0
    assert out["dropped"] == 1


def test_ordre_des_lignes_DETERMINISTE_quel_que_soit_le_flux():
    """/devil : une venue qui réordonne ses lignes à chaque rafraîchissement ferait SAUTER les
    instruments d'un tick à l'autre — impossible de verrouiller l'œil sur une ligne en séance.
    L'ordre d'affichage ne doit dépendre que du contenu, jamais de l'ordre d'arrivée."""
    forward = build_long_short(_raw([_row(symbol="EURUSD"), _row(symbol="ES"), _row(symbol="NQ")]))
    shuffled = build_long_short(_raw([_row(symbol="NQ"), _row(symbol="EURUSD"), _row(symbol="ES")]))
    assert [i["symbol"] for i in forward["instruments"]] == \
           [i["symbol"] for i in shuffled["instruments"]]
    assert [i["symbol"] for i in forward["instruments"]] == ["ES", "EURUSD", "NQ"]


def test_le_doublon_ecarte_reste_le_SECOND_arrive_meme_apres_tri():
    """Le tri est un choix d'AFFICHAGE : il ne doit pas changer QUELLE ligne gagne. La première
    arrivée reste la bonne, sinon un doublon pourrait renverser la valeur retenue."""
    out = build_long_short(_raw([_row(long_pct=60.0, short_pct=40.0),
                                 _row(long_pct=20.0, short_pct=80.0)]))
    assert out["instruments"][0]["long_pct"] == 60.0 and out["dropped"] == 1


# --- structure & flux obèse -------------------------------------------------------------------

def test_structures_inexploitables_rejetees():
    for bad in (None, [], {}, {"venue": "x"}, {"rows": "EURUSD"}, {"rows": [1, 2]}, "rows", 42):
        assert build_long_short(bad) is None, bad


def test_flux_obese_rejete_ENTIEREMENT():
    """Doctrine D-050 : un flux obèse est un flux empoisonné. Tronquer masquerait des
    instruments sans le dire — on refuse le lot entier, le bloc passe ABSENT."""
    rows = [_row(symbol=f"SYM{i}") for i in range(config.SENTIMENT_MAX_ROWS + 1)]
    assert build_long_short(_raw(rows)) is None
    ok = build_long_short(_raw(rows[:config.SENTIMENT_MAX_ROWS]))
    assert len(ok["instruments"]) == config.SENTIMENT_MAX_ROWS


def test_venue_absente_ou_douteuse_reste_lisible():
    out = build_long_short({"rows": [_row()]})
    assert out["venue"] == "?"                               # jamais d'invention, jamais de crash


def test_toutes_les_lignes_rejetees_rend_None():
    """Un objet avec zéro instrument s'afficherait comme « connecté mais vide » : trompeur.
    Rien d'exploitable = bloc ABSENT."""
    assert build_long_short(_raw([_row(long_pct=60.0, short_pct=10.0)])) is None


def test_fonction_PURE_aucune_lecture_d_horloge():
    """Discipline commune D-045/047/050/052 : ce module ne lit jamais l'heure."""
    import inspect

    from app import sentiment
    src = inspect.getsource(sentiment)
    for banned in ("time.time", "datetime", "perf_counter", "monotonic"):
        assert banned not in src, banned


# --- intégration : le bloc arrive-t-il RÉELLEMENT jusqu'au flux SSE ? -------------------------
# (leçon D-051 : un bloc peut être construit côté moteur et jeté en silence côté transport)

import asyncio  # noqa: E402

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
    """Un bloc absent de la liste ne serait jamais poussé — panneau fail-closed sans cause."""
    assert "long_short_ratio" in SLOW_BLOCKS
    assert hasattr(ContextSchema(), "long_short_ratio")


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_moteur_publie_le_bloc_et_le_normalise():
    async def scenario():
        state = RedisState()
        try:
            await state.set_scenario({"name": "calme", "force_session": "OVERLAP_NY"})
            await state.set_source_up("sentiment_feed", True)
            engine = Engine(MockDataSource(), state)
            published = []
            for _ in range(6):
                await engine.ds.tick_slow(state)
                await engine._assemble_slow(time.time())
                block = engine.schema.long_short_ratio
                if block.freshness == Freshness.FRESH and block.value:
                    published.append(block)
                    break
            assert published, "le bloc n'est jamais devenu FRESH"
            value = published[0].value
            assert value["venue"] and isinstance(value["instruments"], list)
            symbols = [i["symbol"] for i in value["instruments"]]
            assert "EURUSD" in symbols and len(symbols) == len(set(symbols))
            for inst in value["instruments"]:
                assert abs(inst["long_pct"] + inst["short_pct"] - 100.0) <= 0.5
        finally:
            await state.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not _redis_available(), reason="Redis indisponible — intégration sautée")
def test_lot_inexploitable_rend_le_bloc_ABSENT_et_non_vide():
    """Une venue qui ne renvoie que des lignes cassées : le bloc doit tomber à `value=None`
    (→ PAS DE DONNÉES à l'écran), jamais un objet vide qui se lit « connecté »."""
    async def scenario():
        state = RedisState()
        try:
            await state.set_source_up("sentiment_feed", True)
            engine = Engine(MockDataSource(), state)
            await state.write_raw("long_short", {"venue": "cassée",
                                                 "rows": [{"symbol": "EURUSD",
                                                           "long_pct": 60.0, "short_pct": 10.0}]},
                                  "sentiment_feed", ts=time.time(), flags=[])
            await engine._assemble_slow(time.time())
            assert engine.schema.long_short_ratio.value is None
        finally:
            await state.close()
    asyncio.run(scenario())
