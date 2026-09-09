"""Data access for :class:`~app.models.rental.Rental`.

Plain Python - no FastAPI, no business rules. Methods ``flush`` but never
``commit``; the transaction is owned by the service layer. "Not found" is
signalled by returning ``None``, never by raising.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Rental


@runtime_checkable
class RentalRepository(Protocol):
    """Persistence operations for rentals (the seam the service depends on)."""

    def add(self, rental: Rental) -> Rental: ...

    def get_by_id(self, rental_id: int) -> Rental | None: ...

    def get_by_id_for_update(self, rental_id: int) -> Rental | None: ...

    def get_active_by_car(self, car_id: int) -> Rental | None: ...

    def list_active(self) -> Sequence[Rental]: ...

    def update(self, rental: Rental) -> Rental: ...

    def count_active(self) -> int: ...


class SqlAlchemyRentalRepository:
    """SQLAlchemy-backed :class:`RentalRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, rental: Rental) -> Rental:
        self._session.add(rental)
        self._session.flush()  # assign PK / server defaults without committing
        return rental

    def get_by_id(self, rental_id: int) -> Rental | None:
        return self._session.get(Rental, rental_id)

    def get_by_id_for_update(self, rental_id: int) -> Rental | None:
        """Fetch a rental with a row lock (``SELECT ... FOR UPDATE`` on
        PostgreSQL; no-op on SQLite).

        ``populate_existing`` refreshes an identity-map row from this locked
        read, so validation after the lock sees post-lock state.
        """
        stmt = (
            select(Rental)
            .where(Rental.id == rental_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.scalars(stmt).first()

    def get_active_by_car(self, car_id: int) -> Rental | None:
        """The open rental for a car (``returned_date IS NULL``), if any."""
        stmt = (
            select(Rental)
            .where(Rental.car_id == car_id, Rental.returned_date.is_(None))
            .order_by(Rental.id.desc())
        )
        return self._session.scalars(stmt).first()

    def list_active(self) -> Sequence[Rental]:
        stmt = (
            select(Rental)
            .where(Rental.returned_date.is_(None))
            .order_by(Rental.id)
        )
        return self._session.scalars(stmt).all()

    def update(self, rental: Rental) -> Rental:
        # ``rental`` is already tracked; flush to surface constraint errors now.
        self._session.flush()
        return rental

    def count_active(self) -> int:
        """Number of open rentals (``returned_date IS NULL``)."""
        stmt = (
            select(func.count())
            .select_from(Rental)
            .where(Rental.returned_date.is_(None))
        )
        return self._session.scalar(stmt) or 0
