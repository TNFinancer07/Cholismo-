"""Source de compte — port `AccountDataProvider` + mock strict (D-047, tranche 2).

Le RiskSizer (D-047 T1) est pur : quelqu'un doit lui apporter l'état du compte. Ce module est ce
port. Contrat : `current(now) -> AccountState | None` — l'horloge est INJECTÉE (règle commune
D-045/046/047 : rien ici ne lit l'heure), et le provider est seul juge de la FRAÎCHEUR de sa
photo. `None` couvre les réalités que l'appelant traite TOUTES pareil (fail-closed §3, « on ne trade
jamais à l'aveugle ») : jamais connecté, déconnecté, photo périmée (> `ACCOUNT_MAX_AGE_S`),
photo au ts NON FINI (NaN passerait une comparaison naïve) ou datée du FUTUR (désync d'horloge
broker — son heure réelle est inconnue, leçon D-028/D-046) — une équité fossile ou fantôme
n'est pas une équité. Côté engine, le port est consommé sous `try/except` + garde de type :
un provider réel qui LÈVE ou rend n'importe quoi = coupure = rejet naturel = silence.

`MockAccountProvider` simule le flux NinjaTrader/broker pour les tests et le stack mock :
- `push(state, ts)` : nouvelle photo datée (mise à jour d'équité après un fill) ;
- `disconnect()` : coupure du flux ;
- `always_fresh=True` : **couture du stack DÉMO uniquement** — un broker simulé qui répond
  toujours ; un provider réel (NinjaTrader/Rithmic) remplace ce mode par de vraies photos
  datées et le même port, sans toucher à l'engine.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Optional, Protocol

from . import config
from .risk_sizer import AccountState, ApexEodPreset

log = logging.getLogger("cholismo.account")


class AccountDataProvider(Protocol):
    """Port : rendre l'état du compte au moment `now`, ou None si l'on n'en sait RIEN de frais."""

    def current(self, now: float) -> Optional[AccountState]:
        ...


class MockAccountProvider:
    """Simulation stricte du flux compte broker — périmé = absent, jamais une équité fossile."""

    def __init__(self, state: Optional[AccountState] = None, ts: Optional[float] = None,
                 always_fresh: bool = False,
                 max_age_s: float = config.ACCOUNT_MAX_AGE_S):
        self._state = state
        self._ts = ts
        self._always_fresh = always_fresh
        self._max_age_s = max_age_s
        self._connected = True

    def push(self, state: AccountState, ts: float) -> None:
        """Nouvelle photo datée du compte (le broker vient de parler)."""
        self._state, self._ts = state, ts

    def disconnect(self) -> None:
        self._connected = False

    def current(self, now: float) -> Optional[AccountState]:
        if not self._connected or self._state is None:
            return None
        if self._always_fresh:
            return self._state
        # Fraîcheur STRICTE (/devil) : ts absent, NON FINI (NaN passerait « nan > max_age » qui
        # est FAUX), ou daté du FUTUR (désync d'horloge broker — `now − ts` négatif resterait
        # « frais » indéfiniment ; son heure réelle est inconnue, même leçon que D-046) → None.
        ts = self._ts
        if not isinstance(ts, (int, float)) or not math.isfinite(ts):
            return None
        if ts > now or now - ts > self._max_age_s:
            return None                                   # photo périmée/fantôme → on ne sait rien (§3)
        return self._state


