"""Feature — L3 `o5.kurtosis` : barres ES 1 min + déport du calcul (D-077).

O5 consomme des barres `{timestamp, close}`. Personne ne les produisait : le footprint agrège
bien par bougie, mais son tampon est borné à `FOOTPRINT_MAX_PRINTS` prints — de quoi couvrir
quelques minutes, là où O5 en réclame 121. Une fenêtre de deux heures ne se reconstruit pas
depuis un tampon de prints ; elle **s'accumule**.

`EsBarAggregator` échantillonne donc le dernier print observé et clôt une barre à chaque
frontière de minute. Trois choix qui méritent leur justification, tous testés ici :

1. **La largeur de barre est INDÉPENDANTE de `FOOTPRINT_CANDLE_SECONDS`.** Ce réglage-là pilote
   un affichage et peut passer en mode tick (`FOOTPRINT_TICKS_PER_CANDLE`). Adosser une mesure
   de risque à un réglage d'affichage, c'est accepter qu'un changement de vue modifie le
   kurtosis sans que personne ne fasse le lien.
2. **Seules les barres CLOSES entrent dans le tampon.** La bougie en formation a une clôture
   mouvante ; `push_bar` rejetant les doublons d'horodatage, la première valeur partielle
   serait **gelée** comme clôture définitive de la minute.
3. **Tape non FRESH → aucune observation.** Répéter le dernier prix connu fabriquerait des
   rendements nuls : une série calme inventée, donc un kurtosis rassurant sur des données qui
   n'existent pas (§3).
"""
import asyncio

import pytest

from app import config
from app.es_bars import EsBarAggregator, last_trade_price
from app.meta import Freshness


def _tape(price, freshness=Freshness.FRESH, ts=1_000.0):
    """Miroir du dump d'un `MetaField` portant le tape (plus récent en tête)."""
    return {"value": [{"ts": ts, "price": price, "size": 1, "side": "BUY", "seq": 1}],
            "last_update_ts": ts, "source": "bookmap", "freshness": freshness.value,
            "flags": []}


# ---------------------------------------------------------------------------
# Extraction du dernier prix — fail-closed sur tout ce qui n'est pas une mesure
# ---------------------------------------------------------------------------

def test_dernier_prix_lu_en_tete_du_tape():
    assert last_trade_price(_tape(6001.25)) == 6001.25


def test_tape_NON_FRESH_ne_donne_AUCUN_prix():
    """Un tape périmé qu'on relaierait quand même fabriquerait des rendements nuls."""
    for f in (Freshness.STALE, Freshness.ABSENT):
        assert last_trade_price(_tape(6001.25, f)) is None


def test_tape_vide_absent_ou_malforme_ne_donne_aucun_prix():
    assert last_trade_price(None) is None
    assert last_trade_price({"value": [], "freshness": "FRESH"}) is None
    assert last_trade_price({"value": "pas une liste", "freshness": "FRESH"}) is None
    assert last_trade_price({"value": [{"price": None}], "freshness": "FRESH"}) is None
    assert last_trade_price({"value": [{"price": float("nan")}], "freshness": "FRESH"}) is None
    assert last_trade_price({"value": [{"price": -1.0}], "freshness": "FRESH"}) is None


# ---------------------------------------------------------------------------
# Agrégation : la barre ne se ferme qu'au passage de minute
# ---------------------------------------------------------------------------

def test_aucune_barre_avant_le_passage_de_minute():
    agg = EsBarAggregator(bar_seconds=60)
    for i in range(10):
        assert agg.observe(6000.0 + i, 1_000_000.0 + i) is False
    assert agg.bars == (), "la bougie en formation n'entre pas dans le tampon"


def test_la_barre_close_porte_le_DERNIER_prix_de_la_minute():
    agg = EsBarAggregator(bar_seconds=60)
    base = 1_000_020.0                                  # milieu du bucket 1_000_000
    agg.observe(6000.0, base)
    agg.observe(6005.0, base + 10)
    agg.observe(6003.0, base + 20)                      # dernier de la minute
    assert agg.observe(6100.0, base + 60) is True       # minute suivante -> clôture
    assert len(agg.bars) == 1
    assert agg.bars[0]["close"] == 6003.0


def test_l_horodatage_de_la_barre_est_la_FIN_du_bucket_en_millisecondes():
    """En ms parce que O5 raisonne en ms (`max_bar_gap_ms`). Mélanger les unités ici ferait
    passer chaque barre pour un trou temporel."""
    agg = EsBarAggregator(bar_seconds=60)
    agg.observe(6000.0, 1_000_020.0)                    # 1_000_020 est un multiple de 60
    agg.observe(6100.0, 1_000_080.0)                    # bucket suivant -> clôture
    assert agg.bars[0]["timestamp"] == 1_000_080.0 * 1000


