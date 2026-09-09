"""Unit tests for the service layer: business rules + transaction boundary.

Real ``SqlAlchemyUnitOfWork`` + repositories over the in-memory ``db_session``
fixture; a ``SpyPublisher`` records emitted events.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.models import Car, CarStatus, Rental
from app.repositories.car import SqlAlchemyCarRepository
from app.repositories.rental import SqlAlchemyRentalRepository
from app.schemas.car import CarCreate, CarUpdate
from app.schemas.rental import RentalCreate
from app.services import (
    CarHasActiveRentalError,
    CarNotAvailableError,
    CarNotFoundError,
    CarService,
    CarStatusTransitionError,
    RentalAlreadyEndedError,
    RentalDateError,
    RentalNotFoundError,
    RentalService,
)

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)
NEXT_WEEK = TODAY + timedelta(days=7)


class SpyPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class RaisingPublisher:
    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("broker down")


class ExplodingOnUpdate:
    """Delegates to a real CarRepository but raises on update()."""

    def __init__(self, inner: SqlAlchemyCarRepository) -> None:
        self._inner = inner

    def add(self, car: Car) -> Car:
        return self._inner.add(car)

    def get_by_id(self, car_id: int) -> Car | None:
        return self._inner.get_by_id(car_id)

    def get_by_id_for_update(self, car_id: int) -> Car | None:
        return self._inner.get_by_id_for_update(car_id)

    def list(self, *, status: CarStatus | None = None) -> Sequence[Car]:
        return self._inner.list(status=status)

    def update(self, car: Car) -> Car:
        raise RuntimeError("boom")

    def soft_delete(self, car: Car) -> Car:
        return self._inner.soft_delete(car)


def _car_service(session: Session, publisher: Any = None) -> CarService:
    return CarService(
        uow=SqlAlchemyUnitOfWork(session),
        cars=SqlAlchemyCarRepository(session),
        rentals=SqlAlchemyRentalRepository(session),
        publisher=publisher or SpyPublisher(),
    )


def _rental_service(
    session: Session, publisher: Any = None, *, cars: Any = None
) -> RentalService:
    return RentalService(
        uow=SqlAlchemyUnitOfWork(session),
        cars=cars or SqlAlchemyCarRepository(session),
        rentals=SqlAlchemyRentalRepository(session),
        publisher=publisher or SpyPublisher(),
    )


def _seed_car(
    session: Session,
    *,
    status: CarStatus = CarStatus.AVAILABLE,
    model: str = "Corolla",
    year: int = 2022,
) -> Car:
    car = Car(model=model, year=year, status=status)
    session.add(car)
    session.commit()
    session.refresh(car)
    return car


def _rc(car_id: int, *, start: date = TODAY, end: date = NEXT_WEEK) -> RentalCreate:
    return RentalCreate(
        car_id=car_id, customer_name="Dana", start_date=start, end_date=end
    )


# --- CarService ------------------------------------------------------------


def test_add_car_persists_and_publishes(db_session: Session) -> None:
    spy = SpyPublisher()
    car = _car_service(db_session, spy).add_car(CarCreate(model="Yaris", year=2023))

    assert car.id is not None
    assert car.status is CarStatus.AVAILABLE
    assert spy.events == [("car.added", {"car_id": car.id})]
    assert SqlAlchemyCarRepository(db_session).get_by_id(car.id) is not None


def test_list_cars_filters_by_status(db_session: Session) -> None:
    svc = _car_service(db_session)
    a = svc.add_car(CarCreate(model="A", year=2020))
    b = svc.add_car(CarCreate(model="B", year=2021))
    svc.update_car(b.id, CarUpdate(status=CarStatus.UNDER_MAINTENANCE))

    assert [c.id for c in svc.list_cars()] == [a.id, b.id]
    assert [c.id for c in svc.list_cars(status=CarStatus.UNDER_MAINTENANCE)] == [b.id]


def test_update_car_model_and_year(db_session: Session) -> None:
    svc = _car_service(db_session)
    car = svc.add_car(CarCreate(model="Old", year=2015))

    updated = svc.update_car(car.id, CarUpdate(model="New", year=2016))
    assert (updated.model, updated.year) == ("New", 2016)


def test_update_car_toggles_maintenance(db_session: Session) -> None:
    spy = SpyPublisher()
    svc = _car_service(db_session, spy)
    car = svc.add_car(CarCreate(model="M", year=2020))
    spy.events.clear()

    a = svc.update_car(car.id, CarUpdate(status=CarStatus.UNDER_MAINTENANCE))
    assert a.status is CarStatus.UNDER_MAINTENANCE
    b = svc.update_car(car.id, CarUpdate(status=CarStatus.AVAILABLE))
    assert b.status is CarStatus.AVAILABLE
    assert [e[0] for e in spy.events] == ["car.updated", "car.updated"]
    assert spy.events[0][1] == {"car_id": car.id, "changed": ["status"]}


def test_update_car_rejects_available_to_in_use(db_session: Session) -> None:
    svc = _car_service(db_session)
    car = svc.add_car(CarCreate(model="X", year=2020))

    with pytest.raises(CarStatusTransitionError):
        svc.update_car(car.id, CarUpdate(status=CarStatus.IN_USE))


def test_update_car_rejects_status_change_on_in_use_car(db_session: Session) -> None:
    car = _seed_car(db_session)
    _rental_service(db_session).register_rental(_rc(car.id))
    svc = _car_service(db_session)

    with pytest.raises(CarStatusTransitionError):
        svc.update_car(car.id, CarUpdate(status=CarStatus.AVAILABLE))
    with pytest.raises(CarStatusTransitionError):
        svc.update_car(car.id, CarUpdate(status=CarStatus.UNDER_MAINTENANCE))


def test_update_car_missing(db_session: Session) -> None:
    with pytest.raises(CarNotFoundError):
        _car_service(db_session).update_car(999, CarUpdate(model="Z"))


def test_update_car_empty_body_is_noop(db_session: Session) -> None:
    spy = SpyPublisher()
    svc = _car_service(db_session, spy)
    car = svc.add_car(CarCreate(model="X", year=2020))
    spy.events.clear()

    result = svc.update_car(car.id, CarUpdate())
    assert result.id == car.id
    assert spy.events == []


def test_update_car_same_value_is_noop(db_session: Session) -> None:
    spy = SpyPublisher()
    svc = _car_service(db_session, spy)
    car = svc.add_car(CarCreate(model="X", year=2020))  # AVAILABLE
    spy.events.clear()

    svc.update_car(car.id, CarUpdate(status=CarStatus.AVAILABLE))
    assert spy.events == []


def test_delete_car_soft_deletes_and_publishes(db_session: Session) -> None:
    spy = SpyPublisher()
    svc = _car_service(db_session, spy)
    car = svc.add_car(CarCreate(model="X", year=2020))
    spy.events.clear()

    svc.delete_car(car.id)
    assert list(svc.list_cars()) == []
    assert spy.events == [("car.deleted", {"car_id": car.id})]


def test_delete_car_blocked_by_active_rental(db_session: Session) -> None:
    car = _seed_car(db_session)
    _rental_service(db_session).register_rental(_rc(car.id))

    with pytest.raises(CarHasActiveRentalError):
        _car_service(db_session).delete_car(car.id)

    still = SqlAlchemyCarRepository(db_session).get_by_id(car.id)
    assert still is not None and still.status is CarStatus.IN_USE


def test_delete_car_missing(db_session: Session) -> None:
    with pytest.raises(CarNotFoundError):
        _car_service(db_session).delete_car(999)


def test_add_car_survives_publisher_failure(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """A raising publisher is swallowed: the car commits, one ERROR is logged."""
    caplog.set_level(logging.INFO)
    car = _car_service(db_session, RaisingPublisher()).add_car(
        CarCreate(model="Yaris", year=2023)
    )

    assert SqlAlchemyCarRepository(db_session).get_by_id(car.id) is not None
    errors = [
        r
        for r in caplog.records
        if r.getMessage() == "failed to publish car.added" and r.levelno >= logging.ERROR
    ]
    assert len(errors) == 1
    assert errors[0].name == "app.services.car_service"
    assert errors[0].exc_info is not None  # ERROR carries the traceback


# --- RentalService -------------------------------------------------------


def test_register_rental_marks_car_in_use_and_publishes(db_session: Session) -> None:
    spy = SpyPublisher()
    car = _seed_car(db_session)

    rental = _rental_service(db_session, spy).register_rental(_rc(car.id))

    assert rental.id is not None
    reloaded = SqlAlchemyCarRepository(db_session).get_by_id(car.id)
    assert reloaded is not None and reloaded.status is CarStatus.IN_USE
    assert spy.events == [
        ("rental.started", {"rental_id": rental.id, "car_id": car.id})
    ]


def test_register_rental_on_unavailable_car(db_session: Session) -> None:
    car = _seed_car(db_session, status=CarStatus.UNDER_MAINTENANCE)
    with pytest.raises(CarNotAvailableError):
        _rental_service(db_session).register_rental(_rc(car.id))


def test_register_rental_on_missing_car(db_session: Session) -> None:
    with pytest.raises(CarNotFoundError):
        _rental_service(db_session).register_rental(_rc(999))


def test_register_rental_on_soft_deleted_car(db_session: Session) -> None:
    car = _seed_car(db_session)
    _car_service(db_session).delete_car(car.id)
    with pytest.raises(CarNotFoundError):
        _rental_service(db_session).register_rental(_rc(car.id))


@pytest.mark.parametrize("start", [YESTERDAY, TOMORROW])
def test_register_rental_rejects_non_today_start(
    db_session: Session, start: date
) -> None:
    car = _seed_car(db_session)
    with pytest.raises(RentalDateError):
        _rental_service(db_session).register_rental(_rc(car.id, start=start))


def test_register_rental_inconsistent_state_is_domain_error(
    db_session: Session,
) -> None:
    """Car row AVAILABLE + an open rental exists -> CarNotAvailableError, not IntegrityError."""
    car = _seed_car(db_session)
    SqlAlchemyRentalRepository(db_session).add(
        Rental(
            car_id=car.id, customer_name="Ghost", start_date=TODAY, end_date=NEXT_WEEK
        )
    )
    db_session.commit()

    with pytest.raises(CarNotAvailableError):
        _rental_service(db_session).register_rental(_rc(car.id))


def test_car_can_be_rented_again_after_return(db_session: Session) -> None:
    car = _seed_car(db_session)
    rsvc = _rental_service(db_session)
    r1 = rsvc.register_rental(_rc(car.id))
    rsvc.end_rental(r1.id)

    r2 = rsvc.register_rental(_rc(car.id))
    assert r2.id != r1.id


def test_end_rental_returns_car_and_publishes(db_session: Session) -> None:
    spy = SpyPublisher()
    car = _seed_car(db_session)
    rsvc = _rental_service(db_session, spy)
    rental = rsvc.register_rental(_rc(car.id))
    spy.events.clear()

    ended = rsvc.end_rental(rental.id)
    assert ended.returned_date == TODAY
    assert ended.is_active is False
    reloaded = SqlAlchemyCarRepository(db_session).get_by_id(car.id)
    assert reloaded is not None and reloaded.status is CarStatus.AVAILABLE
    assert spy.events == [
        ("rental.ended", {"rental_id": rental.id, "car_id": car.id})
    ]


def test_end_rental_already_ended(db_session: Session) -> None:
    car = _seed_car(db_session)
    rsvc = _rental_service(db_session)
    rental = rsvc.register_rental(_rc(car.id))
    rsvc.end_rental(rental.id)

    with pytest.raises(RentalAlreadyEndedError):
        rsvc.end_rental(rental.id)


def test_end_rental_missing(db_session: Session) -> None:
    with pytest.raises(RentalNotFoundError):
        _rental_service(db_session).end_rental(999)


def test_end_rental_when_car_row_is_gone_is_domain_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive guard: an active rental exists but its car row can't be locked."""
    car = _seed_car(db_session, status=CarStatus.IN_USE)
    rental = SqlAlchemyRentalRepository(db_session).add(
        Rental(car_id=car.id, customer_name="X", start_date=TODAY, end_date=NEXT_WEEK)
    )
    db_session.commit()

    cars = SqlAlchemyCarRepository(db_session)
    monkeypatch.setattr(cars, "get_by_id_for_update", lambda _car_id: None)

    with pytest.raises(CarNotFoundError):
        _rental_service(db_session, cars=cars).end_rental(rental.id)


