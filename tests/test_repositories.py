"""Unit tests for the repository layer (data access).

Run against in-memory SQLite via the ``db_session`` fixture; no DB daemon needed.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Car, CarStatus, Rental
from app.repositories import (
    CarRepository,
    RentalRepository,
    SqlAlchemyCarRepository,
    SqlAlchemyRentalRepository,
)

_START = date(2026, 1, 1)
_END = date(2026, 1, 5)


def _add_car(session: Session, **kwargs: object) -> Car:
    car = Car(
        model=kwargs.get("model", "Toyota Corolla"),  # type: ignore[arg-type]
        year=kwargs.get("year", 2022),  # type: ignore[arg-type]
        status=kwargs.get("status", CarStatus.AVAILABLE),  # type: ignore[arg-type]
    )
    session.add(car)
    session.flush()
    return car


# --- CarRepository ---------------------------------------------------------


def test_car_add_persists_and_assigns_id(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    car = repo.add(Car(model="VW Golf", year=2021))
    assert car.id is not None


def test_car_get_by_id(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    car = repo.add(Car(model="Kia Niro", year=2023))

    assert repo.get_by_id(car.id) is car
    assert repo.get_by_id(999_999) is None


def test_car_get_by_id_for_update(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    car = repo.add(Car(model="Mazda 3", year=2020))

    # with_for_update is a no-op on SQLite; the row still comes back.
    assert repo.get_by_id_for_update(car.id) is car
    assert repo.get_by_id_for_update(999_999) is None


def test_car_list_returns_all_ordered(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    a = repo.add(Car(model="A", year=2020))
    b = repo.add(Car(model="B", year=2021))

    assert [c.id for c in repo.list()] == [a.id, b.id]


def test_car_list_filters_by_status(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    repo.add(Car(model="Free", year=2020, status=CarStatus.AVAILABLE))
    busy = repo.add(Car(model="Busy", year=2021, status=CarStatus.IN_USE))

    result = repo.list(status=CarStatus.IN_USE)
    assert [c.id for c in result] == [busy.id]


def test_car_update_persists_change(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    car = repo.add(Car(model="Fiat 500", year=2018))

    car.status = CarStatus.UNDER_MAINTENANCE
    repo.update(car)
    db_session.expire_all()

    reloaded = repo.get_by_id(car.id)
    assert reloaded is not None
    assert reloaded.status is CarStatus.UNDER_MAINTENANCE


def test_car_soft_delete_hides_from_reads(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    car = repo.add(Car(model="Old Van", year=2010))
    other = repo.add(Car(model="Kept", year=2024))

    repo.soft_delete(car)
    assert car.deleted_at is not None

    assert repo.get_by_id(car.id) is None
    assert repo.get_by_id_for_update(car.id) is None
    assert [c.id for c in repo.list()] == [other.id]


def test_soft_deleted_car_still_reachable_via_rental_history(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    rentals = SqlAlchemyRentalRepository(db_session)
    car = repo.add(Car(model="Retired", year=2012))
    rental = rentals.add(
        Rental(car_id=car.id, customer_name="Past", start_date=_START, end_date=_END)
    )

    repo.soft_delete(car)
    db_session.expire_all()

    reloaded = rentals.get_by_id(rental.id)
    assert reloaded is not None
    assert reloaded.car.id == car.id  # history keeps its link to the retired car


def test_car_count_by_status_excludes_deleted(db_session: Session) -> None:
    repo = SqlAlchemyCarRepository(db_session)
    repo.add(Car(model="A", year=2020, status=CarStatus.AVAILABLE))
    repo.add(Car(model="B", year=2021, status=CarStatus.AVAILABLE))
    repo.add(Car(model="C", year=2022, status=CarStatus.IN_USE))
    repo.add(Car(model="D", year=2018, status=CarStatus.UNDER_MAINTENANCE))
    gone = repo.add(Car(model="E", year=2019, status=CarStatus.AVAILABLE))
    repo.soft_delete(gone)

    assert repo.count_by_status() == {
        CarStatus.AVAILABLE: 2,  # 'E' is soft-deleted, excluded
        CarStatus.IN_USE: 1,
        CarStatus.UNDER_MAINTENANCE: 1,
    }


def test_car_repo_satisfies_protocol(db_session: Session) -> None:
    assert isinstance(SqlAlchemyCarRepository(db_session), CarRepository)


# --- RentalRepository ----------------------------------------------------


def test_rental_add_and_get_by_id(db_session: Session) -> None:
    car = _add_car(db_session)
    repo = SqlAlchemyRentalRepository(db_session)

    rental = repo.add(
        Rental(car_id=car.id, customer_name="Dana", start_date=_START, end_date=_END)
    )
    assert rental.id is not None
    assert repo.get_by_id(rental.id) is rental
    assert repo.get_by_id(999_999) is None


def test_rental_get_active_by_car_ignores_returned(db_session: Session) -> None:
    car = _add_car(db_session)
    repo = SqlAlchemyRentalRepository(db_session)

    closed = repo.add(
        Rental(car_id=car.id, customer_name="Old", start_date=_START, end_date=_END)
    )
    closed.returned_date = _END
    db_session.flush()
    assert repo.get_active_by_car(car.id) is None

    active = repo.add(
        Rental(car_id=car.id, customer_name="New", start_date=_START, end_date=_END)
    )
    assert repo.get_active_by_car(car.id) is active


def test_rental_list_active_excludes_returned(db_session: Session) -> None:
    car_a = _add_car(db_session, model="A")
    car_b = _add_car(db_session, model="B")
    repo = SqlAlchemyRentalRepository(db_session)

    open_rental = repo.add(
        Rental(car_id=car_a.id, customer_name="Open", start_date=_START, end_date=_END)
    )
    returned = repo.add(
        Rental(car_id=car_b.id, customer_name="Done", start_date=_START, end_date=_END)
    )
    returned.returned_date = _END
    db_session.flush()

    assert [r.id for r in repo.list_active()] == [open_rental.id]


def test_rental_get_by_id_for_update(db_session: Session) -> None:
    car = _add_car(db_session)
    repo = SqlAlchemyRentalRepository(db_session)
    rental = repo.add(
        Rental(car_id=car.id, customer_name="Dana", start_date=_START, end_date=_END)
    )

    # with_for_update is a no-op on SQLite; the row still comes back.
    assert repo.get_by_id_for_update(rental.id) is rental
    assert repo.get_by_id_for_update(999_999) is None


def test_rental_update_persists_change(db_session: Session) -> None:
    car = _add_car(db_session)
    repo = SqlAlchemyRentalRepository(db_session)
    rental = repo.add(
        Rental(car_id=car.id, customer_name="Dana", start_date=_START, end_date=_END)
    )

    rental.returned_date = _END
    repo.update(rental)
    db_session.expire_all()

    reloaded = repo.get_by_id(rental.id)
    assert reloaded is not None
    assert reloaded.returned_date == _END


def test_rental_count_active(db_session: Session) -> None:
    car_a = _add_car(db_session, model="A")
    car_b = _add_car(db_session, model="B")
    repo = SqlAlchemyRentalRepository(db_session)
    assert repo.count_active() == 0

    repo.add(
        Rental(car_id=car_a.id, customer_name="Open", start_date=_START, end_date=_END)
    )
    closed = repo.add(
        Rental(car_id=car_b.id, customer_name="Done", start_date=_START, end_date=_END)
    )
    assert repo.count_active() == 2

    closed.returned_date = _END
    db_session.flush()
    assert repo.count_active() == 1


def test_rental_repo_satisfies_protocol(db_session: Session) -> None:
    assert isinstance(SqlAlchemyRentalRepository(db_session), RentalRepository)