def test_une_minute_SANS_print_ne_fabrique_pas_de_barre():
    """Le trou reste un trou : c'est `has_temporal_gap` qui doit le voir, pas nous qui le
    comblons avec le dernier prix connu."""
    agg = EsBarAggregator(bar_seconds=60)
    agg.observe(6000.0, 1_000_020.0)
    agg.observe(6100.0, 1_000_200.0)                    # 3 minutes plus tard
    assert len(agg.bars) == 1, "une seule barre close, pas trois"
    assert agg.bars[0]["close"] == 6000.0


def test_le_trou_reste_DETECTABLE_par_O5():
    from app.o5_tail_risk import evaluate_o5, config_with
    agg = EsBarAggregator(bar_seconds=60)
    t = 1_000_020.0
    for i in range(40):
        agg.observe(6000.0 + (i % 5), t)
        t += 60 if i != 20 else 300                     # un trou de 5 min au milieu
    r = evaluate_o5(list(agg.bars), config_with(min_samples=5))
    assert r["status"] == "O5_DATA_GAP"


def test_horloge_qui_RECULE_ne_corrompt_pas_le_tampon():
    """`push_bar` rejette l'hors-ordre ; on vérifie que l'agrégateur ne contourne pas la
    protection en écrivant directement dans le tampon."""
    agg = EsBarAggregator(bar_seconds=60)
    agg.observe(6000.0, 1_000_020.0)
    agg.observe(6100.0, 1_000_080.0)                    # clôture bucket 1_000_000
    avant = agg.bars
    agg.observe(5900.0, 900_000.0)                      # saut NTP arrière
    agg.observe(5901.0, 900_060.0)
    assert agg.bars == avant, "aucune barre antérieure ne s'insère après coup"


def test_prix_non_fini_est_ignore_sans_casser_la_barre_en_cours():
    agg = EsBarAggregator(bar_seconds=60)
    agg.observe(6000.0, 1_000_020.0)
    assert agg.observe(float("nan"), 1_000_030.0) is False
    agg.observe(6100.0, 1_000_080.0)
    assert agg.bars[0]["close"] == 6000.0, "le NaN n'a pas remplacé la clôture"


def test_le_tampon_est_BORNE_a_la_fenetre_utile():
    """Sans borne, une session de 8 h accumulerait 480 barres pour une fenêtre qui en lit 121 —
    une fuite lente, le piège nommé dans RUNTIME_LOOPS Loop D."""
    agg = EsBarAggregator(bar_seconds=60, max_bars=121)
    t = 1_000_020.0
    for i in range(400):
        agg.observe(6000.0 + (i % 7), t)
        t += 60
    assert len(agg.bars) == 121


def test_l_agregateur_ne_leve_jamais_sur_une_entree_absurde():
    agg = EsBarAggregator(bar_seconds=60)
    for prix, ts in ((None, 1.0), ("x", 1.0), (6000.0, None), (6000.0, "x"), (0.0, 1.0)):
        assert agg.observe(prix, ts) is False


# ---------------------------------------------------------------------------
# Le déport — la raison d'être de L3
# ---------------------------------------------------------------------------

def test_le_calcul_O5_est_DEPORTE_hors_de_la_boucle():
    """Le kurtosis est du CPU SYNCHRONE : exécuté dans la boucle d'événements, il la gèle avant
    tout point d'attente (piège Python en tête de RUNTIME_LOOPS). On vérifie que le tick
    n'exécute pas `evaluate_o5` sur le fil de la boucle."""
    from app.loops.wiring import build_o5_tick

    agg = EsBarAggregator(bar_seconds=60)
    fils = []

    def _spy_evaluate(bars, cfg, now_ms):
        import threading
        fils.append(threading.current_thread().name)
        return {"status": "PASS", "excess_kurtosis": 0.1, "sample_size": len(bars),
                "timestamp": now_ms, "skewness": 0.0, "variance": 1.0,
                "dominant_residual_share": 0.0, "config_used": {}}

    published = []

    class _B:
        def publish(self, channel, event, payload, replay=True):
            published.append((channel, event, payload))

    now = {"t": 1_000_020.0}
    tick = build_o5_tick(lambda: _tape(6000.0), agg, _B(),
                         clock=lambda: now["t"], evaluate=_spy_evaluate)

    async def scenario():
        await tick()                                    # établit le bucket, rien ne clôt
        now["t"] = 1_000_080.0
        await tick()                                    # frontière franchie -> clôture

    asyncio.run(scenario())
    import threading
    assert fils, "evaluate_o5 n'a jamais été appelé"
    assert all(f != threading.main_thread().name for f in fils), \
        f"le calcul a tourné sur le fil principal ({fils})"
    assert published and published[0][1] == "o5_tail_risk"
    assert published[0][0] == "options"


