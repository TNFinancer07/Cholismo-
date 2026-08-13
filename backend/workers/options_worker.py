"""
options_worker.py — Le Cerveau Lent (Slow Worker)
====================================================
Cholismo · Pont Options -> LSR v2 · architecture "Double Cerveau"

Ce script est AUTONOME : pas de FastAPI, pas de dépendance à l'application
web existante. Raison (voir décision précédente) : découplage total — un
redémarrage ou une panne du serveur qui sert le terminal ne doit jamais
affecter ce worker, et inversement. Se déploie comme un service de plus
(NSSM), au même titre qu'uvicorn et Caddy.

Rôle : interroger (ici : SIMULER) un fournisseur de données options,
calculer le facteur de conversion SPX -> ES chaque matin à 09:15 ET, et
publier le tout dans Redis pour lecture par le Fast Engine TypeScript.

Ce module NE PREND AUCUNE DÉCISION DE TRADING. Il alimente un cache lu
par des fonctions pures côté Fast Engine (voir o5TailRisk.ts et,
prochainement, lsrEngineIntegration.ts).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Configuration — tout seuil non calibré est marqué PLACEHOLDER, cohérent
# avec la discipline du reste du projet (config_risque_challenge, etc.)
# ---------------------------------------------------------------------------

NY_TZ = ZoneInfo("America/New_York")

REDIS_URL = "redis://localhost:6379/0"
REDIS_CONTEXT_KEY = "options:context:latest"
REDIS_UPDATE_CHANNEL = "options:context:updated"

POLL_INTERVAL_SECONDS = 5          # PLACEHOLDER — cadence de rafraîchissement GEX/Net Drift
CONTEXT_TTL_SECONDS = 90           # PLACEHOLDER — au-delà, le Fast Engine traite comme périmé
BASIS_CALC_HOUR = 9                # 09:15 ET, avant l'ouverture 09:30
BASIS_CALC_MINUTE = 15
VENDOR_TIMEOUT_SECONDS = 3.0       # PLACEHOLDER
MAX_CONSECUTIVE_FAILURES = 4       # PLACEHOLDER — avant passage en VENDOR_DOWN
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0

# Taux et dividende — AUCUNE source réelle connectée. Prérequis non résolu,
# documenté dans cholismo_pont_options_lsr_v2.html, section 8/10.
RISK_FREE_RATE_PLACEHOLDER = 0.045
DIVIDEND_YIELD_PLACEHOLDER = 0.013

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("options_worker")


# ---------------------------------------------------------------------------
# Contrat du fournisseur de données — interface, pas une implémentation.
# Permet de remplacer MockVendorClient par un vrai client (SpotGamma,
# Options Depth, ...) sans toucher au reste du worker.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GexSnapshot:
    """Exposition gamma par strike, en unités ES (déjà converties côté fournisseur
    réel, ou par nous via BasisCalculator pour le mock)."""
    gex_local_by_strike: dict[str, float]   # clé = strike ES en texte, valeur = M$/1%
    gamma_zero_es: float
    put_wall_es: float
    call_wall_es: float


@dataclass(frozen=True)
class NetDriftSnapshot:
    direction: Optional[str]   # "up" | "down" | None (plat/haché)
    crossover_ts_ms: Optional[int]
    source_confirmed: bool     # False tant que la source SPY/SPX n'est pas confirmée
                                # (voir Pont v2 §4 — badgé "QQQ only" sur la capture)


class OptionsVendorClient(Protocol):
    """Contrat que tout client fournisseur (mock ou réel) doit respecter."""

    async def fetch_gex(self) -> GexSnapshot: ...
    async def fetch_net_drift(self) -> NetDriftSnapshot: ...
    async def fetch_spx_reference_levels(self) -> dict[str, float]:
        """Niveaux bruts en SPX, avant conversion ES."""
        ...


class VendorUnavailableError(Exception):
    """Levée par un client vendor sur timeout, erreur HTTP, ou donnée aberrante.
    Jamais laissée remonter au-delà du polling loop — capturée et transformée
    en statut VENDOR_DOWN après MAX_CONSECUTIVE_FAILURES."""


class MockVendorClient:
    """
    SIMULATION explicite — aucun appel réseau réel. Sert à valider toute la
    mécanique (polling, TTL, publication Redis, circuit breaker) sans
    dépendre d'un abonnement fournisseur. Interface identique à un vrai
    client : le remplacer ne touche à rien d'autre dans ce fichier.

    Injection d'un taux d'échec configurable pour tester le circuit breaker.
    """

    def __init__(self, *, seed: int = 2026, failure_rate: float = 0.0) -> None:
        self._rng = random.Random(seed)
        self._failure_rate = failure_rate
        self._spx_spot = 6004.0  # point de départ réaliste, dérive légèrement au fil du temps

    async def _maybe_fail(self) -> None:
        await asyncio.sleep(0.01)  # simule une latence réseau minimale
        if self._rng.random() < self._failure_rate:
            raise VendorUnavailableError("mock: panne simulée du fournisseur")

    async def fetch_gex(self) -> GexSnapshot:
        await self._maybe_fail()
        self._spx_spot += self._rng.uniform(-1.5, 1.5)
        strikes = {}
        for i in range(-6, 7):
            strike = round(self._spx_spot / 5) * 5 + i * 25
            # motif : positif loin du spot, s'approche de zéro près du spot
            dist = abs(strike - self._spx_spot) / 120
            sign = 1 if strike < self._spx_spot - 15 or strike > self._spx_spot + 15 else -1
            strikes[str(strike)] = round(sign * (80 + dist * 400) * self._rng.uniform(0.8, 1.2), 1)
        return GexSnapshot(
            gex_local_by_strike=strikes,
            gamma_zero_es=round(self._spx_spot + 3.2, 2),
            put_wall_es=round(self._spx_spot - 12.5, 2),
            call_wall_es=round(self._spx_spot + 11.75, 2),
        )

    async def fetch_net_drift(self) -> NetDriftSnapshot:
        await self._maybe_fail()
        r = self._rng.random()
        direction = "up" if r > 0.6 else ("down" if r < 0.4 else None)
        return NetDriftSnapshot(
            direction=direction,
            crossover_ts_ms=int(time.time() * 1000) if direction else None,
            source_confirmed=False,  # prérequis non résolu — voir Pont v2 §4
        )

    async def fetch_spx_reference_levels(self) -> dict[str, float]:
        await self._maybe_fail()
        return {
            "put_wall_spx": round(self._spx_spot - 12.5, 2),
            "call_wall_spx": round(self._spx_spot + 11.75, 2),
            "gamma_zero_spx": round(self._spx_spot + 3.2, 2),
        }


# ---------------------------------------------------------------------------
# Conversion SPX -> ES — fonctions pures, testables isolément.
# Formule et ordre de grandeur vérifiés dans cholismo_pont_options_lsr_v2.html
# (section 6 du document v1) : ES = SPX * exp((r - q) * T), arrondi au tick.
# ---------------------------------------------------------------------------

TICK_ES = 0.25


def compute_basis_factor(risk_free_rate: float, dividend_yield: float, time_to_expiry_years: float) -> float:
    """Facteur multiplicatif SPX -> ES. Pure, déterministe."""
    if time_to_expiry_years < 0:
        raise ValueError("time_to_expiry_years doit être >= 0")
    return math.exp((risk_free_rate - dividend_yield) * time_to_expiry_years)


def convert_spx_to_es(spx_level: float, factor: float) -> float:
    """Convertit un niveau SPX en ES, arrondi au tick le plus proche. Pure."""
    raw = spx_level * factor
    return round(raw / TICK_ES) * TICK_ES


def years_to_next_quarterly_expiry(now: datetime) -> float:
    """
    Temps jusqu'à la prochaine échéance trimestrielle ES (3e vendredi de
    mars/juin/septembre/décembre) — approximation simple, suffisante pour
    la conversion de base. PLACEHOLDER : ne gère pas les jours fériés.
    """
    quarter_months = [3, 6, 9, 12]
    year = now.year
    for m in quarter_months:
        candidate = _third_friday(year, m)
        if candidate > now:
            return max((candidate - now).total_seconds() / (365.0 * 24 * 3600), 1e-6)
    candidate = _third_friday(year + 1, 3)
    return (candidate - now).total_seconds() / (365.0 * 24 * 3600)


def _third_friday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1, 16, 0, tzinfo=NY_TZ)
    friday = 4  # lundi=0 ... vendredi=4
    offset = (friday - d.weekday()) % 7
    d += timedelta(days=offset)
    d += timedelta(days=14)
    return d


@dataclass(frozen=True)
class BasisResult:
    factor: float
    computed_at_ms: int
    time_to_expiry_years: float
    risk_free_rate: float
    dividend_yield: float
    is_placeholder_rates: bool = True  # r et q ne sont pas encore une vraie source


class BasisCalculator:
    """Calcule et republie le facteur de conversion. Planifié à 09:15 ET,
    mais exposé comme méthode indépendante — testable sans horloge."""

    def compute(self, now: Optional[datetime] = None) -> BasisResult:
        now = now or datetime.now(NY_TZ)
        t = years_to_next_quarterly_expiry(now)
        factor = compute_basis_factor(RISK_FREE_RATE_PLACEHOLDER, DIVIDEND_YIELD_PLACEHOLDER, t)
        return BasisResult(
            factor=factor,
            computed_at_ms=int(now.timestamp() * 1000),
            time_to_expiry_years=t,
            risk_free_rate=RISK_FREE_RATE_PLACEHOLDER,
            dividend_yield=DIVIDEND_YIELD_PLACEHOLDER,
        )


# ---------------------------------------------------------------------------
# Circuit breaker — distingue "lent ce cycle" de "en panne confirmée".
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreaker:
    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES
    backoff_base_seconds: float = BACKOFF_BASE_SECONDS
    backoff_max_seconds: float = BACKOFF_MAX_SECONDS
    _consecutive_failures: int = field(default=0, init=False)

    @property
    def is_down(self) -> bool:
        return self._consecutive_failures >= self.max_consecutive_failures

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> int:
        self._consecutive_failures += 1
        return self._consecutive_failures

    def backoff_seconds(self) -> float:
        """Backoff exponentiel borné. Pure sur l'état courant."""
        if self._consecutive_failures == 0:
            return 0.0
        return min(
            self.backoff_base_seconds * (2 ** (self._consecutive_failures - 1)),
            self.backoff_max_seconds,
        )


