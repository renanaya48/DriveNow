"""Cars router - thin HTTP surface over ``CarService``.

Each route: parse (FastAPI + DTO) -> call one service method -> return a DTO.
No business rules here; domain errors become HTTP status codes in
``app/api/errors.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.deps import CarSvc
from app.models import CarStatus
from app.schemas.car import CarCreate, CarRead, CarUpdate

router = APIRouter(prefix="/cars", tags=["cars"])

CarId = Annotated[int, Path(gt=0)]


@router.post("", status_code=201, summary="Add a car")
def add_car(dto: CarCreate, service: CarSvc) -> CarRead:
    return CarRead.model_validate(service.add_car(dto))


@router.get("", summary="List cars, optionally filtered by status")
def list_cars(
    service: CarSvc,
    status: Annotated[CarStatus | None, Query()] = None,
) -> list[CarRead]:
    return [CarRead.model_validate(car) for car in service.list_cars(status=status)]


@router.patch("/{car_id}", summary="Update car details")
def update_car(car_id: CarId, dto: CarUpdate, service: CarSvc) -> CarRead:
    return CarRead.model_validate(service.update_car(car_id, dto))


@router.delete("/{car_id}", status_code=204, summary="Retire a car (soft delete)")
def delete_car(car_id: CarId, service: CarSvc) -> Response:
    service.delete_car(car_id)
    return Response(status_code=204)