class NT8FileAccountProvider:
    """Provider RÉEL : lit l'état du compte depuis un export NinjaTrader 8 (D-048).

    **Deux étages, pour tenir les deux contrats à la fois** : le port D-047 exige un `current(now)`
    SYNCHRONE (appelé dans la boucle sweep), et l'I/O fichier ne doit JAMAIS geler l'event loop
    (un `stat`/`read` peut bloquer des millisecondes sous verrou Windows/antivirus). Résolution :
    - une boucle de rafraîchissement ASYNC (`start`/`stop`, cadence `NT8_ACCOUNT_POLL_SECONDS`)
      exécute la lecture BLOQUANTE dans un thread (`asyncio.to_thread`) et alimente un cache
      `(AccountState, mtime)` ;
    - `current(now)` reste sync et applique la règle de fraîcheur D-047 sur le cache.

    **Horodatage = mtime du fichier** — même horloge que `now` (le système de fichiers du backend),
    donc pas de dérive inter-machines ; et si NT8 cesse d'écrire, le mtime fige et
    `ACCOUNT_MAX_AGE_S` périme le compte NATURELLEMENT. Le ts interne des lignes n'est jamais
    utilisé pour la fraîcheur (horloge NT8 ≠ horloge backend). Un refresh raté ne ressuscite ni ne
    re-timbre le cache : il vieillit par son mtime d'origine.

    **Format v1 provisional** (convention côté exporteur NT8, un fichier par jour de session) :
    lignes `epoch;equity[;day_start]` appendées en continu. Dernière ligne VALIDE gagne ; ligne
    déchirée en plein vol → la précédente ; `day_start` explicite (3e champ) sinon DÉDUIT de la
    PREMIÈRE ligne valide du fichier ; floor et DLL viennent du preset Apex (NT8 ne les connaît
    pas — le recalcul EOD Trail reste au driver de fin de session, D-047).

    **FAIL-CLOSED I/O, silence ABSOLU** : introuvable, verrouillé, illisible, aucune ligne valide,
    équité non-finie ou ≤ 0 → pas de snapshot, aucun log — un échec d'I/O attendu est un rejet
    naturel (hygiène D-046), pas une panne à hurler."""

    def __init__(self, path: str, preset: ApexEodPreset,
                 drawdown_floor: Optional[float] = None,
                 poll_seconds: float = None,  # type: ignore[assignment]
                 max_age_s: float = None):    # type: ignore[assignment]
        self._path = path
        self._preset = preset
        self._floor = (drawdown_floor if drawdown_floor is not None
                       else preset.initial_capital - preset.max_drawdown)
        self._poll_s = poll_seconds if poll_seconds is not None else config.NT8_ACCOUNT_POLL_SECONDS
        self._max_age_s = max_age_s if max_age_s is not None else config.ACCOUNT_MAX_AGE_S
        self._snapshot: Optional[tuple[AccountState, float]] = None   # (state, mtime)
        self._task: Optional[asyncio.Task] = None

    # -- étage async : rafraîchissement --

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Une exception INATTENDUE est une panne (pas un rejet naturel) : elle se voit —
                # les échecs d'I/O attendus sont déjà silencieusement absorbés par _read_file.
                log.exception("NT8 account poll failed (fail-closed: snapshot ages out)")
            await asyncio.sleep(max(0.1, self._poll_s))

    async def refresh(self) -> None:
        """Un cycle de lecture — la partie BLOQUANTE part dans un thread : l'event loop reste
        libre même si le fichier est verrouillé une milliseconde (ou trois cents)."""
        snap = await asyncio.to_thread(self._read_file)
        if snap is not None:
            self._snapshot = snap                            # un échec ne touche PAS au cache

    # -- étage bloquant (thread) : lecture FENÊTRÉE + parsing tolérant --

    # Fenêtres de lecture (/devil) : jamais un readlines() du fichier ENTIER — un flood de 10 Mo
    # (ou 1 Go) mangerait la RAM et le CPU du worker à CHAQUE poll. Tête bornée (le day_start
    # vit dans les premières lignes) + queue bornée (la dernière ligne valide vit à la fin) :
    # O(72 Ko) par lecture quel que soit le fichier.
    _HEAD_BYTES = 8_192
    _TAIL_BYTES = 65_536

    def _read_file(self) -> Optional[tuple[AccountState, float]]:
        try:
            st = os.stat(self._path)
            mtime, size = st.st_mtime, st.st_size
            with open(self._path, "rb") as f:
                if size <= self._HEAD_BYTES + self._TAIL_BYTES:
                    head_raw = tail_raw = f.read()
                    tail_offset = False                      # un seul buffer, lignes complètes sûres
                else:
                    head_raw = f.read(self._HEAD_BYTES)
                    f.seek(size - self._TAIL_BYTES)
                    tail_raw = f.read(self._TAIL_BYTES)
                    tail_offset = True                       # la fenêtre peut couper une ligne au début
        except OSError:
            return None                                      # introuvable/verrouillé → silence

        # TAIL-SAFETY : seuls les éléments AVANT le dernier `\n` sont des lignes TERMINÉES — une
        # écriture en vol n'a pas son newline, et un float tronqué reste un float (« 49600.0 »
        # déchiré en « 4 » parserait comme 4,0 $). Le fragment final est toujours écarté ; en
        # fenêtre décalée, le fragment INITIAL aussi (potentiellement coupé en plein milieu).
        head_lines = head_raw.decode("utf-8", errors="replace").split("\n")[:-1]
        tail_lines = tail_raw.decode("utf-8", errors="replace").split("\n")[:-1]
        if tail_offset:
            tail_lines = tail_lines[1:]

        # dernière ligne VALIDE de la queue — balayée à REBOURS (la plus récente d'abord)
        last: Optional[tuple[float, Optional[float]]] = None
        for line in reversed(tail_lines):
            last = self._parse_line(line)
            if last is not None:
                break
        if last is None:
            return None                # l'état RÉCENT est illisible → à l'aveugle → pas de compte

        equity, explicit_day_start = last
        if explicit_day_start is not None:
            day_start = explicit_day_start
        else:
            # day_start DÉDUIT de la première ligne valide de la tête. Introuvable → None :
            # un day_start inventé (= équité courante) simulerait un JOUR NEUF, le DLL
            # repartirait plein — la corruption deviendrait du levier (leçon D-047).
            first = next((p for line in head_lines
                          if (p := self._parse_line(line)) is not None), None)
            if first is None:
                return None
            day_start = first[0]
        state = AccountState(account_type="EOD_TRAILING", current_equity=equity,
                             day_start_equity=day_start, drawdown_floor=self._floor,
                             daily_loss_limit=self._preset.daily_loss_limit)
        return state, mtime

    @staticmethod
    def _parse_line(line: str) -> Optional[tuple[float, Optional[float]]]:
        """`epoch;equity[;day_start]` → (equity, day_start | None). Tout écart → None :
        champs manquants, non-numériques, non finis, équité ou day_start ≤ 0. Le BOM UTF-8
        est ignoré (sans ça, la PREMIÈRE ligne — celle du day_start déduit — serait avalée)."""
        parts = line.strip().lstrip("﻿").split(";")
        if len(parts) < 2:
            return None
        try:
            float(parts[0])                                  # epoch interne : présent et numérique,
        except ValueError:                                   # jamais utilisé pour la fraîcheur
            return None
        try:
            equity = float(parts[1])
        except ValueError:
            return None
        if not math.isfinite(equity) or equity <= 0:
            return None
        day_start: Optional[float] = None
        if len(parts) >= 3 and parts[2].strip():
            try:
                day_start = float(parts[2])
            except ValueError:
                return None
            if not math.isfinite(day_start) or day_start <= 0:
                return None
        return equity, day_start

    # -- étage sync : le port D-047, règle de fraîcheur identique au mock --

    def current(self, now: float) -> Optional[AccountState]:
        if self._snapshot is None:
            return None
        state, ts = self._snapshot
        if not isinstance(ts, (int, float)) or not math.isfinite(ts):
            return None
        if ts > now or now - ts > self._max_age_s:
            return None                                      # mtime figé/fantôme → à l'aveugle → non
        return state