# ---------------------------------------------------------------------------
# Publication Redis — écrit le contexte, publie l'événement de mise à jour.
# ---------------------------------------------------------------------------

class ContextPublisher:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def publish_ok(
        self,
        gex: GexSnapshot,
        net_drift: NetDriftSnapshot,
        basis: Optional[BasisResult],
        source_vendor: str,
    ) -> None:
        payload = {
            "status": "OK",
            "gexLocalByStrike": gex.gex_local_by_strike,
            "gammaZeroEs": gex.gamma_zero_es,
            "putWallEs": gex.put_wall_es,
            "callWallEs": gex.call_wall_es,
            "netDriftCrossover": {
                "direction": net_drift.direction,
                "ts": net_drift.crossover_ts_ms,
                "sourceConfirmed": net_drift.source_confirmed,
            },
            "conversionFactorUsed": basis.factor if basis else None,
            "computedAt": int(time.time() * 1000),
            "sourceVendor": source_vendor,
        }
        await self._write_and_publish(payload)

    async def publish_vendor_down(self, source_vendor: str, consecutive_failures: int) -> None:
        payload = {
            "status": "VENDOR_DOWN",
            "gexLocalByStrike": {},
            "gammaZeroEs": None,
            "putWallEs": None,
            "callWallEs": None,
            "netDriftCrossover": {"direction": None, "ts": None, "sourceConfirmed": False},
            "conversionFactorUsed": None,
            "computedAt": int(time.time() * 1000),
            "sourceVendor": source_vendor,
            "consecutiveFailures": consecutive_failures,
        }
        await self._write_and_publish(payload)
        log.warning("VENDOR_DOWN publié après %d échecs consécutifs", consecutive_failures)

    async def _write_and_publish(self, payload: dict) -> None:
        raw = json.dumps(payload)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(REDIS_CONTEXT_KEY, raw, ex=CONTEXT_TTL_SECONDS)
            pipe.publish(REDIS_UPDATE_CHANNEL, raw)
            await pipe.execute()


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

