"""Feature — log_scraper : tailer NT8 + parseur d'exécution + auto-snapshot (D-031).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- OBSERVATION seule (§2.1) : lit les logs d'exécution que NinjaTrader a DÉJÀ produits (fills
  passés par l'humain dans NT8) — ne passe JAMAIS d'ordre ;
- tailer ASYNC NON-BLOQUANT : lit uniquement les lignes NEUVES (offset), I/O offloadée
  (to_thread), démarre en FIN de fichier (ne re-déclenche pas l'historique) ;
- parseur Regex : détecte 'Execution=' / 'filled' / State=Filled et extrait les champs
  disponibles (instrument, prix, quantité) ; ligne de bruit → None ;
- fail-closed (§3) : fichier absent/illisible → rien, jamais un fill inventé ; robuste à la
  ROTATION quotidienne (nouvel inode → repart de la fin) et à la troncature ;
- un match validé → callback (câblé à la capture de snapshot).
"""
import asyncio
import os
import time

from app.log_scraper import LogTailer, nt8_daily_log_path, parse_execution


def _run(coro):
    return asyncio.run(coro)


def test_parse_execution_detects_execution_line_with_fields():
    m = parse_execution("2024-11-15 09:30:15|Execution='NT-0001' Instrument='ES 12-24' "
                        "Account='Sim101' Price=5000.25 Quantity=2 MarketPosition=Long")
    assert m is not None
    assert m.instrument == "ES 12-24"
    assert m.price == 5000.25
    assert m.quantity == 2


def test_parse_execution_detects_filled_state():
    assert parse_execution("Order='x' State=Filled Instrument='NQ' Price=17000.0") is not None
    assert parse_execution("... order filled at market ...") is not None


def test_parse_execution_ignores_noise():
    assert parse_execution("2024-11-15 09:00:00|Connected to data feed") is None
    assert parse_execution("") is None
    assert parse_execution("INFO strategy enabled") is None


def test_tailer_triggers_callback_on_new_execution_line(tmp_path):
    async def scenario():
        path = tmp_path / "log.20240101.txt"
        path.write_text("")
        hits = []

        async def cb(m):
            hits.append(m)

        t = LogTailer(lambda: str(path), cb)
        await t._poll_once()                       # baseline : offset → fin (0)
        with open(path, "a", encoding="utf-8") as f:
            f.write("Execution='NT-1' Instrument='ES 12-24' Price=5000.0 Quantity=1\n")
        await t._poll_once()                       # détecte la ligne neuve
        assert len(hits) == 1 and hits[0].price == 5000.0
        with open(path, "a", encoding="utf-8") as f:
            f.write("info: heartbeat\n")           # bruit → pas de nouveau trigger
        await t._poll_once()
        assert len(hits) == 1
    _run(scenario())


def test_tailer_skips_preexisting_history_on_first_sight(tmp_path):
    async def scenario():
        path = tmp_path / "log.20240101.txt"
        path.write_text("Execution='OLD' Instrument='ES' Price=1.0 Quantity=1\n")  # historique
        hits = []

        async def cb(m):
            hits.append(m)

        t = LogTailer(lambda: str(path), cb)
        await t._poll_once()                       # première vue → démarre en FIN
        assert hits == []                          # ne re-déclenche PAS l'historique
        with open(path, "a", encoding="utf-8") as f:
            f.write("Execution='NEW' Instrument='ES' Price=2.0 Quantity=1\n")
        await t._poll_once()
        assert len(hits) == 1 and hits[0].price == 2.0
    _run(scenario())


def test_tailer_fail_closed_when_file_absent(tmp_path):
    async def scenario():
        hits = []

        async def cb(m):
            hits.append(m)

        t = LogTailer(lambda: str(tmp_path / "nonexistent.txt"), cb)
        await t._poll_once()                       # ne crashe pas
        assert hits == []                          # aucun trigger sur fichier absent
    _run(scenario())


def test_tailer_handles_daily_rotation(tmp_path):
    async def scenario():
        hits = []

        async def cb(m):
            hits.append(m)

        p1 = tmp_path / "log.20240101.txt"
        p2 = tmp_path / "log.20240102.txt"
        current = {"p": p1}
        p1.write_text("Execution='D1' Instrument='ES' Price=1.0 Quantity=1\n")
        t = LogTailer(lambda: str(current["p"]), cb)
        await t._poll_once()                       # J1 : démarre en fin (skip historique)
        # rotation → nouveau fichier (nouvel inode) : démarre en fin du nouveau, pas re-trigger
        p2.write_text("Execution='D2_OLD' Instrument='ES' Price=2.0 Quantity=1\n")
        current["p"] = str(p2)
        await t._poll_once()
        assert hits == []
        with open(p2, "a", encoding="utf-8") as f:
            f.write("Execution='D2_NEW' Instrument='ES' Price=3.0 Quantity=1\n")
        await t._poll_once()
        assert len(hits) == 1 and hits[0].price == 3.0
    _run(scenario())


def test_tailer_read_is_non_blocking(tmp_path):
    async def scenario():
        t = LogTailer(lambda: str(tmp_path / "log.txt"), lambda m: None)

        def slow_read(path):
            time.sleep(0.3)                        # bloque un THREAD, pas la boucle
            return []

        t._read_new = slow_read
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(40):
                await asyncio.sleep(0.01)
                ticks += 1

        await asyncio.gather(t._poll_once(), ticker())
        assert ticks >= 30, f"boucle bloquée par la lecture (ticks={ticks})"
    _run(scenario())


def test_nt8_daily_log_path_targets_todays_file(tmp_path):
    now = time.time()
    stamp = time.strftime("%Y%m%d", time.gmtime(now))
    (tmp_path / f"log.{stamp}.txt").write_text("x")
    (tmp_path / "log.20200101.txt").write_text("old")     # autre jour → ignoré
    path = nt8_daily_log_path(str(tmp_path), now)
    assert path is not None and stamp in os.path.basename(path)
    # dossier sans log du jour → None (fail-closed, pas d'invention)
    assert nt8_daily_log_path(str(tmp_path / "empty"), now) is None
