"""Rental ORM model."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.car import Car


class Rental(TimestampMixin, Base):
    """A rental agreement for a single car over a fixed period.

    ``start_date`` / ``end_date`` are the agreed term, both set when the rental
    is registered. ``returned_date`` is ``None`` while the car is still out and
    is set when the rental is ended; an *active* rental is one with
    ``returned_date IS NULL``.
    """

    __tablename__ = "rentals"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_rentals_end_after_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(
        ForeignKey("cars.id", name="fk_rentals_car_id"),
        nullable=False,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    returned_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    car: Mapped[Car] = relationship(back_populates="rentals")

    @property
    def is_active(self) -> bool:
        """True while the car has not been returned yet."""
        return self.returned_date is None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"Rental(id={self.id!r}, car_id={self.car_id!r}, "
            f"customer_name={self.customer_name!r}, active={self.is_active})"
        )
