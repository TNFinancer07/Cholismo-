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


# --- /devil D-048 : pathologies de fichiers et de FS ----------------------------------------

def test_devil_troncature_a_zero_puis_reprise(tmp_path):
    """Rotation NT8 : fichier tronqué à 0 octet → l'ancien cache reste mais VIEILLIT ;
    reprise des écritures → le provider repart sans intervention."""
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now - 10)
    p = _provider(path)
    _refresh(p)
    assert p.current(now) is not None
    _write(tmp_path, "", mtime=now)                         # troncature à 0
    _refresh(p)                                             # aucune ligne valide → cache intact
    assert p.current(now) is not None                       # (mtime d'origine, encore frais)
    assert p.current(now + 10) is None                      # …et il meurt à son échéance
    _write(tmp_path, "1700000100;49800.0\n", mtime=now + 12)   # reprise (nouveau jour)
    _refresh(p)
    acc = p.current(now + 13)
    assert acc is not None and acc.current_equity == 49_800.0


def test_devil_suppression_au_moment_precis_de_l_io(tmp_path, monkeypatch, caplog):
    """Le fichier disparaît ENTRE le stat et l'open (fenêtre de course réelle) :
    OSError attrapée, silence absolu, aucune exception non gérée."""
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now)
    p = _provider(path)
    real_open = open

    def open_gone(*a, **k):
        raise FileNotFoundError("supprimé entre stat et open")
    monkeypatch.setattr("builtins.open", open_gone)
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        _refresh(p)                                         # ne lève pas
        assert [r for r in caplog.records if r.name.startswith("cholismo")] == []
    monkeypatch.setattr("builtins.open", real_open)
    assert p.current(now) is None                           # jamais de snapshot fabriqué


def test_devil_mtime_dans_le_futur_jamais_infiniment_frais(tmp_path):
    now = time.time()
    path = _write(tmp_path, "1700000000;49500.0\n", mtime=now + 3600)
    p = _provider(path)
    _refresh(p)
    assert p.current(now) is None                           # fantôme → à l'aveugle → non


def test_devil_bom_utf8_n_avale_pas_la_premiere_ligne(tmp_path):
    """BOM UTF-8 en tête : sans strip, la PREMIÈRE ligne (celle du day_start déduit) devient
    invalide → day_start faux. Le BOM doit être ignoré."""
    now = time.time()
    f = tmp_path / "nt8_account.csv"
    f.write_bytes("﻿1700000000;50000.0\n1700000001;49500.0\n".encode("utf-8"))
    os.utime(f, (now, now))
    p = _provider(str(f))
    _refresh(p)
    acc = p.current(now)
    assert acc is not None
    assert acc.current_equity == 49_500.0
    assert acc.day_start_equity == 50_000.0                 # la ligne BOM COMPTE pour le day_start


def test_devil_utf16_et_octets_nuls_fail_closed(tmp_path, caplog):
    now = time.time()
    f = tmp_path / "nt8_account.csv"
    f.write_bytes("1700000000;50000.0\n".encode("utf-16"))  # UTF-16 = déchets en utf-8
    os.utime(f, (now, now))
    p = _provider(str(f))
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        _refresh(p)
        assert p.current(now) is None                       # non supporté → None, pas un crash
        assert [r for r in caplog.records if r.name.startswith("cholismo")] == []
    f.write_bytes(b"1700000000;50\x00000.0\n1700000001;49500.0\n")   # octet nul dans l'équité
    os.utime(f, (now, now))
    p2 = _provider(str(f))
    _refresh(p2)
    acc = p2.current(now)
    assert acc is not None and acc.current_equity == 49_500.0        # ligne \x00 écartée


