"""Feature — NT8FileAccountProvider : lecture async des exports de compte NinjaTrader (D-048).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- provider à DEUX étages : une boucle de rafraîchissement async (`asyncio.to_thread` — un stat/read
  bloqué par Windows/antivirus ne gèle JAMAIS l'event loop) alimente un cache `(state, mtime)` ;
  `current(now)` reste SYNC et applique la règle de fraîcheur D-047 sur le cache — le port est
  respecté à l'identique, l'engine ne change pas ;
- format v1 provisional : lignes `epoch;equity[;day_start]` APPENDÉES par l'exporteur NT8
  (un fichier par jour de session — convention côté exporteur). Dernière ligne VALIDE gagne ;
  ligne déchirée/corrompue → on remonte à la précédente ; `day_start` explicite si présent,
  sinon DÉDUIT de la première ligne valide du fichier ; floor/DLL du preset Apex (NT8 ne les
  connaît pas) ;
- horodatage = **mtime du fichier** (même horloge que `now` backend → pas de dérive inter-machines,
  et si NT8 cesse d'écrire, ACCOUNT_MAX_AGE_S s'applique naturellement) ;
- FAIL-CLOSED I/O : fichier introuvable, verrouillé, illisible, aucune ligne valide, équité
  non-finie ou ≤ 0 → None, SILENCE ABSOLU (aucune ligne de log sur un échec d'I/O attendu).
"""
import asyncio
import logging
import os
import time

from app import config
from app.account_provider import NT8FileAccountProvider
from app.risk_sizer import APEX_EOD_50K

FLOOR = APEX_EOD_50K.initial_capital - APEX_EOD_50K.max_drawdown        # 47 500


def _write(tmp_path, content, mtime=None):
    f = tmp_path / "nt8_account.csv"
    f.write_text(content)
    if mtime is not None:
        os.utime(f, (mtime, mtime))
    return str(f)


def _provider(path):
    return NT8FileAccountProvider(path, preset=APEX_EOD_50K)


def _refresh(p):
    asyncio.run(p.refresh())


# --- Parsing nominal ------------------------------------------------------------------------

def test_nominal_derniere_ligne_valide_et_day_start_deduit(tmp_path):
    now = time.time()
    path = _write(tmp_path, "1700000000;50000.0\n1700000001;49750.0\n1700000002;49500.0\n",
                  mtime=now)
    p = _provider(path)
    _refresh(p)
    acc = p.current(now)
    assert acc is not None
    assert acc.current_equity == 49_500.0                   # dernière ligne valide
    assert acc.day_start_equity == 50_000.0                 # déduit de la PREMIÈRE ligne valide
    assert acc.drawdown_floor == FLOOR                      # du preset (NT8 ne le connaît pas)
    assert acc.daily_loss_limit == APEX_EOD_50K.daily_loss_limit
    assert acc.account_type == "EOD_TRAILING"


def test_day_start_explicite_troisieme_champ(tmp_path):
    now = time.time()
    path = _write(tmp_path, "1700000000;49200.0;49800.0\n", mtime=now)
    p = _provider(path)
    _refresh(p)
    acc = p.current(now)
    assert acc is not None
    assert acc.current_equity == 49_200.0 and acc.day_start_equity == 49_800.0


def test_ecriture_dechiree_remonte_a_la_ligne_precedente(tmp_path):
    """NT8 écrit en continu : la dernière ligne peut être TRONQUÉE en plein vol."""
    now = time.time()
    path = _write(tmp_path, "1700000000;50000.0\n1700000001;49600.0\n1700000002;4"
                  , mtime=now)                               # ligne déchirée
    p = _provider(path)
    _refresh(p)
    acc = p.current(now)
    assert acc is not None and acc.current_equity == 49_600.0


def test_lignes_corrompues_ignorees_ligne_par_ligne(tmp_path):
    now = time.time()
    path = _write(tmp_path,
                  "garbage\n1700000000;50000.0\n;;;\n1700000001;nan\n1700000002;inf\n"
                  "1700000003;-500.0\n1700000004;0\n1700000005;49900.0\nBALANCE=???\n",
                  mtime=now)
    p = _provider(path)
    _refresh(p)
    acc = p.current(now)
    assert acc is not None
    assert acc.current_equity == 49_900.0                   # seule la dernière VALIDE compte
    assert acc.day_start_equity == 50_000.0                 # première VALIDE (garbage ignoré)


