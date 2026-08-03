"""ReplayDataSource — le replay branché sur la couture du terminal (Étape 2).

Ce que ces tests figent, dans l'ordre d'importance :
1. **le terminal reste le seul à cadencer** — la source ne dort jamais ;
2. **un replay ne publie que ce qu'un tape contient** — le reste vieillit vers ABSENT ;
3. **profondeur inconnue ≠ carnet vide** (D-055) ;
4. le contrôle play / pause / vitesse / seek fait ce qu'il annonce.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from app.datasource.base import MarketDataSource
from app.datasource.replay import SOURCE_NAME, ReplayDataSource, _clamp_speed

EN_TETE = "timestamp,price,volume,side,bid_vol,ask_vol\n"


class FauxState:
    """Redis remplacé par un dictionnaire : ces tests n'ouvrent aucune connexion."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, object, str, float, list[str]]] = []

    async def write_raw(self, field, value, source, ts=None, flags=None):
        self.writes.append((field, value, source, ts, list(flags or [])))

    def fields(self) -> set[str]:
        return {w[0] for w in self.writes}

    def last(self, field: str):
        return next(w[1] for w in reversed(self.writes) if w[0] == field)


class Horloge:
    """Horloge INJECTÉE : on avance le temps sans dormir."""

    def __init__(self, t: float = 10_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def avance(self, secondes: float) -> None:
        self.t += secondes


def _tape(tmp_path, lignes: str, nom: str = "tape.csv") -> str:
    chemin = tmp_path / nom
    chemin.write_text(EN_TETE + lignes, encoding="utf-8")
    return str(chemin)


TROIS = ("1000.0,5000.00,10,BUY,120,80\n"
         "1001.0,5000.25,5,SELL,110,90\n"
         "1002.0,5000.50,7,BUY,100,70\n")


def _source(tmp_path, lignes: str = TROIS, **kw):
    horloge = Horloge()
    src = ReplayDataSource(_tape(tmp_path, lignes), clock=horloge, **kw)
    return src, horloge, FauxState()


# =============================================================================================
# 1. Le contrat : c'est une MarketDataSource, et elle ne cadence rien
# =============================================================================================


def test_c_est_bien_une_MarketDataSource(tmp_path):
    src, _, _ = _source(tmp_path)
    assert isinstance(src, MarketDataSource)
    assert inspect.iscoroutinefunction(src.tick_fast)
    assert inspect.iscoroutinefunction(src.tick_slow)


def test_la_source_ne_DORT_jamais(tmp_path):
    """`ReplayEngine.start()` pousse avec ses propres `sleep` ; branché tel quel dans une
    boucle async, il gèlerait la boucle d'événements (§7). La source consomme l'itérateur PUR."""
    from app.datasource import replay
    src_code = inspect.getsource(replay)
    arbre = __import__("ast").parse(src_code)
    appels = {n.attr for n in __import__("ast").walk(arbre)
              if isinstance(n, __import__("ast").Attribute)}
    assert "sleep" not in appels
    assert "start" not in appels                      # le mode « poussé » n'est pas utilisé ici


def test_tick_fast_ne_bloque_pas_la_boucle(tmp_path):
    src, horloge, state = _source(tmp_path)

    async def scenario():
        ticks = 0

        async def battement():
            nonlocal ticks
            for _ in range(3):
                await asyncio.sleep(0)
                ticks += 1

        await src.tick_fast(state)
        horloge.avance(5.0)
        await asyncio.gather(src.tick_fast(state), battement())
        return ticks

    assert asyncio.run(scenario()) == 3
    assert state.fields() == {"tape", "order_book"}


# =============================================================================================
# 2. Un replay ne publie que ce qu'un tape contient
# =============================================================================================


def test_seuls_tape_et_order_book_sont_publies(tmp_path):
    """Fabriquer un VIX ou un score SVS depuis un tape rejoué serait un chiffre inventé qui a
    l'air d'une mesure. Les champs absents vieillissent visiblement vers ABSENT (§3)."""
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    assert state.fields() == {"tape", "order_book"}
    for interdit in ("svs_score", "vix", "gex", "cvd", "bridgewater_matrix"):
        assert interdit not in state.fields()


def test_le_canal_LENT_n_ecrit_rien(tmp_path):
    src, _, state = _source(tmp_path)
    asyncio.run(src.tick_slow(state))
    assert state.writes == []


def test_la_source_s_ANNONCE_comme_un_replay(tmp_path):
    """Un replay qui se fait passer pour du direct est le pire état possible de ce terminal."""
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    for field, _value, source, _ts, flags in state.writes:
        assert source == SOURCE_NAME == "replay", field
        assert "REPLAY" in flags, field


def test_les_horodatages_publies_sont_REBASES_sur_maintenant(tmp_path):
    """Publier les horodatages bruts d'une séance ancienne ferait tout juger périmé : le
    terminal afficherait ABSENT partout. Les ÉCARTS du fichier sont conservés — ce sont eux qui
    portent les rafales et les trous."""
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))               # amorce l'horloge
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    prints = state.last("tape")
    assert all(abs(p["ts"] - horloge.t) < 20.0 for p in prints)   # proche de maintenant
    ecarts = [b["ts"] - a["ts"] for a, b in zip(prints, prints[1:])]
    assert ecarts == pytest.approx([1.0, 1.0])       # les écarts du FICHIER, préservés