def test_devil_flood_10mo_borne_memoire_et_cpu(tmp_path):
    """Ligne géante de 10 Mo : la lecture doit être FENÊTRÉE (tête + queue bornées), jamais un
    readlines() du fichier entier — préservation mémoire ET vitesse de boucle."""
    now = time.time()
    f = tmp_path / "nt8_account.csv"
    with open(f, "w") as fh:
        fh.write("1700000000;50000.0\n")                    # tête valide (day_start)
        fh.write("X" * 10_000_000 + "\n")                   # flood 10 Mo, une seule ligne
        fh.write("1700000900;49500.0\n")                    # queue valide (dernière)
    os.utime(f, (now, now))
    p = _provider(str(f))
    t0 = time.perf_counter()
    _refresh(p)
    elapsed = time.perf_counter() - t0
    acc = p.current(now)
    assert acc is not None
    assert acc.current_equity == 49_500.0                   # la queue gagne
    assert acc.day_start_equity == 50_000.0                 # la tête donne le day_start
    assert elapsed < 0.5                                    # borné, pas un scan de 10 Mo par poll


def test_devil_fenetre_bornee_queue_illisible_fail_closed(tmp_path):
    """La PREUVE du fenêtrage : sur un gros fichier dont la QUEUE (fenêtre de lecture) ne
    contient aucune ligne valide, l'état récent du compte est illisible → None — jamais une
    vieille équité du MILIEU du fichier repêchée comme si elle était récente."""
    now = time.time()
    f = tmp_path / "nt8_account.csv"
    with open(f, "w") as fh:
        fh.write("1700000000;50000.0\n")                    # tête valide
        fh.write("1700000001;49700.0\n")                    # valide, mais hors fenêtre de queue
        fh.write("Y" * 300_000 + "\n")                      # 300 Ko de déchets EN QUEUE
    os.utime(f, (now, now))
    p = _provider(str(f))
    _refresh(p)
    assert p.current(now) is None                           # le récent est illisible → à l'aveugle → non


def test_devil_day_start_indeterminable_fail_closed(tmp_path):
    """Gros fichier dont la TÊTE (fenêtre du day_start) est illisible et sans day_start
    explicite : un day_start inventé (= équité courante) simulerait un JOUR NEUF — le DLL
    repartirait plein, la corruption deviendrait du levier. → None."""
    now = time.time()
    f = tmp_path / "nt8_account.csv"
    with open(f, "w") as fh:
        fh.write("Z" * 100_000 + "\n")                      # 100 Ko de déchets EN TÊTE
        fh.write("1700000900;49500.0\n")                    # queue valide mais sans day_start
    os.utime(f, (now, now))
    p = _provider(str(f))
    _refresh(p)
    assert p.current(now) is None
    # …mais un day_start EXPLICITE (3e champ) suffit, même tête illisible :
    with open(f, "a") as fh:
        fh.write("1700000901;49400.0;50000.0\n")
    os.utime(f, (now, now))
    _refresh(p)
    acc = p.current(now)
    assert acc is not None
    assert acc.current_equity == 49_400.0 and acc.day_start_equity == 50_000.0


def test_devil_ecritures_haute_frequence_pendant_le_poll(tmp_path):
    """100+ appends/s pendant que le poll lit : jamais d'exception, et la dernière ligne
    COMPLÈTE valide est toujours extraite (jamais une ligne déchirée)."""
    import threading
    now = time.time()
    f = tmp_path / "nt8_account.csv"
    f.write_text("1700000000;50000.0\n")
    os.utime(f, (now, now))
    p = _provider(str(f))
    written = [50_000.0]
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set() and i < 400:
            i += 1
            eq = 50_000.0 - i
            with open(f, "a") as fh:
                fh.write(f"17000{i:05d};{eq}\n")
            written.append(eq)
    t = threading.Thread(target=writer)
    t.start()
    seen = []
    try:
        for _ in range(15):                                 # polls concurrents aux écritures
            _refresh(p)
            acc = p.current(time.time())
            if acc is not None:
                seen.append(acc.current_equity)
    finally:
        stop.set()
        t.join()
    assert seen                                             # des lectures ont abouti
    assert all(eq in written for eq in seen)                # toujours une ligne COMPLÈTE écrite
    _refresh(p)
    assert p.current(time.time()).current_equity == written[-1]   # convergence sur la dernière
