"""Unit tests for the API DTOs (no DB, no FastAPI)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.models import Car, CarStatus, Rental
from app.schemas import CarCreate, CarRead, CarUpdate, RentalCreate, RentalRead

_START = date(2026, 3, 1)
_END = date(2026, 3, 5)


# --- CarCreate ----------------------------------------------------------------


def test_car_create_valid() -> None:
    dto = CarCreate(model="Toyota Corolla", year=2022)
    assert dto.model == "Toyota Corolla"
    assert dto.year == 2022


def test_car_create_has_no_status_field() -> None:
    assert "status" not in CarCreate.model_fields


@pytest.mark.parametrize("year", [1500, date.today().year + 2])
def test_car_create_rejects_out_of_range_year(year: int) -> None:
    with pytest.raises(ValidationError):
        CarCreate(model="X", year=year)


def test_car_create_allows_next_year_model() -> None:
    CarCreate(model="X", year=date.today().year + 1)


def test_car_create_rejects_empty_model() -> None:
    with pytest.raises(ValidationError):
        CarCreate(model="", year=2020)


def test_car_create_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CarCreate(model="X", year=2020, id=5)  # type: ignore[call-arg]


def test_car_create_rejects_status() -> None:
    """The API contract: a new car's status is not client-settable."""
    with pytest.raises(ValidationError):
        CarCreate(model="Toyota", year=2025, status=CarStatus.IN_USE)  # type: ignore[call-arg]


# --- CarUpdate --------------------------------------------------------------


def test_car_update_empty_is_valid() -> None:
    dto = CarUpdate()
    assert dto.model_dump(exclude_unset=True) == {}


def test_car_update_partial_keeps_only_sent_fields() -> None:
    dto = CarUpdate(status=CarStatus.IN_USE)
    assert dto.model_dump(exclude_unset=True) == {"status": CarStatus.IN_USE}


@pytest.mark.parametrize(
    "payload",
    [{"model": None}, {"year": None}, {"status": None}],
)
def test_car_update_rejects_explicit_null(payload: dict[str, None]) -> None:
    with pytest.raises(ValidationError):
        CarUpdate(**payload)


def test_car_update_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CarUpdate(foo="bar")  # type: ignore[call-arg]


# --- RentalCreate --------------------------------------------------------


def test_rental_create_valid() -> None:
    dto = RentalCreate(
        car_id=1, customer_name="Dana", start_date=_START, end_date=_END
    )
    assert dto.car_id == 1


def test_rental_create_allows_same_day() -> None:
    RentalCreate(car_id=1, customer_name="Dana", start_date=_START, end_date=_START)


def test_rental_create_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        RentalCreate(
            car_id=1, customer_name="Dana", start_date=_END, end_date=_START
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"car_id": 0, "customer_name": "Dana"},
        {"car_id": 1, "customer_name": ""},
    ],
)
def test_rental_create_rejects_bad_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RentalCreate(start_date=_START, end_date=_END, **payload)  # type: ignore[arg-type]


def test_rental_create_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RentalCreate(
            car_id=1,
            customer_name="Dana",
            start_date=_START,
            end_date=_END,
            foo=1,  # type: ignore[call-arg]
        )


# --- *Read from ORM objects --------------------------------------------


def test_car_read_from_orm_object() -> None:
    car = Car(model="VW Golf", year=2021, status=CarStatus.AVAILABLE)
    car.id = 7
    car.created_at = car.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

    dto = CarRead.model_validate(car)
    assert (dto.id, dto.model, dto.status) == (7, "VW Golf", CarStatus.AVAILABLE)


def test_rental_read_from_orm_object_computes_is_active() -> None:
    rental = Rental(
        car_id=1, customer_name="Dana", start_date=_START, end_date=_END
    )
    rental.id = 3
    rental.created_at = rental.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

    assert RentalRead.model_validate(rental).is_active is True

    rental.returned_date = _END
    assert RentalRead.model_validate(rental).is_active is False
