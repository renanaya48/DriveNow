"""Business logic for rentals.

Plain Python: no FastAPI. Owns the transaction via :class:`UnitOfWork`; publishes
domain events best-effort after commit. Locking order is always CAR then RENTAL.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from app.core.unit_of_work import UnitOfWork
from app.messaging.publisher import EventPublisher
from app.models import CarStatus, Rental
from app.repositories.car import CarRepository
from app.repositories.rental import RentalRepository
from app.schemas.rental import RentalCreate
from app.services.exceptions import (
    CarNotAvailableError,
    CarNotFoundError,
    RentalAlreadyEndedError,
    RentalDateError,
    RentalNotFoundError,
)

logger = logging.getLogger(__name__)


class RentalService:
    """Register and end rentals."""

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

    def register_rental(self, dto: RentalCreate) -> Rental:
        # Not a reservation system: a rental starts today. (end_date >= today
        # then follows from the DTO's end_date >= start_date rule.)
        today = date.today()
        if dto.start_date != today:
            raise RentalDateError("a rental must start today")

        with self._transaction():
            car = self._cars.get_by_id_for_update(dto.car_id)
            if car is None:
                raise CarNotFoundError(f"car {dto.car_id} not found")
            if car.status is not CarStatus.AVAILABLE:
                raise CarNotAvailableError(
                    f"car {dto.car_id} is {car.status.value}"
                )
            # Defence-in-depth: catch an inconsistent row (AVAILABLE yet an open
            # rental exists) as a clean domain error, not a raw IntegrityError.
            if self._rentals.get_active_by_car(car.id) is not None:
                raise CarNotAvailableError(
                    f"car {dto.car_id} already has an active rental"
                )

            rental = self._rentals.add(
                Rental(
                    car_id=car.id,
                    customer_name=dto.customer_name,
                    start_date=dto.start_date,
                    end_date=dto.end_date,
                )
            )
            car.status = CarStatus.IN_USE
            self._cars.update(car)

        self._publish(
            "rental.started", {"rental_id": rental.id, "car_id": car.id}
        )
        return rental

    def end_rental(self, rental_id: int) -> Rental:
        today = date.today()
        with self._transaction():
            candidate = self._rentals.get_by_id(rental_id)
            if candidate is None:
                raise RentalNotFoundError(f"rental {rental_id} not found")

            # Lock CAR first, then RENTAL (global ordering); re-read under lock.
            car = self._cars.get_by_id_for_update(candidate.car_id)
            if car is None:  # unreachable in practice - an active rental's car exists
                raise CarNotFoundError(f"car {candidate.car_id} not found")
            rental = self._rentals.get_by_id_for_update(rental_id)
            if rental is None:  # pragma: no cover - lost between the two reads
                raise RentalNotFoundError(f"rental {rental_id} not found")

            if rental.returned_date is not None:
                raise RentalAlreadyEndedError(
                    f"rental {rental_id} has already been ended"
                )
            if today < rental.start_date:
                raise RentalDateError("cannot return a rental before it starts")

            rental.returned_date = today
            car.status = CarStatus.AVAILABLE
            self._rentals.update(rental)
            self._cars.update(car)

        self._publish(
            "rental.ended", {"rental_id": rental.id, "car_id": car.id}
        )
        return rental
