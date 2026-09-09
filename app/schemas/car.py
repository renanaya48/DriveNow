"""Request/response DTOs for cars."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from app.models import CarStatus
from app.schemas.common import ORMModel, StrictModel, Year


class CarCreate(StrictModel):
    """Body for adding a car. A new car is always created ``AVAILABLE`` -
    moving to ``IN_USE`` only ever happens through registering a rental, so
    ``status`` is deliberately not accepted here."""

    model: str = Field(min_length=1, max_length=100)
    year: Year


class CarUpdate(StrictModel):
    """Body for a partial car update. An empty body is valid (no-op). A field
    sent explicitly as ``null`` is rejected - those columns are ``NOT NULL``."""

    model: str | None = Field(default=None, min_length=1, max_length=100)
    year: Year | None = None
    status: CarStatus | None = None

    @model_validator(mode="after")
    def _reject_explicit_null(self) -> CarUpdate:
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} may not be null")
        return self


class CarRead(ORMModel):
    """A car as returned by the API. Soft-deleted cars are never returned, so
    ``deleted_at`` is not exposed."""

    id: int
    model: str
    year: int
    status: CarStatus
    created_at: datetime
    updated_at: datetime