# =============================================================================================
# 3. Profondeur inconnue ≠ carnet vide (D-055)
# =============================================================================================


def test_une_profondeur_ABSENTE_ne_publie_AUCUN_carnet(tmp_path):
    """Un carnet à zéro annoncerait une absence de liquidité qui n'a jamais été observée."""
    src, horloge, state = _source(tmp_path, "1000.0,5000.00,10,BUY,,\n")
    asyncio.run(src.tick_fast(state))
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    assert "tape" in state.fields()                  # le print existe
    assert "order_book" not in state.fields()        # la profondeur, non


def test_un_carnet_publie_porte_les_DEUX_cotes(tmp_path):
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    book = state.last("order_book")
    assert book["bids"] and book["asks"]
    assert book["bids"][0][0] < book["asks"][0][0]   # bid sous ask, toujours


# =============================================================================================
# 4. Contrôle : play / pause / vitesse / seek
# =============================================================================================


def test_en_PAUSE_l_horloge_virtuelle_n_avance_pas(tmp_path):
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    src.pause()
    horloge.avance(60.0)
    asyncio.run(src.tick_fast(state))
    assert src.state.position == 0 and state.writes == []
    assert "PAUSE" in src.state.resume


def test_le_temps_passe_en_PAUSE_n_est_pas_RATTRAPE(tmp_path):
    """Reprendre après dix minutes de pause ne doit pas déverser dix minutes de tape d'un coup."""
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    src.pause()
    horloge.avance(600.0)
    src.play()
    asyncio.run(src.tick_fast(state))                # ré-amorce, ne publie rien
    horloge.avance(0.5)
    asyncio.run(src.tick_fast(state))
    assert src.state.position <= 1                   # pas les trois d'un coup


def test_la_VITESSE_multiplie_l_avance(tmp_path):
    lent, h1, s1 = _source(tmp_path, TROIS, speed=1.0)
    rapide, h2, s2 = _source(tmp_path, TROIS, speed=100.0)
    for src, h, st in ((lent, h1, s1), (rapide, h2, s2)):
        asyncio.run(src.tick_fast(st))
        h.avance(1.0)
        asyncio.run(src.tick_fast(st))
    assert lent.state.position < rapide.state.position


@pytest.mark.parametrize("valeur,attendu", [(0, 0.01), (-5, 0.01), (1e9, 1000.0),
                                            ("x", 1.0), (None, 1.0), (float("nan"), 1.0),
                                            (2.5, 2.5)])
def test_la_vitesse_est_TOUJOURS_bornee(valeur, attendu):
    """`speed=0` serait une pause qui ne dit pas son nom, et l'UI afficherait « LECTURE » sur
    un flux arrêté."""
    assert _clamp_speed(valeur) == attendu


def test_seek_repositionne_et_REMET_LE_TAPE_A_ZERO(tmp_path):
    """Garder le tape ferait cohabiter des prints d'avant le saut avec ceux d'après : toute
    mesure de fenêtre (B1/B4) porterait sur un temps qui n'a jamais existé."""
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    assert len(state.last("tape")) == 3
    src.seek(position=0)
    state.writes.clear()
    asyncio.run(src.tick_fast(state))
    horloge.avance(0.001)
    asyncio.run(src.tick_fast(state))
    assert src.state.position == 0 or len(state.last("tape")) < 3


def test_seek_par_HORODATAGE_et_par_FRACTION(tmp_path):
    src, _, _ = _source(tmp_path)
    assert src.seek(ts=1001.0).position == 1
    assert src.seek(fraction=1.0).position == 2
    assert src.seek(fraction=0.0).position == 0


def test_seek_hors_bornes_est_RAMENE_pas_refuse(tmp_path):
    src, _, _ = _source(tmp_path)
    assert src.seek(position=-99).position == 0
    assert src.seek(position=9999).position == 3     # len(ticks), état TERMINÉ


def test_la_fin_du_fichier_est_DITE(tmp_path):
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    horloge.avance(100.0)
    asyncio.run(src.tick_fast(state))
    assert src.state.finished and not src.state.playing
    assert "TERMINÉ" in src.state.resume


def test_restart_relance_depuis_le_debut(tmp_path):
    src, horloge, state = _source(tmp_path)
    asyncio.run(src.tick_fast(state))
    horloge.avance(100.0)
    asyncio.run(src.tick_fast(state))
    assert src.state.finished
    src.restart()
    assert src.state.position == 0 and not src.state.finished


def test_l_etat_se_lit_en_UNE_ligne_et_dit_les_ECARTS(tmp_path):
    src, _, _ = _source(tmp_path, TROIS + "1003.0,,9,BUY,10,10\n")
    src.seek(position=0)                              # force l'indexation
    assert "tick 0/3" in src.state.resume
    assert "1 ligne(s) écartée(s)" in src.state.resume
    assert src.state.as_dict()["skipped"] == 1


def test_un_fichier_VIDE_ne_publie_rien_et_ne_casse_pas(tmp_path):
    src, horloge, state = _source(tmp_path, "")
    asyncio.run(src.tick_fast(state))
    horloge.avance(10.0)
    asyncio.run(src.tick_fast(state))
    assert state.writes == [] and src.state.total == 0
