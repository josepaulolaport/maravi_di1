"""The HTTP application (integrator; plan §1, X3).

`create_app` builds the FastAPI app; uvicorn runs it as a factory, so nothing reads the environment
at import time::

    uvicorn di1.main:create_app --factory

The lifespan creates the process's one engine and session factory (platform) and disposes of the
engine at shutdown; it first configures logging (``LOG_LEVEL``), once per process. The app's clock
(OQ-14) is the system clock unless a test passes a fixed one. Every error answers RFC 9457
problem+json (``composition.errors``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from di1.composition.errors import install_problem_handlers
from di1.composition.health import router as health_router
from di1.composition.routers import include_routers
from di1.platform.clock import SystemClock
from di1.platform.config import Settings, get_logging_settings, get_settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.observability.logging_setup import configure_logging
from di1.shared.clock import Clock

HEALTH_TIMEOUT_SECONDS = 2.0
"""How long ``/health`` waits for PostgreSQL (connection and ``SELECT 1``) before answering 503."""


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    health_timeout: float = HEALTH_TIMEOUT_SECONDS,
) -> FastAPI:
    """The app; ``settings`` defaults to the environment, read when the app starts, and
    ``clock`` to `SystemClock`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(get_logging_settings())
        engine = create_engine(settings if settings is not None else get_settings())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Maravi DI1 Backoffice", lifespan=lifespan)
    app.state.clock = clock if clock is not None else SystemClock()
    app.state.health_timeout = health_timeout
    install_problem_handlers(app)
    app.include_router(health_router)
    include_routers(app)
    return app
