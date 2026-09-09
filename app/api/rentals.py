"""Rentals router - thin HTTP surface over ``RentalService``.

Each route: parse -> call one service method -> return a DTO. No business rules
here; domain errors become HTTP status codes in ``app/api/errors.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import RentalSvc
from app.schemas.rental import RentalCreate, RentalRead

router = APIRouter(prefix="/rentals", tags=["rentals"])

RentalId = Annotated[int, Path(gt=0)]


@router.post("", status_code=201, summary="Register a rental")
def register_rental(dto: RentalCreate, service: RentalSvc) -> RentalRead:
    return RentalRead.model_validate(service.register_rental(dto))


@router.post("/{rental_id}/end", summary="End a rental and free the car")
def end_rental(rental_id: RentalId, service: RentalSvc) -> RentalRead:
    return RentalRead.model_validate(service.end_rental(rental_id))
