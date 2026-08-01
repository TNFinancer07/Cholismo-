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
import importlib
import logging
import math
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

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


@dataclass(frozen=True)
class SeriesTable:
    """Plusieurs séries alignées, **sans pandas**. Les échecs sont à part, jamais des colonnes
    vides : un réseau mort et une donnée pas encore publiée ne se lisent pas pareil (§3)."""
    periods: tuple[str, ...]                       # union des périodes, ordre chronologique
    columns: dict[str, tuple[Optional[float], ...]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)     # série → motif
    coverage: dict[str, int] = field(default_factory=dict)   # série → observations RÉELLES

    @property
    def rows(self) -> int:
        return len(self.periods)


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

    # -- assemblage tabulaire : plusieurs séries, un tableau --

    def _fetch_one(self, name: str, *, catalog: bool, **kw) -> SeriesResult:
        """Une série, désignée par UN nom. Chaque connecteur a une telle forme : un identifiant
        FRED, une clé SDMX pointée, un dataset Eurostat. C'est le seul point que l'assemblage
        tabulaire a besoin de connaître — le reste lui est indifférent."""
        return self.fetch_catalog(name, **kw) if catalog else self.fetch(name, **kw)

    def to_columns(self, series: Sequence[str], *, catalog: bool = False,
                   **kw) -> SeriesTable:
        """Plusieurs séries alignées sur l'union de leurs PÉRIODES, en Python pur.

        C'est ici qu'est toute la logique — `to_dataframe` n'en est qu'un habillage. Trois
        règles, et chacune corrige une manière de mentir :

        1. **Une série en ÉCHEC n'est jamais une colonne vide.** Elle sort du tableau et part
           dans `failed` avec son motif. Sinon un réseau mort et une donnée pas encore publiée
           deviennent indistinguables — la confusion que §3 interdit.
        2. **Aucun remplissage, jamais.** Pas de `ffill`, pas d'interpolation : une valeur
           reportée est une valeur inventée, et un z-score calculé dessus n'est pas un z-score.
           Si un remplissage a lieu, c'est une décision de l'appelant, prise sciemment.
        3. **La couverture est rendue.** Mêler du quotidien, du mensuel et du trimestriel
           produit un tableau très majoritairement vide : ce n'est pas un défaut, mais le lire
           sans le savoir en est un.

        `catalog=True` prend les clés MÉTIER du registre (`vixcls`) au lieu des identifiants
        FRED, applique le portillon, et nomme les colonnes par ces clés."""
        columns: dict[str, tuple[Optional[float], ...]] = {}
        failed: dict[str, str] = {}
        brut: dict[str, dict[str, float]] = {}
        for name in series:
            result = self._fetch_one(name, catalog=catalog, **kw)
            if result.series is None or not result.series.observations:
                failed[name] = result.error or "aucune observation exploitable"
                continue
            brut[name] = {o.date: o.value for o in result.series.observations}
        periods = tuple(sorted({p for obs in brut.values() for p in obs}))
        for name, obs in brut.items():
            columns[name] = tuple(obs.get(p) for p in periods)
        return SeriesTable(periods=periods, columns=columns, failed=failed,
                           coverage={n: len(o) for n, o in brut.items()})

    def to_dataframe(self, series: Sequence[str], *, catalog: bool = False,
                     datetime_index: bool = False, **kw):
        """Même chose, en `pandas.DataFrame`. Les séries en échec ne sont PAS des colonnes —
        leur motif reste consultable via `to_columns(...).failed`.

        L'index garde la période telle que FRED la publie. `datetime_index=True` est **opt-in**
        parce qu'il invente de la précision (« 2026 » deviendrait le 1ᵉʳ janvier) : c'est
        l'appelant qui accepte cette précision, jamais le défaut.

        pandas n'est **pas** une dépendance du terminal : le chemin d'exécution n'a pas à porter
        une pile numérique de plusieurs dizaines de Mo pour une commodité d'exploration."""
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError(
                "pandas est requis pour `to_dataframe` et n'est pas une dépendance du terminal "
                "(commodité d'exploration, hors chemin d'exécution) — `pip install pandas`, ou "
                "utiliser `to_columns` qui rend la même chose en Python pur."
            ) from exc
        table = self.to_columns(series, catalog=catalog, **kw)
        index = pd.to_datetime(list(table.periods)) if datetime_index else list(table.periods)
        return pd.DataFrame({n: list(v) for n, v in table.columns.items()}, index=index)

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


# =============================================================================================
# Quel connecteur pour quelle ligne — la porte d'entrée unique
# =============================================================================================

# Trois niveaux à ne pas confondre, et c'est la raison d'être de cette table :
#   1. la ligne est-elle COLLECTABLE ? (registre : C1, observée)            → fetch_block_reason
#   2. a-t-elle un endpoint HTTP ?     (le SPF est C1 et n'en a aucun)      → has_rest_endpoint
#   3. sait-on ALLER LA CHERCHER ?     (l'étage d'interrogation existe-t-il ?) → ici
# Une ligne peut franchir 1 et 2 et rester inaccessible parce que son client n'est pas écrit.
# L'afficher comme « collectable » sans le dire serait une promesse que le code ne tient pas.
_CLIENT_MODULES: dict[Provider, tuple[str, str]] = {
    Provider.FRED: ("fred", "FredClient"),
    Provider.ECB_SDMX: ("ecb", "EcbClient"),
    Provider.EUROSTAT: ("eurostat", "EurostatClient"),
}


def has_client(provider: Provider) -> bool:
    """Le fournisseur a-t-il un étage d'interrogation écrit ?"""
    return provider in _CLIENT_MODULES


def client_for(key: str, **kwargs) -> "HttpSeriesClient":
    """Client capable d'aller chercher CETTE ligne du registre, sans que l'appelant ait à
    savoir quel connecteur s'en occupe. Lève `SeriesBlocked` avec un motif utile sinon —
    y compris quand le connecteur reste à écrire, cas qu'aucun autre garde ne couvrait."""
    reason = cx.fetch_block_reason(key)
    if reason is not None:
        raise cx.SeriesBlocked(f"{key} : {reason}")
    provider = BY_KEY[key].provider
    if not cx.has_rest_endpoint(key):
        raise cx.SeriesBlocked(f"{key} : {cx.describe_endpoint(key)}")
    entry = _CLIENT_MODULES.get(provider)
    if entry is None:
        raise cx.SeriesBlocked(
            f"{key} : connecteur {provider.value} pas encore écrit — l'URL et le parsing "
            "existent, l'étage d'interrogation manque. Rien à relever au catalogue ici : "
            "c'est du code à produire.")
    module_name, class_name = entry
    # Import LOCAL : les connecteurs importent ce module, donc l'inverse ne peut pas se faire
    # en tête de fichier.
    module = importlib.import_module(f"{__package__}.{module_name}")
    return getattr(module, class_name)(**kwargs)
