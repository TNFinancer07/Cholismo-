"""Client FRED — interroger n'importe quelle série (D-057).

« Un endpoint, un format, une clé gratuite. C'est le connecteur le plus rentable du système :
à lui seul il couvre l'essentiel de D1, D3 et D4. » Ce module ne garde que ce qui est PROPRE à
FRED : la clé API et la construction d'URL. Le harnais d'interrogation (timeout borné, fetcher
injecté, lecture bornée, deux natures d'échec, rédaction des secrets) vit dans `client`, et le
parsing dans `connectors` — rien n'est redupliqué ici.

Ce qui reste spécifique, et qui compte :
- **la clé** est lue au moment de l'appel, jamais figée à l'import (défaut déjà payé, D-056) ;
- **l'identifiant est validé AVANT la construction de l'URL** (`connectors`) : sans ce garde,
  `series_id` s'écrit dans la query string et un simple `&` ajoute un paramètre à l'appel ;
- **la clé ne fuit nulle part** hors de la requête — un message de socket contient volontiers
  l'URL entière, donc le secret (rédaction faite par le harnais).
"""
from __future__ import annotations

from typing import Callable, Optional

from .. import config
from . import connectors as cx
from .catalog import Provider
from .client import (DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient,
                     SeriesResult, SeriesTable)

# Résultat et tableau sont communs à tous les connecteurs ; les alias gardent les noms d'usage
# côté FRED, qui est le point d'entrée documenté de ce connecteur.
FredResult = SeriesResult

__all__ = ["FredClient", "FredResult", "SeriesTable", "fetch_series",
           "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]


class FredClient(HttpSeriesClient):
    """Interrogateur de séries FRED. `fetcher` est INJECTÉ : les tests n'ouvrent aucune socket."""

    LABEL = "FRED"
    PROVIDER = Provider.FRED
    PARSER = staticmethod(cx.parse_fred_json)

    def __init__(self, *, api_key: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        super().__init__(fetcher=fetcher, timeout_s=timeout_s)
        # `None` = « lire la configuration au moment de l'appel » : figer la valeur ici la
        # gèlerait à l'import, défaut déjà payé une fois (D-056).
        self._api_key = api_key

    # -- interrogation directe : n'importe quelle série --

    def fetch(self, series_id: str, *, start: Optional[str] = None) -> SeriesResult:
        """Observations d'une série FRED (UNRATE, DFF, SP500, T10YIE, …).

        Lève `SeriesBlocked` si la demande est refusée par politique ; sinon rend toujours un
        résultat, motif à l'appui quand la donnée n'est pas venue."""
        url = cx.fred_observations_url(series_id, api_key=self._key(), start=start)
        return self._run(series_id, url)

    async def fetch_async(self, series_id: str, *, start: Optional[str] = None) -> SeriesResult:
        """Même chose, I/O en thread : la boucle d'événements ne gèle jamais (§7)."""
        # Le refus de politique est levé AVANT de partir en thread — inutile de payer un
        # changement de contexte pour une demande qu'on refuse.
        url = cx.fred_observations_url(series_id, api_key=self._key(), start=start)
        return await self._run_async(series_id, url)

    # -- interrogation par la clé métier du registre --

    def fetch_catalog(self, key: str, *, start: Optional[str] = None) -> SeriesResult:
        return self.fetch(self._spec_for(key).identifier or "", start=start)

    def _key(self) -> Optional[str]:
        return config.FRED_API_KEY if self._api_key is None else self._api_key



def fetch_series(series_id: str, *, api_key: Optional[str] = None,
                 start: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None) -> SeriesResult:
    """Raccourci sans état pour un script ou une session d'exploration."""
    return FredClient(api_key=api_key, fetcher=fetcher).fetch(series_id, start=start)
