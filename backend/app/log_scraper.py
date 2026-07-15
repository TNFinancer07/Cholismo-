"""log_scraper (D-031) — tailer NinjaTrader 8 + parseur d'exécution + auto-snapshot.

OBSERVATION seule (§2.1) : lit les logs d'exécution que NinjaTrader a DÉJÀ produits (fills
passés par l'humain dans NT8). Ne passe JAMAIS d'ordre — il ne fait que constater qu'un fill
a eu lieu et déclenche une capture de snapshot déterministe.

Contraintes :
- ASYNC NON-BLOQUANT (§7) : la lecture disque est offloadée (`asyncio.to_thread`) ; la boucle
  d'événements — donc le hot path — n'est jamais bloquée par l'I/O.
- FAIL-CLOSED (§3) : fichier absent/illisible → rien, jamais un fill inventé. Le tailer
  démarre en FIN de fichier (ne re-déclenche pas l'historique) et repart de la fin sur
  ROTATION quotidienne (nouvel inode) ou troncature — aucun replay.
- DÉTERMINISTE : détection par Regex sur mots-clés (`Execution=` / `filled` / `State=Filled`),
  aucun LLM.
"""
from __future__ import annotations

import asyncio
import glob
import inspect
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

log = logging.getLogger("cholismo.log_scraper")

# --- Détection : une ligne est une exécution si elle porte un de ces marqueurs (NT8) ---
#   Execution='...'  ·  State=Filled  ·  "order filled"  (insensible à la casse)
_EXEC_KEYWORDS = re.compile(r"Execution\s*=|\bfilled\b", re.IGNORECASE)
_RE_INSTRUMENT = re.compile(r"Instrument='([^']*)'")
_RE_PRICE = re.compile(r"Price=([-+]?\d+(?:\.\d+)?)")
_RE_QUANTITY = re.compile(r"Quantity=([-+]?\d+)")


@dataclass
class ExecutionMatch:
    """Un fill détecté dans le log NT8. Champs optionnels : une ligne peut matcher le mot-clé
    sans exposer tous les champs — on capture ce qui est présent, jamais on n'invente (§3)."""
    raw: str
    instrument: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None


def parse_execution(line: str) -> Optional[ExecutionMatch]:
    """Retourne un `ExecutionMatch` si la ligne est une exécution, sinon `None` (bruit).

    Déterministe : simple correspondance de motifs, aucune interprétation probabiliste."""
    if not line or not _EXEC_KEYWORDS.search(line):
        return None
    mi = _RE_INSTRUMENT.search(line)
    mp = _RE_PRICE.search(line)
    mq = _RE_QUANTITY.search(line)
    return ExecutionMatch(
        raw=line,
        instrument=mi.group(1) if mi else None,
        price=float(mp.group(1)) if mp else None,
        quantity=int(mq.group(1)) if mq else None,
    )


def nt8_daily_log_path(log_dir: str, now: float) -> Optional[str]:
    """Cible le log NT8 du JOUR (`log.YYYYMMDD*.txt`). Retourne le plus récent, ou `None` si
    aucun log du jour n'existe (fail-closed : on ne devine pas un autre fichier)."""
    stamp = time.strftime("%Y%m%d", time.gmtime(now))
    matches = glob.glob(os.path.join(log_dir, f"log.{stamp}*.txt"))
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


class LogTailer:
    """Suit un fichier de log qui grandit et invoque `on_execution` pour chaque nouvelle ligne
    d'exécution. `path_fn` est ré-évalué à chaque poll → suit la rotation quotidienne sans
    redémarrage."""

    def __init__(
        self,
        path_fn: Callable[[], str],
        on_execution: Callable[[ExecutionMatch], Optional[Awaitable[None]]],
        poll_seconds: float = 1.0,
    ) -> None:
        self._path_fn = path_fn
        self._on_execution = on_execution
        self._poll_seconds = poll_seconds
        self._inode: Optional[tuple[int, int]] = None  # (st_dev, st_ino) du fichier suivi
        self._offset = 0                                # position de lecture atteinte
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def _read_new(self, path: str) -> Optional[list[str]]:
        """Lit UNIQUEMENT les octets neufs depuis le dernier offset. Bloquant → appelé
        exclusivement via `asyncio.to_thread`. Retourne la liste des lignes neuves, `[]` si
        rien de neuf, `None` si le fichier est absent/illisible (fail-closed).

        Première vue / rotation (inode différent) → se cale en FIN de fichier et retourne `[]`
        (l'historique n'est jamais rejoué). Troncature (taille < offset) → repart de la fin."""
        try:
            st = os.stat(path)
        except OSError:
            return None
        inode = (st.st_dev, st.st_ino)
        size = st.st_size
        if inode != self._inode:
            # première vue ou rotation quotidienne : nouveau fichier → démarre en fin
            self._inode = inode
            self._offset = size
            return []
        if size < self._offset:
            # fichier tronqué/réécrit en place → repart de la fin, aucun replay (§3)
            self._offset = size
            return []
        if size == self._offset:
            return []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                data = f.read()
                self._offset = f.tell()
        except OSError:
            return None
        return data.splitlines()

    async def _poll_once(self) -> None:
        """Un cycle : lit les lignes neuves (I/O offloadée) puis notifie chaque exécution."""
        path = self._path_fn()
        lines = await asyncio.to_thread(self._read_new, path)
        if not lines:
            return
        for line in lines:
            match = parse_execution(line)
            if match is None:
                continue
            result = self._on_execution(match)
            if inspect.isawaitable(result):
                await result

    async def _loop(self) -> None:
        """Boucle auto-cadencée (RUNTIME_LOOPS Loop D) : ne meurt jamais sur une exception de
        poll, garde une cadence stable même si un poll traîne."""
        while self._running:
            started = time.monotonic()
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("log_scraper poll failed; continuing")
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.05, self._poll_seconds - elapsed))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