def test_le_tick_ne_recalcule_QUE_sur_cloture_de_barre():
    """Recalculer à chaque échantillon serait 12 fois le travail pour la même réponse."""
    from app.loops.wiring import build_o5_tick
    agg = EsBarAggregator(bar_seconds=60)
    appels = []
    now = {"t": 1_000_020.0}

    def _spy(bars, cfg, now_ms):
        appels.append(1)
        return {"status": "PASS", "excess_kurtosis": 0.0, "sample_size": 0, "timestamp": now_ms,
                "skewness": None, "variance": None, "dominant_residual_share": None,
                "config_used": {}}

    class _B:
        def publish(self, *a, **k): pass

    tick = build_o5_tick(lambda: _tape(6000.0), agg, _B(),
                         clock=lambda: now["t"], evaluate=_spy)

    async def scenario():
        for _ in range(5):
            await tick()
            now["t"] += 5                               # échantillons dans la MÊME minute
        assert appels == [], "aucune barre close, aucun calcul"
        now["t"] = 1_000_080.0
        await tick()
        assert len(appels) == 1

    asyncio.run(scenario())


def test_tape_mort_le_tick_LEVE_pour_que_la_boucle_le_voie():
    """Sans levée, L3 battrait `RUNNING` en n'observant rien — le mensonge que D-073 empêche."""
    from app.loops.wiring import build_o5_tick
    from app.es_bars import EsBarsUnavailable

    class _B:
        def publish(self, *a, **k): pass

    tick = build_o5_tick(lambda: _tape(6000.0, Freshness.ABSENT), EsBarAggregator(), _B(),
                         clock=lambda: 1_000_000.0)
    with pytest.raises(EsBarsUnavailable):
        asyncio.run(tick())


def test_la_largeur_de_barre_ne_depend_PAS_du_reglage_footprint():
    """Adosser une mesure de risque a un reglage d'affichage, c'est accepter qu'un changement de
    vue modifie le kurtosis sans que personne ne fasse le lien."""
    import inspect
    src = inspect.getsource(__import__("app.es_bars", fromlist=["x"]))
    # On cherche un USAGE (`config.FOOTPRINT_…`), pas une mention : la docstring explique
    # justement pourquoi le module ne s'y adosse pas, et cette explication doit rester lisible.
    assert "config.FOOTPRINT" not in src
    assert config.O5_BAR_PERIOD_SECONDS == 60.0


def test_la_spec_L3_declare_la_cadence_d_ECHANTILLONNAGE_pas_la_largeur_de_barre():
    """Une L3 cadencée à 60 s verrait chaque bucket une fois : la moindre gigue de boucle
    sauterait une minute et fabriquerait un faux `O5_DATA_GAP`. On échantillonne plus vite que
    la barre, et on ne calcule qu'à la clôture."""
    from app.loops.registry import O5_KURTOSIS
    assert O5_KURTOSIS.period_s == config.O5_SAMPLE_PERIOD_SECONDS
    assert O5_KURTOSIS.period_s < config.O5_BAR_PERIOD_SECONDS
    assert O5_KURTOSIS.heartbeat_stale_s > O5_KURTOSIS.period_s


# ---------------------------------------------------------------------------
# Régression — le chemin d'accès au tape, verrouillé sur la VRAIE projection
# ---------------------------------------------------------------------------

def test_le_chemin_du_tape_est_verrouille_sur_la_projection_REELLE_du_moteur():
    """Régression (D-077), trouvée à l'essai réel et invisible en test unitaire.

    La première version lisait `snapshot()["s1_state"]["tape"]` — or `Engine.snapshot()`
    enveloppe le schéma sous la clé `schema`. Le `except Exception` qui entourait l'accès a
    transformé un chemin faux en `tape_not_fresh` : L3 a échoué 58 fois de suite en accusant le
    feed. **Un filet trop large ne protège pas, il déguise.**

    Ce test construit la projection depuis le VRAI modèle Pydantic plutôt que depuis un dict
    écrit à la main — un dict fabriqué se serait contenté de refléter ma propre erreur."""
    from app.main import _tape_field
    from app.meta import MetaField
    from app.schema import ContextSchema

    schema = ContextSchema()
    schema.s1_state.tape = MetaField(
        value=[{"ts": 1_000.0, "price": 5453.0, "size": 1.0, "side": "BUY", "seq": 455}],
        last_update_ts=1_000.0, source="bookmap", freshness=Freshness.FRESH)

    class _Engine:
        def snapshot(self):
            return {"schema": schema.model_dump(mode="json"), "extras": {}}

    field = _tape_field(_Engine())
    assert field is not None, "le chemin d'accès au tape a changé"
    assert last_trade_price(field) == 5453.0


def test_le_chemin_du_tape_rend_None_sans_masquer_par_un_except_fourre_tout():
    """Une projection malformée rend `None` (fail-closed), mais l'accès n'est plus enveloppé
    d'un `except Exception` : une erreur de programmation doit remonter, pas se déguiser en
    absence de donnée."""
    import inspect

    from app import main
    src = inspect.getsource(main._tape_field)
    assert "except Exception" not in src

    class _Vide:
        def snapshot(self):
            return {"extras": {}}

    assert main._tape_field(_Vide()) is None
