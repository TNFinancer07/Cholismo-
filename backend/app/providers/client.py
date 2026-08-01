"""Harnais commun d'interrogation HTTP — le socle des sept connecteurs (D-057).

Sept fournisseurs, sept manières de construire une URL et de lire une réponse — mais **une
seule** manière d'aller chercher : borner le timeout, injecter le fetcher, lire de façon bornée,
distinguer les deux natures d'échec, ne jamais laisser fuir un secret. Ce module porte cette
partie-là ; chaque connecteur ne garde que ce qui lui est propre.

**Deux natures d'échec, jamais confondues** — c'est le contrat de tout le paquet :

- **Refus de politique** → `SeriesBlocked` levée par le connecteur AVANT tout appel. Clé API
  absente, identifiant mal formé, ligne du registre non confirmée (C2/C3), fournisseur qui ne
  correspond pas. C'est une erreur de PROGRAMME : elle doit s'arrêter net, pas se dégrader en
  série vide qu'on lirait ensuite comme un marché calme (§3).
- **Condition de données** → `SeriesResult.error` renseigné, aucune exception. Réseau
  injoignable, réponse illisible ou obèse. L'appelant garde ce qu'il avait (doctrine D-050) —
  un fetch raté ne détruit jamais le cache précédent, qui vieillit honnêtement de son côté.

**Aucun secret ne sort.** Tout ce qui remonte passe par `connectors.redact` : un message de
socket contient volontiers l'URL entière, donc la clé quand il y en a une.

Deux étages, comme le provider de calendrier macro (D-050) : `_run` est synchrone, `_run_async`
fait partir l'I/O en `asyncio.to_thread` pour que la boucle d'événements ne gèle jamais (§7).
"""
from __future__ import annotations

import asyncio
import logging
import math
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from . import connectors as cx
from .catalog import BY_KEY, Provider, SeriesSpec

log = logging.getLogger("cholismo.providers")

DEFAULT_TIMEOUT_S = 10.0
# Bornes de timeout. La borne HAUTE n'est pas du confort : `_run_async` part en
# `asyncio.to_thread`, et un thread ne s'annule pas. Une annulation (Ctrl-C, `stop()`) rend la
# main tout de suite côté boucle, mais le thread vit jusqu'au timeout de la socket — un timeout
# absent ou géant laisserait un thread qui ne meurt jamais, et un arrêt qui n'en finit pas.
MIN_TIMEOUT_S, MAX_TIMEOUT_S = 1.0, 60.0


def clamp_timeout(value: object) -> float:
    """Un timeout absent ou absurde devient le défaut, puis reste dans les bornes. Sans ça,
    `timeout_s=None` se traduit en `urlopen(timeout=None)` : un thread qui ne meurt jamais."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return DEFAULT_TIMEOUT_S
    if not math.isfinite(value):
        return DEFAULT_TIMEOUT_S
    return min(max(float(value), MIN_TIMEOUT_S), MAX_TIMEOUT_S)


@dataclass(frozen=True)
class SeriesResult:
    """Le résultat d'UNE interrogation. `series` et `error` sont mutuellement exclusifs."""
    series_id: str                     # identifiant chez le fournisseur (FRED : `VIXCLS`)
    series: Optional[cx.ParsedSeries]
    error: Optional[str] = None
    url: str = ""                      # URL RÉDIGÉE (sans secret) — traçabilité sans fuite


class HttpSeriesClient:
    """Socle d'un connecteur. Les sous-classes fournissent `LABEL`, `PROVIDER`, `PARSER` et
    leur propre construction d'URL ; tout le reste est ici. `fetcher` est INJECTÉ : les tests
    n'ouvrent aucune socket."""

    LABEL: str = "fournisseur"                     # nom lisible, utilisé dans les motifs (§5)
    PROVIDER: Provider = Provider.NONE
    PARSER: Callable[[str], Optional[cx.ParsedSeries]] = staticmethod(cx.parse_sdmx_csv)

    def __init__(self, *, fetcher: Optional[Callable[[str], str]] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self._fetcher = fetcher if fetcher is not None else self._fetch_url
        self.timeout_s = clamp_timeout(timeout_s)

    # -- exécution : la seule manière d'aller chercher --

    def _run(self, series_id: str, url: str) -> SeriesResult:
        safe_url = cx.redact(url)
        try:
            text = self._fetcher(url)
        except Exception as exc:                   # noqa: BLE001 — condition de données
            detail = cx.redact(str(exc)) or exc.__class__.__name__
            log.warning("%s injoignable (%s) : %s", self.LABEL, series_id, detail)
            return SeriesResult(series_id, None, f"{self.LABEL} injoignable — {detail}", safe_url)
        parsed = type(self).PARSER(text)
        if parsed is None:
            echec = SeriesResult(series_id, None,
                                 f"réponse {self.LABEL} illisible ou hors bornes — cache "
                                 "précédent conservé", safe_url)
            # Le texte est encore en main : un connecteur qui sait distinguer plusieurs causes
            # d'échec les nomme ICI, sans refaire d'appel.
            return self._on_unreadable(text, echec)
        return SeriesResult(series_id, parsed, None, safe_url)

    def _on_unreadable(self, text: str, result: SeriesResult) -> SeriesResult:
        """Point d'extension : requalifier un parsing refusé quand le connecteur sait pourquoi.
        Par défaut, « illisible » est la seule cause connue et le motif reste tel quel."""
        return result

    async def _run_async(self, series_id: str, url: str) -> SeriesResult:
        return await asyncio.to_thread(self._run, series_id, url)

    # -- portillon du registre, commun à tous les connecteurs --

    def _spec_for(self, key: str) -> SeriesSpec:
        """Chemin normal : on demande la clé MÉTIER (`vixcls`), pas l'identifiant du
        fournisseur. Le portillon du registre s'applique (C1 seulement), et le fournisseur est
        vérifié — demander une série BCE à FRED ramènerait une erreur qu'on lirait comme une
        panne de source."""
        reason = cx.fetch_block_reason(key)
        if reason is not None:
            raise cx.SeriesBlocked(f"{key} : {reason}")
        spec = BY_KEY[key]
        if spec.provider is not self.PROVIDER:
            raise cx.SeriesBlocked(
                f"{key} : servi par {spec.provider.value}, pas par {self.PROVIDER.value} — "
                "utiliser le connecteur correspondant.")
        return spec

    # -- interne --

    def _fetch_url(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=self.timeout_s) as resp:    # dans un thread
            # Lecture BORNÉE (+1 pour détecter le dépassement) : une réponse plus grosse que la
            # borne ne peut pas être une série macro, et elle ne doit pas manger la RAM.
            return resp.read(cx.MAX_FEED_BYTES + 1).decode("utf-8", errors="replace")
