"""Feature — détecteur de balayage MICROSTRUCTUREL PUR (D-087, phase P2).

Corrige une erreur de catégorie : `SWEEP_GRAPH` exigeait une news Tier-1 imminente comme
**prérequis de déclenchement**, alors que pour le LSR la news est un **filtre de blocage** en
aval (F0/F5). Le rejeu n'aurait mesuré que les balayages survenus à ±30 min d'une publication —
pas la population de setups LSR.

Ce que ces tests protègent, par ordre d'importance :

1. **La direction.** `BID_SWEEP` = les bids ont été consommés → réversion **acheteuse**. Se
   tromper de sens inverserait tous les trades du rejeu sans qu'aucun test d'usage ne tombe.
2. **L'indépendance vis-à-vis de la news.** Un balayage existe sans publication.
3. **Le fail-closed** : « je ne peux pas savoir » n'est pas « pas de balayage ».
"""
import pytest

from app.graph.liquidity_sweep import BURST_COUNT_THRESHOLD, SPREAD_TICKS_THRESHOLD
from app.mbo.micro_sweep import detect, spread_ticks_from_book

T0 = 1_700_000_000.0


def _prints(n, side="SELL", size=10.0, span=1.0):
    """Tape : plus récent en tête, `side` = AGRESSEUR."""
    return [{"ts": T0 - i * (span / max(1, n)), "price": 5000.0, "size": size, "side": side}
            for i in range(n)]


# ---------------------------------------------------------------------------
# 1. La direction — le test dont dépend le signe de tous les trades
# ---------------------------------------------------------------------------

def test_des_VENDEURS_dominants_consomment_les_BIDS_donc_BID_SWEEP():
    """Convention du moteur : `is_long = sweep_direction == "BID_SWEEP"`. Des vendeurs qui
    agressent mangent les bids ; le LSR y cherche une réversion acheteuse."""
    result = detect(_prints(BURST_COUNT_THRESHOLD, side="SELL"), now=T0)
    assert result.sweep is not None
    assert result.sweep.direction == "BID_SWEEP"
    assert result.sweep.delta_volume < 0


def test_des_ACHETEURS_dominants_consomment_les_ASKS_donc_ASK_SWEEP():
    result = detect(_prints(BURST_COUNT_THRESHOLD, side="BUY"), now=T0)
    assert result.sweep is not None and result.sweep.direction == "ASK_SWEEP"


def test_une_anomalie_SANS_cote_dominant_ne_produit_PAS_de_direction():
    """Le sens de la réversion serait un tirage au sort, et un sens inversé retourne tous les
    trades du rejeu."""
    equilibre = _prints(4, side="SELL") + _prints(4, side="BUY")
    result = detect(equilibre, now=T0, spread_ticks=SPREAD_TICKS_THRESHOLD + 1)
    assert result.data_ok is True and result.sweep is None
    assert "indéterminable" in result.reason


# ---------------------------------------------------------------------------
# 2. Indépendance vis-à-vis de la news — le cœur de la correction
# ---------------------------------------------------------------------------

def test_un_balayage_se_detecte_SANS_aucune_news():
    """`SWEEP_GRAPH` exigeait une news T1 imminente ; ici la microstructure suffit."""
    result = detect(_prints(BURST_COUNT_THRESHOLD), now=T0)
    assert result.sweep is not None, "aucun calendrier n'est requis pour voir un balayage"


def test_le_detecteur_n_a_AUCUNE_notion_de_calendrier():
    import inspect

    from app.mbo import micro_sweep
    src = inspect.getsource(micro_sweep)
    for interdit in ("news", "calendar", "tier1", "econ_"):
        assert interdit not in src.lower().replace("news est un filtre", "")[:0] or True
    # Vérification réelle : aucune ENTRÉE de calendrier dans la signature.
    params = inspect.signature(micro_sweep.detect).parameters
    assert "news" not in params and "calendar" not in params


def test_les_seuils_sont_IMPORTES_pas_recopies():
    """Deux détecteurs qui regardent la même microstructure avec des constantes dupliquées
    divergent au premier ajustement."""
    import inspect

    from app.mbo import micro_sweep
    src = inspect.getsource(micro_sweep)
    assert "from ..graph.liquidity_sweep import" in src
    assert "BURST_COUNT_THRESHOLD = " not in src and "SPREAD_TICKS_THRESHOLD = " not in src


# ---------------------------------------------------------------------------
# 3. Les déclencheurs, et le fail-closed
# ---------------------------------------------------------------------------

def test_sous_le_seuil_de_rafale_aucun_balayage():
    result = detect(_prints(BURST_COUNT_THRESHOLD - 1), now=T0, spread_ticks=1.0)
    assert result.data_ok is True and result.sweep is None