def test_end_rental_before_start_date(db_session: Session) -> None:
    """A rental whose start_date is still in the future cannot be ended.

    Constructed directly (register_rental would reject start_date != today).
    """
    car = _seed_car(db_session, status=CarStatus.IN_USE)
    rental = SqlAlchemyRentalRepository(db_session).add(
        Rental(
            car_id=car.id,
            customer_name="Future",
            start_date=TOMORROW,
            end_date=TOMORROW + timedelta(days=5),
        )
    )
    db_session.commit()

    with pytest.raises(RentalDateError):
        _rental_service(db_session).end_rental(rental.id)


# --- best-effort events + transaction boundary -------------------------


def test_register_rental_survives_publisher_failure(db_session: Session) -> None:
    car = _seed_car(db_session)
    rental = _rental_service(db_session, RaisingPublisher()).register_rental(
        _rc(car.id)
    )

    reloaded = SqlAlchemyCarRepository(db_session).get_by_id(car.id)
    assert reloaded is not None and reloaded.status is CarStatus.IN_USE
    assert SqlAlchemyRentalRepository(db_session).get_by_id(rental.id) is not None


def test_register_rental_rolls_back_on_repo_failure(db_session: Session) -> None:
    spy = SpyPublisher()
    car = _seed_car(db_session)
    svc = _rental_service(
        db_session, spy, cars=ExplodingOnUpdate(SqlAlchemyCarRepository(db_session))
    )

    with pytest.raises(RuntimeError):
        svc.register_rental(_rc(car.id))

    db_session.expire_all()
    reloaded = SqlAlchemyCarRepository(db_session).get_by_id(car.id)
    assert reloaded is not None and reloaded.status is CarStatus.AVAILABLE
    assert list(SqlAlchemyRentalRepository(db_session).list_active()) == []
    assert spy.events == []


def test_end_rental_rolls_back_on_repo_failure(db_session: Session) -> None:
    spy = SpyPublisher()
    car = _seed_car(db_session)
    rental = _rental_service(db_session).register_rental(_rc(car.id))

    svc = _rental_service(
        db_session, spy, cars=ExplodingOnUpdate(SqlAlchemyCarRepository(db_session))
    )
    with pytest.raises(RuntimeError):
        svc.end_rental(rental.id)

    db_session.expire_all()
    reloaded = SqlAlchemyRentalRepository(db_session).get_by_id(rental.id)
    assert reloaded is not None and reloaded.returned_date is None
    car_row = SqlAlchemyCarRepository(db_session).get_by_id(car.id)
    assert car_row is not None and car_row.status is CarStatus.IN_USE
    assert spy.events == []
