"""Cholismo Terminal — backend entrypoint. FastAPI (REST + SSE), Redis (intra-session),
SQLite (append-only event store). The hot path is deterministic; AI is async-only."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai.tasks import AITasks
from .api import router
from .datasource.mock import MockDataSource
from .engine import Engine
from .event_store import get_store
from .redis_state import RedisState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


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
    try:
        yield
    finally:
        await app.state.ai.stop()
        await app.state.engine.stop()
        await app.state.redis.close()


app = FastAPI(title="Cholismo Terminal", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(router)
