"""Application factory. Run with: uvicorn --factory app.main:create_app"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, ingest
from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        logger.info(
            "startup",
            extra={
                "app_env": settings.app_env,
                "database": engine.url.render_as_string(hide_password=True),
            },
        )
        try:
            yield
        finally:
            # Close pooled connections so Postgres does not keep idle sessions open.
            engine.dispose()
            logger.info("shutdown")

    app = FastAPI(title="AI SRE Assistant", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(ingest.router)
    return app
