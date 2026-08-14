"""`ExternalDataModule` — le Niveau 3 branché sur le terminal (D-062).

Regroupe les deux chaînes (calendrier F5, VIX F3), tient un cache mémoire, rafraîchit sur sa
propre cadence et publie dans Redis sous les **noms de source que le moteur attend déjà** :
`macro_releases` sous `econ_feed`, `vix` sous `cboe`. Zéro modification d'`engine.py` : tout le
pipeline aval (normalisation D-040, `compute_macro_risk`, règle Phase 0 `MACRO_BLACKOUT`,
panneaux) fonctionne tel quel, et la couche de fraîcheur fait son travail sans être prévenue.

### Deux étages, comme le `MacroNewsProvider` (D-050)
Un worker async rafraîchit le cache (fetch en `asyncio.to_thread` — la boucle d'événements ne
gèle jamais, §7) ; les accesseurs sont **synchrones et purs**, horloge injectée, zéro I/O sur le
chemin d'évaluation. Un fetch raté CONSERVE l'ancien cache, qui vieillit par son `fetched_ts`
d'origine.

### Un cache FOSSILE n'est pas servi
Passé `max_age_s`, le cache n'est plus une donnée : c'est un souvenir. Les accesseurs rendent
alors `None` (aveugle, l'appelant décide) et `publish()` **n'écrit plus rien** — le champ
vieillit visiblement vers STALE puis ABSENT, ce qui EST la vérité. Republier un vieux calendrier
avec un horodatage frais le blanchirait en donnée courante : c'est le mensonge exact que §3
interdit, et il ouvrirait le verrou F5 sur un calendrier périmé.

### Ce que ce module ne détient PAS
- **Pas d'état d'hystérésis.** `engine` tient déjà `self._regime_tier` ; en garder un second ici
  ferait deux paliers D4 qui divergent. `vix_regime()` reçoit donc le palier courant en
  paramètre et ne le mémorise pas.
- **Pas de verdict.** Le blackout reste `compute_macro_risk`, le veto reste `VIX_CRIT`.

### Ce qu'une clôture quotidienne peut honnêtement alimenter
`vix` est un champ de canal RAPIDE. Une clôture FRED décrit la veille : la publier sans le dire
la ferait lire comme un niveau de séance. L'horodatage publié est donc celui de la LECTURE (on
a bien lu maintenant), mais le drapeau `VIX_CLOTURE_<date>` part avec, et `as_of` reste lisible
dans l'état du module. Pour un VIX intraday il faut une source temps réel ; en attendant, le
repli `TermStructureVix` — déjà intraday, déjà dans le terminal — passe avant.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Callable, Optional

from .. import config
from ..redis_state import RedisState
from .contracts import CalendarEvent, CalendarFetch, VixFetch
from .economic_calendar import is_high_impact_news_near
from .vix import VixRegime, get_vix_regime

log = logging.getLogger("cholismo.external")

CALENDAR_FIELD, CALENDAR_SOURCE = "macro_releases", "econ_feed"
VIX_FIELD, VIX_SOURCE = "vix", "cboe"

# Champs dont ce module devient PROPRIÉTAIRE quand il est actif. Deux producteurs pour un même
# champ, c'est le dernier qui écrit qui gagne — donc une valeur qui dépend de l'ordonnancement,
# c'est-à-dire de rien. La propriété est déclarée ICI, au plus près de qui publie, et
# `MockDataSource` la reçoit au montage : le mock cesse alors réellement de les produire, il
# n'est pas simplement écrasé. Conséquence assumée : si la source externe est muette, ces champs
# deviennent ABSENT et Phase 0 bloque — c'est le bon sens du fail-closed (§3), pas une panne.
OWNED_FIELDS = (CALENDAR_FIELD, VIX_FIELD)


class ExternalDataModule:
    """Manager unifié des sources externes. Voir la docstring du module pour les invariants."""

    def __init__(self, *, calendar: Optional[Any] = None, vix: Optional[Any] = None,
                 refresh_s: Optional[float] = None, max_age_s: Optional[float] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._calendar = calendar
        self._vix = vix
        self._refresh_s = refresh_s if refresh_s is not None else config.EXTERNAL_REFRESH_SECONDS
        self._max_age_s = max_age_s if max_age_s is not None else config.EXTERNAL_MAX_AGE_S
        self._clock = clock
        self._cal_cache: Optional[tuple[CalendarFetch, float]] = None
        self._vix_cache: Optional[tuple[VixFetch, float]] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._state: Optional[RedisState] = None
        self._lock = asyncio.Lock()

    # -- étage async : rafraîchissement --

    async def start(self, state: Optional[RedisState] = None) -> None:
        """Démarre le worker. Avec un `state`, il publie après chaque rafraîchissement — une
        seule écriture par cycle suffit : l'horodatage publié est celui de l'OBSERVATION, donc
        la valeur ne « rajeunit » pas en étant réécrite, et la couche de fraîcheur la fait
        vieillir toute seule entre deux cycles."""
        self._state = state
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
                if self._state is not None:
                    await self.publish(self._state)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fail-closed : le cache existant vieillit vers l'aveuglement, il n'est jamais
                # remplacé par une valeur inventée.
                log.exception("rafraîchissement externe échoué (le cache vieillit, §3)")
            await asyncio.sleep(max(1.0, self._refresh_s))

    async def refresh(self) -> dict[str, str]:
        """Un cycle fetch des deux chaînes, I/O en thread. Un échec CONSERVE l'ancien cache.
        Rend le compte rendu par source — un dict de compteurs n'est pas un message (D-056)."""
        async with self._lock:      # deux cycles concurrents écriraient le cache en désordre
            return await self._refresh()

    async def _refresh(self) -> dict[str, str]:
        now = float(self._clock())
        bilan: dict[str, str] = {}
        if self._calendar is not None:
            res = await self._essayer(self._calendar, now)
            bilan["calendrier"] = res.resume if res is not None else "fetch impossible"
            if res is not None and res.ok:
                self._cal_cache = (res, now)
        if self._vix is not None:
            res_v = await self._essayer(self._vix, now)
            bilan["vix"] = res_v.resume if res_v is not None else "fetch impossible"
            if res_v is not None and res_v.ok:
                self._vix_cache = (res_v, now)
        return bilan

    @staticmethod
    async def _essayer(provider: Any, now: float) -> Any:
        """Le fetch part en thread : une source synchrone qui bloque ne doit jamais figer la
        boucle (§7). Une exception du fournisseur ne remonte pas — elle devient une absence."""
        try:
            return await asyncio.to_thread(lambda: provider.fetch(now=now))
        except Exception:
            log.exception("source externe %s a levé", getattr(provider, "name", "?"))
            return None

    # -- étage sync : accesseurs PURS (zéro I/O, horloge injectée) --

    def _frais(self, cache: Optional[tuple[Any, float]], now: float) -> Optional[Any]:
        """Cache utilisable, ou `None` s'il est absent, fossile ou fantôme (horodaté dans le
        futur). Un souvenir n'est pas une donnée."""
        if cache is None or not isinstance(now, (int, float)) or not math.isfinite(now):
            return None
        valeur, fetched_ts = cache
        if not math.isfinite(fetched_ts) or fetched_ts > now or now - fetched_ts > self._max_age_s:
            return None
        return valeur

    def calendar_events(self, now: float) -> Optional[list[CalendarEvent]]:
        """Événements en cache. `None` = **aveugle** (jamais initialisé ou fossile) — à ne pas
        confondre avec `[]`, qui est un calendrier lu et vide, donc un état CONNU."""
        res = self._frais(self._cal_cache, now)
        return None if res is None else list(res.events or [])

    def news_near(self, now: float, window_minutes: Optional[float] = None) -> dict[str, Any]:
        """Le contrat F5 demandé : sommes-nous dans la fenêtre d'interdiction, et pourquoi ?

        **Aveugle ≠ calme.** Sans calendrier utilisable, on ne rend pas `near=False` : ce serait
        une autorisation de trader fondée sur rien. `blind=True` est rendu, et il appartient à
        l'appelant de fail-closed — comme `SAFETY_UNKNOWN` côté Porte F0 (D-050).
        """
        fenetre = (window_minutes if window_minutes is not None
                   else config.MACRO_PAUSE_WINDOW_S / 60.0)
        events = self.calendar_events(now)
        if events is None:
            return {"near": False, "blind": True, "regime": "SAFETY_UNKNOWN", "event": None,
                    "seconds_until": None,
                    "motif": "aucun calendrier utilisable (jamais chargé ou périmé) — "
                             "l'appelant doit refuser, pas conclure au calme"}
        verdict = is_high_impact_news_near(events, now, fenetre)
        verdict["blind"] = False
        verdict["motif"] = ""
        return verdict

    def vix_value(self, now: float) -> Optional[float]:
        res = self._frais(self._vix_cache, now)
        return None if res is None else res.value

    def vix_regime(self, now: float, *, previous_tier: str = "GREEN",
                   kurtosis: Optional[float] = None) -> VixRegime:
        """Régime F3. `previous_tier` vient de l'APPELANT (le moteur le détient déjà) : en garder
        une copie ici ferait deux paliers D4 qui finiraient par diverger."""
        res = self._frais(self._vix_cache, now)
        return get_vix_regime(None if res is None else res.value,
                              previous_tier=previous_tier, kurtosis=kurtosis,
                              source=res.provider if res is not None else "")

    # -- publication dans Redis, sous les noms de source que le moteur attend déjà --

    async def publish(self, state: RedisState, now: Optional[float] = None) -> list[str]:
        """Écrit les champs alimentables. Rend la liste de ce qui a été écrit.

        Un cache fossile n'écrit RIEN : le champ vieillit visiblement vers STALE puis ABSENT.
        Le republier avec un horodatage frais le blanchirait en donnée courante.
        """
        maintenant = float(self._clock()) if now is None else float(now)
        ecrits: list[str] = []
        cal = self._frais(self._cal_cache, maintenant)
        if cal is not None and cal.events is not None:
            await state.write_raw(CALENDAR_FIELD, list(cal.events), CALENDAR_SOURCE,
                                  ts=cal.observed_ts if cal.observed_ts is not None else maintenant,
                                  flags=["EXTERNAL", *cal.flags])
            ecrits.append(CALENDAR_FIELD)
        vix = self._frais(self._vix_cache, maintenant)
        if vix is not None and vix.value is not None:
            flags = ["EXTERNAL", *vix.flags]
            if vix.as_of:
                # La valeur décrit une CLÔTURE : le dire dans le drapeau, sinon elle se lit comme
                # un niveau de séance sur un canal rapide.
                flags.append(f"VIX_CLOTURE_{vix.as_of}")
            await state.write_raw(VIX_FIELD, vix.value, VIX_SOURCE,
                                  ts=vix.observed_ts if vix.observed_ts is not None else maintenant,
                                  flags=flags)
            ecrits.append(VIX_FIELD)
        return ecrits

    # -- état lisible --

    def state_dict(self, now: float) -> dict[str, Any]:
        cal, vix = self._frais(self._cal_cache, now), self._frais(self._vix_cache, now)
        return {
            "calendrier": {
                "utilisable": cal is not None,
                "resume": cal.resume if cal is not None else "aveugle — aucun calendrier utilisable",
                "provider": cal.provider if cal is not None else None,
                "fallback": bool(cal.fallback) if cal is not None else None,
                "tentatives": list(getattr(self._calendar, "attempts", [])),
            },
            "vix": {
                "utilisable": vix is not None,
                "resume": vix.resume if vix is not None else "aveugle — aucune lecture utilisable",
                "provider": vix.provider if vix is not None else None,
                "fallback": bool(vix.fallback) if vix is not None else None,
                "as_of": vix.as_of if vix is not None else None,
                "tentatives": list(getattr(self._vix, "attempts", [])),
            },
            "max_age_s": self._max_age_s, "refresh_s": self._refresh_s,
        }


def build_default(*, clock: Callable[[], float] = time.time) -> ExternalDataModule:
    """Le montage par défaut, depuis la configuration. Chaque chaîne va du plus honnête au plus
    dégradé, et tout ce qui est dégradé porte son drapeau."""
    from .economic_calendar import ChainedCalendar, FinnhubCalendar, LocalCalendarFile
    from .vix import ChainedVix, FredVix, StaticVix

    calendrier = ChainedCalendar([
        FinnhubCalendar(config.FINNHUB_API_KEY),
        LocalCalendarFile(config.EXTERNAL_CALENDAR_FILE),
    ])
    vix = ChainedVix([
        FredVix(),
        StaticVix(config.EXTERNAL_VIX_STATIC),
    ])
    return ExternalDataModule(calendar=calendrier, vix=vix, clock=clock)
