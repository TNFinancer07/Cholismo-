"""Cholismo Terminal — backend entrypoint. FastAPI (REST + SSE), Redis (intra-session),
SQLite (append-only event store). The hot path is deterministic; AI is async-only."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .ai.tasks import AITasks
from .api import router
from .datasource.mock import MockDataSource
from .engine import Engine
from .event_store import get_store
from .log_scraper import LogTailer, nt8_daily_log_path
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
    app.state.engine = Engine(MockDataSource(), app.state.redis)
    await app.state.engine.start()
    # AI: async only, out of the hot path (CLAUDE §2.8); no keys -> explicit UNAVAILABLE.
    app.state.ai = AITasks(app.state.engine)
    await app.state.ai.start()
    # log_scraper (D-031): OBSERVATION seule (§2.1) — sur un fill NT8 DÉJÀ passé par l'humain,
    # capture un snapshot déterministe. Async non-bloquant (§7). Désactivé sans dossier NT8.
    app.state.log_scraper = _build_log_scraper(app.state.engine)
    if app.state.log_scraper is not None:
        await app.state.log_scraper.start()
    try:
        yield
    finally:
        if app.state.log_scraper is not None:
            await app.state.log_scraper.stop()
        await app.state.ai.stop()
        await app.state.engine.stop()
        await app.state.redis.close()


def _build_log_scraper(engine: Engine) -> LogTailer | None:
    """Construit le tailer NT8 si activé ET si un dossier de log est fourni. Fail-closed :
    pas de dossier → None (aucun scraper), jamais un chemin deviné."""
    if not config.LOG_SCRAPER_ENABLED or not config.NT8_LOG_DIR:
        return None

    async def _on_fill(match) -> None:
        # Un fill constaté (jamais provoqué) → capture instantanée. On log l'exécution pour
        # traçabilité ; toute erreur de capture est isolée (le tailer ne meurt pas).
        try:
            res = await capture_snapshot(engine, time.time())
            log.info("log_scraper: fill NT8 %s → snapshot %s",
                     match.instrument or "?", res.get("snapshot_id"))
        except Exception:
            log.exception("log_scraper: capture de snapshot échouée")

    return LogTailer(
        lambda: nt8_daily_log_path(config.NT8_LOG_DIR, time.time()) or "",
        _on_fill,
        poll_seconds=config.LOG_SCRAPER_POLL_SECONDS,
    )


app = FastAPI(title="Cholismo Terminal", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(router)
