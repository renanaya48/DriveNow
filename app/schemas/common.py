"""Shared building blocks for the API DTOs."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base for every response DTO - built from ORM instances via attributes."""

    model_config = ConfigDict(from_attributes=True)


class StrictModel(BaseModel):
    """Base for every request DTO - unknown / over-posted fields are a 422."""

    model_config = ConfigDict(extra="forbid")


def _check_year(value: int) -> int:
    max_year = date.today().year + 1
    if not 1900 <= value <= max_year:
        raise ValueError(f"year must be between 1900 and {max_year}")
    return value


# A model year: 1900 .. next calendar year. In ``Year | None`` Pydantic skips
# the validator when the value is None.
Year = Annotated[int, AfterValidator(_check_year)]
