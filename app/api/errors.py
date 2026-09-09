"""Translate domain exceptions into HTTP responses.

This is the only place that knows both the domain errors and HTTP status codes,
keeping that mapping out of both the services and the routers.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.exceptions import (
    CarHasActiveRentalError,
    CarNotAvailableError,
    CarNotFoundError,
    CarStatusTransitionError,
    DomainError,
    RentalAlreadyEndedError,
    RentalDateError,
    RentalNotFoundError,
)

logger = logging.getLogger(__name__)

_STATUS_MAP: dict[type[DomainError], int] = {
    CarNotFoundError: 404,
    RentalNotFoundError: 404,
    CarNotAvailableError: 409,
    CarStatusTransitionError: 409,
    CarHasActiveRentalError: 409,
    RentalAlreadyEndedError: 409,
    RentalDateError: 422,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status_code = _STATUS_MAP.get(type(exc), 400)
        logger.warning(
            "Domain error on %s %s: %s", request.method, request.url.path, exc
        )
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})
