"""Request/response DTOs for rentals."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, model_validator

from app.schemas.common import ORMModel, StrictModel


class RentalCreate(StrictModel):
    """Body for registering a rental. The term is a pair of dates, both given
    up front; ``end_date`` may equal ``start_date`` (a one-day rental)."""

    car_id: int = Field(gt=0)
    customer_name: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _end_on_or_after_start(self) -> RentalCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class RentalRead(ORMModel):
    """A rental as returned by the API."""

    id: int
    car_id: int
    customer_name: str
    start_date: date
    end_date: date
    returned_date: date | None
    created_at: datetime
    updated_at: datetime
    is_active: bool