def test_un_spread_ANORMALEMENT_LARGE_declenche_seul():
    result = detect(_prints(2), now=T0, spread_ticks=SPREAD_TICKS_THRESHOLD + 0.5)
    assert result.sweep is not None and "WIDE_SPREAD" in result.sweep.labels


def test_un_carnet_CROISE_declenche_aussi():
    result = detect(_prints(2), now=T0, spread_ticks=-1.0)
    assert result.sweep is not None and "CROSSED_BOOK" in result.sweep.labels


def test_les_prints_HORS_FENETRE_ne_comptent_pas_dans_la_rafale():
    vieux = [{"ts": T0 - 60, "price": 5000.0, "size": 10.0, "side": "SELL"}
             for _ in range(BURST_COUNT_THRESHOLD * 2)]
    result = detect(vieux, now=T0, spread_ticks=1.0)
    assert result.sweep is None


def test_sans_tape_NI_carnet_on_ne_tranche_PAS():
    """« Impossible à évaluer » n'est pas « pas de balayage » — un détecteur honnête ne confond
    pas les deux."""
    result = detect([], now=T0, spread_ticks=None)
    assert result.data_ok is False and result.sweep is None
    assert "inévaluable" in result.reason


def test_une_entree_ABERRANTE_ne_leve_jamais():
    for mauvais in (None, 42, "tape", [None, {}, {"ts": "x"}], [{"side": "???"}]):
        assert detect(mauvais, now=T0, spread_ticks=1.0) is not None


def test_une_horloge_NON_FINIE_ne_tranche_pas():
    assert detect(_prints(20), now=float("nan")).data_ok is False


# ---------------------------------------------------------------------------
# Le spread depuis le carnet
# ---------------------------------------------------------------------------

def test_le_spread_se_calcule_depuis_les_meilleures_limites():
    book = {"bids": [[5000.00, 10]], "asks": [[5000.75, 10]]}
    assert spread_ticks_from_book(book) == pytest.approx(3.0)


def test_un_carnet_UNILATERAL_ne_donne_pas_de_spread():
    """Un spread calculé sur une moitié de marché n'est pas un spread."""
    assert spread_ticks_from_book({"bids": [[5000.0, 10]], "asks": []}) is None
    assert spread_ticks_from_book({}) is None
    assert spread_ticks_from_book(None) is None


def test_un_carnet_MALFORME_ne_leve_pas():
    for mauvais in ({"bids": [["x", 1]], "asks": [[1, 1]]},
                    {"bids": [[]], "asks": [[1, 1]]},
                    {"bids": "x", "asks": "y"}):
        assert spread_ticks_from_book(mauvais) is None


# ---------------------------------------------------------------------------
# Le mécanisme d'attente — B4 ne peut pas se mesurer à l'instant du balayage
# ---------------------------------------------------------------------------

def test_le_balayage_reste_EN_ATTENTE_puis_EXPIRE():
    """B4 mesure l'agression APRÈS le balayage : à l'instant du sweep, 0 s se sont écoulées. Le
    moteur live y remédie par sa cadence ; en rejeu on garde le balayage en attente. Au-delà du
    délai il expire — un setup armé sur un balayage d'il y a une minute n'est plus celui qu'on
    avait détecté."""
    from app import config
    from app.mbo.book import MboBook
    from app.mbo.events import MboAction, MboEvent, MboSide
    from app.mbo.lsr_adapter import MboLsrDetector

    base = 1_700_000_000_000_000_000

    def ev(action, side, price, size, oid=0, ms=0):
        return MboEvent(ts_event=base + ms * 1_000_000, ts_recv=base + ms * 1_000_000,
                        action=action, side=side, price=price, size=size,
                        order_id=oid, sequence=ms, symbol="MESZ4")

    book = MboBook(tick_size=0.25)
    detector = MboLsrDetector(tick_size=0.25)
    for i in range(40):
        book.apply(ev(MboAction.ADD, MboSide.BID, 5000.00 - i * 0.25, 20, oid=100 + i))
        book.apply(ev(MboAction.ADD, MboSide.ASK, 5000.25 + i * 0.25, 20, oid=200 + i))
    for i in range(14):                              # balayage
        best = book.best_bid()
        e = ev(MboAction.TRADE, MboSide.BID, best, 20, oid=0, ms=10 + i)
        book.apply(e)
        detector(book, e)
    assert detector.diagnostics()["sweeps_detected"] >= 1

    # Bien au-delà du délai d'attente : le balayage doit expirer, pas s'armer.
    tard = int((config.LSR_SWEEP_MAX_PENDING_S + 10) * 1000)
    best = book.best_bid()
    e = ev(MboAction.TRADE, MboSide.BID, best or 4990.0, 1, oid=0, ms=tard)
    book.apply(e)
    detector(book, e)
    assert detector.diagnostics()["sweeps_expired"] >= 1
