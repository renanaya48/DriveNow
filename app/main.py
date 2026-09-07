"""Application entrypoint: builds and configures the FastAPI app.

This module stays thin on purpose. Routers, error handling, logging and metrics
are each defined in their own module and only wired together here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.api import cars, health, rentals
from app.api.errors import register_exception_handlers
from app.core import metrics as _metrics  # noqa: F401  (import registers Prometheus metrics)
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown hooks. DB and message-queue wiring is added later."""
    configure_logging(get_settings())
    yield


def create_app() -> FastAPI:
    """Application factory. Keeping it a function makes testing straightforward."""
    app = FastAPI(
        title="DriveNow Vehicle Management",
        version="0.1.0",
        description="Internal system to manage a car rental fleet.",
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(cars.router)
    app.include_router(rentals.router)

    # Prometheus scrape endpoint. Metric definitions live in app/core/metrics.py.
    app.mount("/metrics", make_asgi_app())

    return app


app = create_app()
