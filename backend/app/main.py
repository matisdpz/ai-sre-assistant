"""Application factory. Run with: uvicorn --factory app.main:create_app"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai import DiagnosisProvider, GeminiProvider
from app.api import diagnosis, health, incidents, ingest, rules, services
from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def build_provider(settings: Settings) -> DiagnosisProvider | None:
    """The AI provider, or None when no key is configured (the feature is then off)."""
    if settings.gemini_api_key is None:
        return None
    return GeminiProvider(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        timeout=settings.ai_timeout_seconds,
    )


def create_app(
    settings: Settings | None = None, diagnosis_provider: DiagnosisProvider | None = None
) -> FastAPI:
    """`diagnosis_provider` lets tests inject a fake; by default it comes from settings."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        provider = app.state.diagnosis_provider
        logger.info(
            "startup",
            extra={
                "app_env": settings.app_env,
                "ai_diagnosis": f"{provider.name}:{provider.model}" if provider else "disabled",
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
    app.state.diagnosis_provider = diagnosis_provider or build_provider(settings)
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(services.router)
    app.include_router(incidents.router)
    app.include_router(rules.router)
    app.include_router(diagnosis.router)
    return app
