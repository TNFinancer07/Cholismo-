"""Client FRED — interroger n'importe quelle série (D-057).

« Un endpoint, un format, une clé gratuite. C'est le connecteur le plus rentable du système :
à lui seul il couvre l'essentiel de D1, D3 et D4. » Ce module est la moitié « aller chercher »
du connecteur ; la construction d'URL et le parsing vivent dans `connectors` et ne sont pas
redupliqués ici.

**Deux natures d'échec, jamais confondues** — c'est tout le contrat de ce module :

- **Refus de politique** → `SeriesBlocked` levée. Clé API absente, identifiant qui n'a pas la
  forme d'une série FRED, ligne du registre non confirmée (C2/C3) ou servie par un autre
  fournisseur. C'est une erreur de PROGRAMME : elle doit s'arrêter net, pas se dégrader en une
  série vide qu'on lirait ensuite comme un marché calme (§3).
- **Condition de données** → `FredResult.error` renseigné, aucune exception. Réseau injoignable,
  réponse illisible ou obèse. L'appelant garde ce qu'il avait (doctrine D-050) — un fetch raté
  ne détruit jamais le cache précédent, qui vieillit honnêtement de son côté.

**La clé n'apparaît nulle part hors de la requête.** Les messages d'erreur passent par
`connectors.redact` : un message de socket contient volontiers l'URL entière, donc le secret.

Deux étages, comme le provider de calendrier macro (D-050) : `fetch` est synchrone (à appeler
depuis un thread ou un script), `fetch_async` fait partir l'I/O en `asyncio.to_thread` pour que
la boucle d'événements ne gèle jamais (§7 — le hot path reste déterministe).
"""
from __future__ import annotations

import asyncio
import logging
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .. import config
from . import connectors as cx
from .catalog import BY_KEY, Provider

log = logging.getLogger("cholismo.providers.fred")

DEFAULT_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class FredResult:
    """Le résultat d'UNE interrogation. `series` et `error` sont mutuellement exclusifs."""
    series_id: str
    series: Optional[cx.ParsedSeries]
    error: Optional[str] = None
    url: str = ""                      # URL RÉDIGÉE (sans la clé) — traçabilité sans fuite


class FredClient:
    """Interrogateur de séries FRED. `fetcher` est INJECTÉ : les tests n'ouvrent aucune socket."""

    def __init__(self, *, api_key: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        # `None` = « lire la configuration au moment de l'appel » : figer la valeur ici la
        # gèlerait à l'import, défaut déjà payé une fois (D-056).
        self._api_key = api_key
        self._fetcher = fetcher if fetcher is not None else self._fetch_url
        self._timeout_s = timeout_s

    # -- interrogation directe : n'importe quelle série --

    def fetch(self, series_id: str, *, start: Optional[str] = None) -> FredResult:
        """Observations d'une série FRED (UNRATE, DFF, SP500, T10YIE, …).

        Lève `SeriesBlocked` si la demande est refusée par politique ; sinon rend toujours un
        `FredResult`, motif à l'appui quand la donnée n'est pas venue."""
        url = cx.fred_observations_url(series_id, api_key=self._key(), start=start)
        safe_url = cx.redact(url)
        try:
            text = self._fetcher(url)
        except Exception as exc:                       # noqa: BLE001 — condition de données
            # Un message de socket contient volontiers l'URL entière, donc la clé : on rédige.
            detail = cx.redact(str(exc)) or exc.__class__.__name__
            log.warning("FRED injoignable (%s) : %s", series_id, detail)
            return FredResult(series_id, None, f"FRED injoignable — {detail}", safe_url)
        parsed = cx.parse_fred_json(text)
        if parsed is None:
            return FredResult(series_id, None,
                              "réponse FRED illisible ou hors bornes — cache précédent conservé",
                              safe_url)
        return FredResult(series_id, parsed, None, safe_url)

    async def fetch_async(self, series_id: str, *, start: Optional[str] = None) -> FredResult:
        """Même chose, I/O en thread : la boucle d'événements ne gèle jamais (§7)."""
        # Le refus de politique est levé AVANT de partir en thread — inutile de payer un
        # changement de contexte pour une demande qu'on refuse.
        cx.fred_observations_url(series_id, api_key=self._key(), start=start)
        return await asyncio.to_thread(self.fetch, series_id, start=start)

    # -- interrogation par la clé métier du registre --

    def fetch_catalog(self, key: str, *, start: Optional[str] = None) -> FredResult:
        """Chemin normal : on demande `vixcls`, pas `VIXCLS`. Le portillon du registre
        s'applique (C1 seulement), et le fournisseur est vérifié — demander une série BCE à
        FRED ramènerait une erreur qu'on lirait comme une panne."""
        reason = cx.fetch_block_reason(key)
        if reason is not None:
            raise cx.SeriesBlocked(f"{key} : {reason}")
        spec = BY_KEY[key]
        if spec.provider is not Provider.FRED:
            raise cx.SeriesBlocked(
                f"{key} : servi par {spec.provider.value}, pas par FRED — utiliser le "
                "connecteur correspondant.")
        return self.fetch(spec.identifier or "", start=start)

    # -- internes --

    def _key(self) -> Optional[str]:
        return config.FRED_API_KEY if self._api_key is None else self._api_key

    def _fetch_url(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=self._timeout_s) as resp:   # dans un thread
            # Lecture BORNÉE (+1 pour détecter le dépassement) : une réponse plus grosse que la
            # borne ne peut pas être une série macro, et elle ne doit pas manger la RAM.
            return resp.read(cx.MAX_FEED_BYTES + 1).decode("utf-8", errors="replace")


def fetch_series(series_id: str, *, api_key: Optional[str] = None,
                 start: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None) -> FredResult:
    """Raccourci sans état pour un script ou une session d'exploration."""
    return FredClient(api_key=api_key, fetcher=fetcher).fetch(series_id, start=start)
