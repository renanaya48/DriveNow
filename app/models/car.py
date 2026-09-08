"""Car ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import CarStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.rental import Rental


class Car(TimestampMixin, Base):
    """A vehicle in the DriveNow fleet.

    Removal is a **soft delete**: ``deleted_at`` is stamped instead of deleting
    the row, so rental history is preserved and the car stays reachable via
    ``Rental.car``. Repository reads skip rows with ``deleted_at`` set.
    """

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[CarStatus] = mapped_column(
        # native_enum=False -> stored as VARCHAR; create_constraint=True adds the
        # CHECK (defaults to False); values_callable stores the enum *values*
        # ('available', ...) rather than the member names ('AVAILABLE', ...).
        # Same DDL on PostgreSQL and SQLite.
        SAEnum(
            CarStatus,
            native_enum=False,
            create_constraint=True,
            length=20,
            name="car_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=CarStatus.AVAILABLE,
        server_default=CarStatus.AVAILABLE.value,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Default cascade only (save-update, merge) - deleting/detaching a Car must
    # never touch its rental history.
    rentals: Mapped[list[Rental]] = relationship(back_populates="car")

    @property
    def is_deleted(self) -> bool:
        """True once the car has been retired from the fleet."""
        return self.deleted_at is not None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Car(id={self.id!r}, model={self.model!r}, status={self.status!r})"
