"""Source de compte — port `AccountDataProvider` + mock strict (D-047, tranche 2).

Le RiskSizer (D-047 T1) est pur : quelqu'un doit lui apporter l'état du compte. Ce module est ce
port. Contrat : `current(now) -> AccountState | None` — l'horloge est INJECTÉE (règle commune
D-045/046/047 : rien ici ne lit l'heure), et le provider est seul juge de la FRAÎCHEUR de sa
photo. `None` couvre TROIS réalités que l'appelant traite pareil (fail-closed §3, « on ne trade
jamais à l'aveugle ») : jamais connecté, déconnecté, ou photo périmée (> `ACCOUNT_MAX_AGE_S`) —
une équité fossile n'est pas une équité.

`MockAccountProvider` simule le flux NinjaTrader/broker pour les tests et le stack mock :
- `push(state, ts)` : nouvelle photo datée (mise à jour d'équité après un fill) ;
- `disconnect()` : coupure du flux ;
- `always_fresh=True` : **couture du stack DÉMO uniquement** — un broker simulé qui répond
  toujours ; un provider réel (NinjaTrader/Rithmic) remplace ce mode par de vraies photos
  datées et le même port, sans toucher à l'engine.
"""
from __future__ import annotations

import math
from typing import Optional, Protocol

from . import config
from .risk_sizer import AccountState


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
