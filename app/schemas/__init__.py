"""Pydantic request/response DTOs (the API contract).

Request DTOs (`*Create`, `*Update`) subclass ``StrictModel`` (`extra="forbid"`);
response DTOs (`*Read`) subclass ``ORMModel`` (`from_attributes=True`).
"""

from app.schemas.car import CarCreate, CarRead, CarUpdate
from app.schemas.common import ORMModel, StrictModel, Year
from app.schemas.rental import RentalCreate, RentalRead

__all__ = [
    "CarCreate",
    "CarRead",
    "CarUpdate",
    "ORMModel",
    "RentalCreate",
    "RentalRead",
    "StrictModel",
    "Year",
]
