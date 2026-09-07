"""Car ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import CarStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.rental import Rental


class Car(TimestampMixin, Base):
    """A vehicle in the DriveNow fleet."""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[CarStatus] = mapped_column(
        # native_enum=False -> stored as VARCHAR + CHECK, so the same model works
        # on PostgreSQL and on SQLite (used by the test suite).
        SAEnum(CarStatus, native_enum=False, length=20, name="car_status"),
        nullable=False,
        default=CarStatus.AVAILABLE,
        server_default=CarStatus.AVAILABLE.value,
    )

    rentals: Mapped[list[Rental]] = relationship(
        back_populates="car",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Car(id={self.id!r}, model={self.model!r}, status={self.status!r})"
