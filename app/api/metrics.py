"""The ``/metrics`` scrape endpoint.

A real route (not a mounted ASGI app) so it can take a DB session and refresh the
gauges from live data on every scrape - always accurate, restart-safe.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.deps import get_db
from app.core.metrics import CARS, ONGOING_RENTALS
from app.models import CarStatus
from app.repositories.car import SqlAlchemyCarRepository
from app.repositories.rental import SqlAlchemyRentalRepository

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
def metrics(session: Annotated[Session, Depends(get_db)]) -> Response:
    by_status = SqlAlchemyCarRepository(session).count_by_status()
    for status in CarStatus:
        CARS.labels(status=status.value).set(by_status.get(status, 0))
    ONGOING_RENTALS.set(SqlAlchemyRentalRepository(session).count_active())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
