"""Cholismo Terminal — backend entrypoint. FastAPI (REST + SSE), Redis (intra-session),
SQLite (append-only event store). The hot path is deterministic; AI is async-only."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .account_provider import MockAccountProvider, NT8FileAccountProvider
from .ai.tasks import AITasks
from .api import router
from .datasource.mock import MockDataSource
from .datasource.replay import ReplayDataSource
from .macro_news import MacroNewsProvider
from .risk_sizer import APEX_EOD_50K, apex_eod_account
from .engine import Engine
from .event_store import get_store
from .log_scraper import LogTailer, nt8_daily_log_path, startup_report
from .redis_state import RedisState
from .snapshot import capture_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("cholismo.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = RedisState()
    get_store()  # create DB + append-only triggers up front
    # MarketDataSource is the single swappable seam (CLAUDE §4): replace MockDataSource
    # with a real feed implementation without touching the engine.
    # Source de compte (D-047/D-048) : NT8FileAccountProvider si un export NinjaTrader est
    # configuré (NT8_ACCOUNT_FILE) — vraies photos datées par le mtime, boucle async démarrée
    # ci-dessous ; sinon MockAccountProvider `always_fresh` = broker SIMULÉ du stack démo
    # (Apex 50K EOD, jour neuf). Sans source, AUCUN manifeste ne sort (à l'aveugle = non, §3).
    if config.NT8_ACCOUNT_FILE:
        app.state.account_provider = NT8FileAccountProvider(
            config.NT8_ACCOUNT_FILE, preset=APEX_EOD_50K)
    else:
        app.state.account_provider = MockAccountProvider(
            state=apex_eod_account(APEX_EOD_50K), always_fresh=True)
    # Calendrier macro (D-050) : porte F0 active seulement si un flux est configuré — sans lui,
    # la protection de facto reste le couplage news du détecteur D-028 + le blackout humain.
    app.state.news_provider = (MacroNewsProvider(config.MACRO_NEWS_FEED_URL)
                               if config.MACRO_NEWS_FEED_URL else None)
    # Le mode replay se choisit au démarrage, par la couture unique (§4) : le moteur ne sait
    # pas laquelle des trois sources est branchée. `REPLAY_FILE` absent = source mock.
    if config.REPLAY_FILE:
        app.state.datasource = ReplayDataSource(config.REPLAY_FILE, speed=config.REPLAY_SPEED,
                                                autoplay=config.REPLAY_AUTOPLAY)
        log.warning("MODE REPLAY : %s — les prints sont REJOUÉS, pas du direct (source=replay)",
                    config.REPLAY_FILE)
    else:
        app.state.datasource = MockDataSource()
    app.state.engine = Engine(app.state.datasource, app.state.redis,
                              account_provider=app.state.account_provider,
                              news_provider=app.state.news_provider)
    if isinstance(app.state.account_provider, NT8FileAccountProvider):
        await app.state.account_provider.start()
    if app.state.news_provider is not None:
        await app.state.news_provider.start()
    await app.state.engine.start()
    # AI: async only, out of the hot path (CLAUDE §2.8); no keys -> explicit UNAVAILABLE.
    app.state.ai = AITasks(app.state.engine)
    await app.state.ai.start()
    # log_scraper (D-031): OBSERVATION seule (§2.1) — sur un fill NT8 DÉJÀ passé par l'humain,
    # capture un snapshot déterministe. Async non-bloquant (§7). Désactivé sans dossier NT8.
    # Diagnostic de démarrage actionnable : dit s'il est actif, quel fichier il suit, sinon
    # comment l'activer — l'opérateur sait tout de suite sans lire le code (§polish).
    log.info(startup_report(config.LOG_SCRAPER_ENABLED, config.NT8_LOG_DIR))
    app.state.log_scraper = _build_log_scraper(app.state.engine)
    if app.state.log_scraper is not None:
        await app.state.log_scraper.start()
    try:
        yield
    finally:
        if app.state.log_scraper is not None:
            await app.state.log_scraper.stop()
        if isinstance(app.state.account_provider, NT8FileAccountProvider):
            await app.state.account_provider.stop()          # sortie propre : boucle de poll annulée
        if app.state.news_provider is not None:
            await app.state.news_provider.stop()
        await app.state.ai.stop()
        await app.state.engine.stop()
        await app.state.redis.close()


def _build_log_scraper(engine: Engine) -> LogTailer | None:
    """Construit le tailer NT8 si activé ET si un dossier de log est fourni. Fail-closed :
    pas de dossier → None (aucun scraper), jamais un chemin deviné."""
    if not config.LOG_SCRAPER_ENABLED or not config.NT8_LOG_DIR:
        return None

    async def _on_fill(match) -> None:
        # Un fill constaté (jamais provoqué) → capture instantanée. Le fill est EMBARQUÉ dans le
        # snapshot (Trade Reconciliator D-033). Confirmation console actionnable : l'opérateur
        # voit le côté, l'instrument, le prix, et le CHEMIN écrit. Toute erreur de capture est
        # isolée (le tailer survit) et dit quoi vérifier.
        price = "?" if match.price is None else match.price
        now = time.time()
        fill = {"instrument": match.instrument, "side": match.side, "price": match.price,
                "quantity": match.quantity, "ts": now, "raw": match.raw}
        try:
            res = await capture_snapshot(engine, now, fill=fill)
            log.info("log_scraper: fill NT8 détecté (%s %s @ %s) → snapshot ÉCRIT : %s",
                     match.side or "?", match.instrument or "?", price, res.get("json_path"))
        except Exception:
            log.exception("log_scraper: fill détecté (%s @ %s) mais capture de snapshot "
                          "ÉCHOUÉE — vérifier SNAPSHOT_DIR (droits d'écriture / espace disque)",
                          match.instrument or "?", price)

    return LogTailer(
        lambda: nt8_daily_log_path(config.NT8_LOG_DIR, time.time()) or "",
        _on_fill,
        poll_seconds=config.LOG_SCRAPER_POLL_SECONDS,
    )


app = FastAPI(title="Cholismo Terminal", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(router)
