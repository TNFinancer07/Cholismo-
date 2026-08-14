"""Client Yahoo Finance — deux tickers, et une réserve assumée (D-057).

« Deux tickers seulement, mais aucun substitut gratuit propre : `^GDAXI` (risk appetite EUR, D1)
et `^MOVE` (volatilité obligataire, D4). Également le canal des futures ZQ pour D2. »

**Réserve à assumer une fois pour toutes, écrite ici plutôt que découverte un matin** : ce n'est
PAS une API officielle, les CGU Yahoo couvrent l'usage personnel et la recherche. Prévoir que ça
casse un jour et que le remplacement sera manuel. C'est la seule source du registre dont la
disponibilité future n'est garantie par personne.

**`ZQ` est une RACINE de contrat, pas un ticker** : sans le mois et l'année il n'y a aucune
série à demander, et choisir une échéance par défaut déciderait à la place de l'opérateur.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from . import connectors as cx
from .catalog import Provider
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

BASE = "https://query1.finance.yahoo.com/v7/finance/download"
__all__ = ["YahooClient", "TICKERS", "data_url", "fetch_series", "BASE",
           "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]

TICKERS: dict[str, str] = {
    "^GDAXI": "DAX — risk appetite jambe EUR (D1 · Arb 5). Vérifier l'alignement des jours "
              "fériés avant de soustraire au S&P 500, qui vient de FRED.",
    "^MOVE": "volatilité obligataire — confirmation du régime D4. Ligne SUPPRIMABLE : "
             "VIX + HY + NFCI suffisent à définir le régime sans elle.",
    "ZQ": "RACINE des futures Fed Funds (D2 · Arb 1) — préciser le contrat, ex. ZQZ26.",
}

_TICKER_RE = re.compile(r"^\^?[A-Za-z0-9.\-=]{1,20}$")


def data_url(ticker: str, *, contract: Optional[str] = None) -> str:
    if ticker == "ZQ":
        if not contract:
            raise cx.SeriesBlocked(
                "« ZQ » est une racine de contrat, pas un ticker — préciser le contrat "
                "(ex. ZQZ26). La méthodologie FedWatch est publique, le choix de l'échéance "
                "ne l'est pas.")
        ticker = contract if "." in contract else f"{contract}.CBT"
    if not isinstance(ticker, str) or not _TICKER_RE.match(ticker):
        raise cx.SeriesBlocked(
            f"« {ticker} » n'a pas la forme d'un ticker Yahoo — refusé avant la requête.")
    return (f"{BASE}/{quote(ticker)}?period1=0&period2=9999999999&interval=1d&events=history")


class YahooClient(HttpSeriesClient):
    """Interrogateur Yahoo. Aucune clé API — et aucune garantie de disponibilité (voir module)."""

    LABEL = "Yahoo"
    PROVIDER = Provider.YFINANCE
    PARSER = staticmethod(cx.parse_yahoo_csv)

    def fetch(self, ticker: str, *, contract: Optional[str] = None) -> SeriesResult:
        return self._run(ticker, data_url(ticker, contract=contract))

    async def fetch_async(self, ticker: str, *, contract: Optional[str] = None) -> SeriesResult:
        return await self._run_async(ticker, data_url(ticker, contract=contract))

    def _by_identifier(self, identifier: str, **kw: Any) -> SeriesResult:
        return self.fetch(identifier, **kw)


def fetch_series(ticker: str, fetcher: Optional[object] = None, **kw) -> SeriesResult:
    return YahooClient(fetcher=fetcher).fetch(ticker, **kw)   # type: ignore[arg-type]
