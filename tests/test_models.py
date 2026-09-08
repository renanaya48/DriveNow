"""Schema-contract tests for the ORM models and the initial migration.

These lock down what step 2 produced so steps 3+ can build on it safely.
Business-logic tests for the service layer come in step 10.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Car, CarStatus, Rental

_START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
_END = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def test_car_status_values() -> None:
    assert {s.value for s in CarStatus} == {"available", "in_use", "under_maintenance"}


def test_is_active_reflects_returned_at() -> None:
    rental = Rental(car_id=1, customer_name="Dana", start_at=_START, end_at=_END)
    assert rental.is_active is True

    rental.returned_at = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)
    assert rental.is_active is False


def test_car_rental_relationship_both_directions(db_session: Session) -> None:
    car = Car(model="VW Golf", year=2021)
    rental = Rental(car=car, customer_name="Yossi", start_at=_START, end_at=_END)
    db_session.add(rental)
    db_session.commit()

    assert rental.car is car
    assert car.rentals == [rental]


def test_timestamps_autopopulate(db_session: Session) -> None:
    car = Car(model="Kia Niro", year=2023)
    db_session.add(car)
    db_session.commit()
    db_session.refresh(car)

    assert car.created_at is not None
    assert car.updated_at is not None


def test_default_status_is_available(db_session: Session) -> None:
    car = Car(model="Honda Civic", year=2019)
    db_session.add(car)
    db_session.commit()
    db_session.refresh(car)

    assert car.status is CarStatus.AVAILABLE


def test_car_status_roundtrips_as_enum(db_session: Session) -> None:
    car = Car(model="Mazda 3", year=2020, status=CarStatus.IN_USE)
    db_session.add(car)
    db_session.commit()
    car_id = car.id
    db_session.expunge_all()

    loaded = db_session.get(Car, car_id)
    assert loaded is not None
    assert isinstance(loaded.status, CarStatus)
    assert loaded.status is CarStatus.IN_USE


def test_check_constraint_rejects_end_before_start(db_session: Session) -> None:
    car = Car(model="Fiat 500", year=2018)
    db_session.add(car)
    db_session.flush()

    db_session.add(
        Rental(
            car_id=car.id,
            customer_name="Rita",
            start_at=_END,
            end_at=_START,  # ends before it starts
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_key_is_enforced(db_session: Session) -> None:
    db_session.add(
        Rental(
            car_id=9999,  # no such car
            customer_name="Nobody",
            start_at=_START,
            end_at=_END,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_migration_head_matches_model_metadata(tmp_path: object) -> None:
    """`alembic upgrade head` yields the same tables/columns as the models."""
    from alembic.command import upgrade
    from alembic.config import Config

    url = f"sqlite:///{tmp_path}/m.db"  # type: ignore[str-bytes-safe]
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    upgrade(cfg, "head")

    migrated = inspect(create_engine(url))
    meta_engine = create_engine("sqlite://")
    Base.metadata.create_all(meta_engine)
    modelled = inspect(meta_engine)

    model_tables = set(Base.metadata.tables)
    assert model_tables <= set(migrated.get_table_names())
    for table in model_tables:
        assert {c["name"] for c in migrated.get_columns(table)} == {
            c["name"] for c in modelled.get_columns(table)
        }, f"column drift in {table!r}"