class OptionsWorker:
    def __init__(
        self,
        vendor: OptionsVendorClient,
        redis_client: aioredis.Redis,
        *,
        source_vendor_name: str = "mock",
    ) -> None:
        self._vendor = vendor
        self._publisher = ContextPublisher(redis_client)
        self._breaker = CircuitBreaker()
        self._basis_calc = BasisCalculator()
        self._source_vendor_name = source_vendor_name
        self._last_basis: Optional[BasisResult] = None
        self._last_basis_date: Optional[str] = None
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def _poll_once(self) -> None:
        try:
            gex, net_drift = await asyncio.wait_for(
                asyncio.gather(self._vendor.fetch_gex(), self._vendor.fetch_net_drift()),
                timeout=VENDOR_TIMEOUT_SECONDS,
            )
        except (VendorUnavailableError, asyncio.TimeoutError) as exc:
            n = self._breaker.record_failure()
            log.warning("échec fournisseur (%d/%d) : %s", n, self._breaker.max_consecutive_failures, exc)
            if self._breaker.is_down:
                await self._publisher.publish_vendor_down(self._source_vendor_name, n)
            return

        self._breaker.record_success()
        self._maybe_recompute_basis()
        await self._publisher.publish_ok(gex, net_drift, self._last_basis, self._source_vendor_name)
        log.info(
            "contexte publié — flip ES %.2f · put wall %.2f · call wall %.2f · drift %s",
            gex.gamma_zero_es, gex.put_wall_es, gex.call_wall_es, net_drift.direction,
        )

    def _maybe_recompute_basis(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(NY_TZ)
        today = now.date().isoformat()
        already_done_today = self._last_basis_date == today
        hour_reached = (now.hour, now.minute) >= (BASIS_CALC_HOUR, BASIS_CALC_MINUTE)
        if not already_done_today and hour_reached:
            self._last_basis = self._basis_calc.compute(now)
            self._last_basis_date = today
            log.info(
                "facteur de base recalculé : %.6f (T=%.4f an, r=%.3f, q=%.3f) — PLACEHOLDER r/q",
                self._last_basis.factor,
                self._last_basis.time_to_expiry_years,
                self._last_basis.risk_free_rate,
                self._last_basis.dividend_yield,
            )

    async def run_forever(self, *, max_cycles: Optional[int] = None) -> None:
        cycles = 0
        while not self._stop.is_set():
            await self._poll_once()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            backoff = self._breaker.backoff_seconds()
            wait_s = max(POLL_INTERVAL_SECONDS, backoff)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_s)
            except asyncio.TimeoutError:
                pass


async def main() -> None:
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    vendor = MockVendorClient(failure_rate=0.0)
    worker = OptionsWorker(vendor, redis_client, source_vendor_name="mock")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            pass  # Windows

    log.info("options_worker démarré — mode simulation, cadence %ss", POLL_INTERVAL_SECONDS)
    try:
        await worker.run_forever()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
