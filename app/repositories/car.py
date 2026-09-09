"""Data access for :class:`~app.models.car.Car`.

Plain Python - no FastAPI, no business rules. Methods ``flush`` but never
``commit``; the transaction is owned by the service layer. "Not found" is
signalled by returning ``None``, never by raising.

Removal is a **soft delete**: ``soft_delete`` stamps ``Car.deleted_at`` and every
read here filters those rows out, so rental history is preserved and a retired
car is still reachable through ``Rental.car``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Car, CarStatus


@runtime_checkable
class CarRepository(Protocol):
    """Persistence operations for cars (the seam the service depends on)."""

    def add(self, car: Car) -> Car: ...

    def get_by_id(self, car_id: int) -> Car | None: ...

    def get_by_id_for_update(self, car_id: int) -> Car | None: ...

    def list(self, *, status: CarStatus | None = None) -> Sequence[Car]: ...

    def update(self, car: Car) -> Car: ...

    def soft_delete(self, car: Car) -> Car: ...

    def count_by_status(self) -> dict[CarStatus, int]: ...


class SqlAlchemyCarRepository:
    """SQLAlchemy-backed :class:`CarRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, car: Car) -> Car:
        self._session.add(car)
        self._session.flush()  # assign PK / server defaults without committing
        return car

    def get_by_id(self, car_id: int) -> Car | None:
        stmt = select(Car).where(Car.id == car_id, Car.deleted_at.is_(None))
        return self._session.scalars(stmt).first()

    def get_by_id_for_update(self, car_id: int) -> Car | None:
        """Fetch a live car with a row lock.

        Emits ``SELECT ... FOR UPDATE`` on PostgreSQL so a concurrent rental
        registration for the same car serialises behind this transaction. On
        SQLite ``with_for_update`` is a no-op (single-writer anyway).

        ``populate_existing`` forces the row already in the session's identity
        map to be refreshed from this locked read, so "lock then re-validate"
        actually sees post-lock state.
        """
        stmt = (
            select(Car)
            .where(Car.id == car_id, Car.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.scalars(stmt).first()

    def list(self, *, status: CarStatus | None = None) -> Sequence[Car]:
        stmt = select(Car).where(Car.deleted_at.is_(None)).order_by(Car.id)
        if status is not None:
            stmt = stmt.where(Car.status == status)
        return self._session.scalars(stmt).all()

    def update(self, car: Car) -> Car:
        # ``car`` is already tracked by the session; flush to surface constraint
        # errors now rather than at commit time.
        self._session.flush()
        return car

    def soft_delete(self, car: Car) -> Car:
        """Retire a car from the fleet without deleting the row."""
        car.deleted_at = datetime.now(UTC)
        self._session.flush()
        return car

    def count_by_status(self) -> dict[CarStatus, int]:
        """Count non-deleted cars grouped by status (for the metrics scrape)."""
        stmt = (
            select(Car.status, func.count())
            .where(Car.deleted_at.is_(None))
            .group_by(Car.status)
        )
        return {status: n for status, n in self._session.execute(stmt)}
