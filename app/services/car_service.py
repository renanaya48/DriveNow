"""Business logic for cars.

Plain Python: no FastAPI. The service orchestrates repositories, enforces the
business invariants, owns the transaction (via :class:`UnitOfWork`) and publishes
domain events best-effort after commit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from app.core.unit_of_work import UnitOfWork
from app.messaging.publisher import EventPublisher
from app.models import Car, CarStatus
from app.repositories.car import CarRepository
from app.repositories.rental import RentalRepository
from app.schemas.car import CarCreate, CarUpdate
from app.services.exceptions import (
    CarHasActiveRentalError,
    CarNotFoundError,
    CarStatusTransitionError,
)

logger = logging.getLogger(__name__)

# Which target statuses `update_car` may set, keyed by the car's current status.
# AVAILABLE <-> UNDER_MAINTENANCE only; IN_USE is entered/left solely through the
# rental lifecycle.
_ALLOWED_STATUS_TARGETS: dict[CarStatus, set[CarStatus]] = {
    CarStatus.AVAILABLE: {CarStatus.AVAILABLE, CarStatus.UNDER_MAINTENANCE},
    CarStatus.UNDER_MAINTENANCE: {CarStatus.UNDER_MAINTENANCE, CarStatus.AVAILABLE},
    CarStatus.IN_USE: {CarStatus.IN_USE},
}


class CarService:
    """Add / update / list / delete cars."""

    def __init__(
        self,
        uow: UnitOfWork,
        cars: CarRepository,
        rentals: RentalRepository,
        publisher: EventPublisher,
    ) -> None:
        self._uow = uow
        self._cars = cars
        self._rentals = rentals
        self._publisher = publisher

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            self._publisher.publish(event_type, payload)
        except Exception:  # best-effort - never fail the operation over an event
            logger.exception("failed to publish %s", event_type)

    def add_car(self, dto: CarCreate) -> Car:
        with self._transaction():
            car = self._cars.add(Car(model=dto.model, year=dto.year))
        logger.info(
            "car added car_id=%s model=%r year=%s", car.id, car.model, car.year
        )
        self._publish("car.added", {"car_id": car.id})
        return car

    def update_car(self, car_id: int, dto: CarUpdate) -> Car:
        requested = dto.model_dump(exclude_unset=True)
        with self._transaction():
            car = self._cars.get_by_id_for_update(car_id)
            if car is None:
                raise CarNotFoundError(f"car {car_id} not found")

            actual = {k: v for k, v in requested.items() if getattr(car, k) != v}
            if not actual:
                return car  # no real change: no write, no event

            new_status = actual.get("status")
            if (
                new_status is not None
                and new_status not in _ALLOWED_STATUS_TARGETS[car.status]
            ):
                raise CarStatusTransitionError(
                    f"cannot change status from {car.status.value} to "
                    f"{new_status.value} via update"
                )

            for field, value in actual.items():
                setattr(car, field, value)
            self._cars.update(car)

        changed = sorted(actual)
        logger.info("car updated car_id=%s changed=%s", car.id, changed)
        self._publish("car.updated", {"car_id": car.id, "changed": changed})
        return car

    def list_cars(self, *, status: CarStatus | None = None) -> Sequence[Car]:
        return self._cars.list(status=status)

    def delete_car(self, car_id: int) -> Car:
        with self._transaction():
            car = self._cars.get_by_id_for_update(car_id)
            if car is None:
                raise CarNotFoundError(f"car {car_id} not found")
            if self._rentals.get_active_by_car(car_id) is not None:
                raise CarHasActiveRentalError(
                    f"car {car_id} has an active rental and cannot be removed"
                )
            self._cars.soft_delete(car)
        logger.info("car retired car_id=%s", car.id)
        self._publish("car.deleted", {"car_id": car.id})
        return car
