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

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .. import config
from . import connectors as cx
from .catalog import Provider
from .client import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MIN_TIMEOUT_S, HttpSeriesClient, SeriesResult

# Le résultat est commun à tous les connecteurs ; l'alias garde le nom d'usage côté FRED.
FredResult = SeriesResult

__all__ = ["FredClient", "FredResult", "SeriesTable", "fetch_series",
           "DEFAULT_TIMEOUT_S", "MIN_TIMEOUT_S", "MAX_TIMEOUT_S"]


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


    # -- assemblage tabulaire : plusieurs séries, un tableau --

    def to_columns(self, series: Sequence[str], *, start: Optional[str] = None,
                   catalog: bool = False) -> SeriesTable:
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
            result = (self.fetch_catalog(name, start=start) if catalog
                      else self.fetch(name, start=start))
            if result.series is None or not result.series.observations:
                failed[name] = result.error or "aucune observation exploitable"
                continue
            brut[name] = {o.date: o.value for o in result.series.observations}
        periods = tuple(sorted({p for obs in brut.values() for p in obs}))
        for name, obs in brut.items():
            columns[name] = tuple(obs.get(p) for p in periods)
        return SeriesTable(periods=periods, columns=columns, failed=failed,
                           coverage={n: len(o) for n, o in brut.items()})

    def to_dataframe(self, series: Sequence[str], *, start: Optional[str] = None,
                     catalog: bool = False, datetime_index: bool = False):
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
        table = self.to_columns(series, start=start, catalog=catalog)
        index = pd.to_datetime(list(table.periods)) if datetime_index else list(table.periods)
        return pd.DataFrame({n: list(v) for n, v in table.columns.items()}, index=index)


def fetch_series(series_id: str, *, api_key: Optional[str] = None,
                 start: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None) -> SeriesResult:
    """Raccourci sans état pour un script ou une session d'exploration."""
    return FredClient(api_key=api_key, fetcher=fetcher).fetch(series_id, start=start)