# --- Horodatage : mtime, la règle D-047 s'applique naturellement -----------------------------

def test_mtime_perime_nt8_a_cesse_d_ecrire(tmp_path):
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now - config.ACCOUNT_MAX_AGE_S - 5)
    p = _provider(path)
    _refresh(p)
    assert p.current(now) is None                           # équité fossile → à l'aveugle → non


def test_mtime_frais_puis_vieillit_sans_nouvelle_ecriture(tmp_path):
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now)
    p = _provider(path)
    _refresh(p)
    assert p.current(now + 1) is not None
    assert p.current(now + config.ACCOUNT_MAX_AGE_S + 1) is None   # le cache VIEILLIT, refresh ou pas


def test_un_refresh_rate_ne_ressuscite_pas_un_vieux_cache(tmp_path):
    """Le fichier disparaît (rotation NT8) : le refresh échoue, le cache précédent reste mais
    VIEILLIT par son mtime — jamais re-timbré au présent."""
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now - 10)
    p = _provider(path)
    _refresh(p)
    assert p.current(now) is not None                       # frais (10 s < 15 s)
    os.remove(path)
    _refresh(p)                                             # échec d'I/O silencieux
    assert p.current(now + 10) is None                      # 20 s > max_age : mort, pas ressuscité


# --- Fail-closed I/O : silence ABSOLU --------------------------------------------------------

def test_fichier_introuvable_none_silencieux(tmp_path, caplog):
    p = _provider(str(tmp_path / "n_existe_pas.csv"))
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        _refresh(p)
        assert p.current(time.time()) is None
        assert [r for r in caplog.records if r.name.startswith("cholismo")] == []   # silence absolu


def test_chemin_verrouille_none_silencieux(tmp_path, caplog):
    """Un répertoire à la place d'un fichier = open() lève OSError — même famille qu'un verrou
    exclusif Windows/antivirus : attrapé, silencieux."""
    p = _provider(str(tmp_path))                            # c'est un RÉPERTOIRE
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        _refresh(p)
        assert p.current(time.time()) is None
        assert [r for r in caplog.records if r.name.startswith("cholismo")] == []


def test_fichier_vide_ou_sans_ligne_valide_none(tmp_path, caplog):
    now = time.time()
    for content in ("", "\n\n", "garbage\nBALANCE=???\n", "1700000000;nan\n"):
        path = _write(tmp_path, content, mtime=now)
        p = _provider(path)
        with caplog.at_level(logging.DEBUG):
            caplog.clear()
            _refresh(p)
            assert p.current(now) is None, repr(content)
            assert [r for r in caplog.records if r.name.startswith("cholismo")] == []


# --- L'event loop ne gèle JAMAIS -------------------------------------------------------------

def test_lecture_lente_ne_gele_pas_l_event_loop(tmp_path, monkeypatch):
    """Antivirus/verrou Windows : la lecture BLOQUE 300 ms. Un ticker concurrent sur le même
    event loop doit continuer à tourner pendant le refresh — preuve du to_thread."""
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now)
    p = _provider(path)
    real_read = p._read_file

    def slow_read():
        time.sleep(0.3)                                     # blocage façon antivirus
        return real_read()
    monkeypatch.setattr(p, "_read_file", slow_read)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)
        t = asyncio.ensure_future(ticker())
        await p.refresh()                                   # 300 ms de lecture BLOQUANTE
        t.cancel()
        return ticks
    ticks = asyncio.run(scenario())
    assert ticks >= 15                                      # loop resté vivant (~30 ticks attendus)
    assert p.current(now) is not None                       # et la lecture a abouti


# --- Conformité au port D-047 : l'engine émet avec l'équité du FICHIER -----------------------

def test_port_d047_emission_dimensionnee_par_le_fichier(tmp_path):
    """Intégration complète : équité 49 500 lue du fichier → buffer 500 → risque 100 $ →
    stop 3 ticks (3.75 $) → 26 contrats dans le manifeste émis."""
    from tests.test_account_provider import _drain_manifests, _run

    now = time.time()
    path = _write(tmp_path, "1700000000;50000.0\n1700000001;49500.0\n", mtime=now)
    p = _provider(path)
    _refresh(p)
    manifests = _run(p)
    assert len(manifests) == 1
    assert manifests[0]["risk"]["positionSize"] == 26
    assert _drain_manifests is not None                     # (import utilisé)
