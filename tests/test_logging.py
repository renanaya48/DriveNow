"""Logging behaviour: one INFO line per successful business action, WARNING for
rejected requests, ERROR + traceback for unexpected exceptions.

``caplog`` proves the call sites fire (the transport is stdlib and not asserted).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.main import create_app
from app.models import Car, CarStatus
from app.repositories.car import SqlAlchemyCarRepository
from app.repositories.rental import SqlAlchemyRentalRepository
from app.schemas.car import CarCreate, CarUpdate
from app.schemas.rental import RentalCreate
from app.services import CarService, RentalService

TODAY = date.today()
NEXT_WEEK = TODAY + timedelta(days=7)


class SpyPublisher:
    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        pass


class RaisingPublisher:
    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("broker down")


class ExplodingOnUpdate:
    def __init__(self, inner: SqlAlchemyCarRepository) -> None:
        self._inner = inner

    def add(self, car: Car) -> Car:
        return self._inner.add(car)

    def get_by_id(self, car_id: int) -> Car | None:
        return self._inner.get_by_id(car_id)

    def get_by_id_for_update(self, car_id: int) -> Car | None:
        return self._inner.get_by_id_for_update(car_id)

    def list(self, *, status: CarStatus | None = None) -> Any:
        return self._inner.list(status=status)

    def update(self, car: Car) -> Car:
        raise RuntimeError("boom")

    def soft_delete(self, car: Car) -> Car:
        return self._inner.soft_delete(car)


class BoomCarService:
    """Stands in for CarService; every call raises a non-domain error."""

    def add_car(self, dto: CarCreate) -> Car:
        raise RuntimeError("kaboom")


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


def _seed_car(session: Session, *, status: CarStatus = CarStatus.AVAILABLE) -> Car:
    car = Car(model="Corolla", year=2022, status=status)
    session.add(car)
    session.commit()
    session.refresh(car)
    return car


def _messages(caplog: pytest.LogCaptureFixture, needle: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if needle in r.getMessage()]


# --- service success logs --------------------------------------------


def test_add_car_logs_info(db_session: Session, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    car = _car_service(db_session).add_car(CarCreate(model="Yaris", year=2023))

    (record,) = _messages(caplog, "car added")
    assert record.name == "app.services.car_service"
    assert record.levelno == logging.INFO
    msg = record.getMessage()
    assert f"car_id={car.id}" in msg and "model='Yaris'" in msg and "year=2023" in msg


def test_update_car_real_change_logs(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    svc = _car_service(db_session)
    car = svc.add_car(CarCreate(model="M", year=2020))
    caplog.clear()
    caplog.set_level(logging.INFO)

    svc.update_car(car.id, CarUpdate(status=CarStatus.UNDER_MAINTENANCE))
    (record,) = _messages(caplog, "car updated")
    assert f"car_id={car.id}" in record.getMessage()
    assert "changed=['status']" in record.getMessage()


def test_update_car_noop_does_not_log(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    svc = _car_service(db_session)
    car = svc.add_car(CarCreate(model="M", year=2020))  # AVAILABLE
    caplog.clear()
    caplog.set_level(logging.INFO)

    svc.update_car(car.id, CarUpdate(status=CarStatus.AVAILABLE))
    assert _messages(caplog, "car updated") == []


def test_delete_car_logs(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    svc = _car_service(db_session)
    car = svc.add_car(CarCreate(model="Van", year=2010))
    caplog.clear()
    caplog.set_level(logging.INFO)

    svc.delete_car(car.id)
    (record,) = _messages(caplog, "car retired")
    assert f"car_id={car.id}" in record.getMessage()


def test_register_rental_logs_without_pii(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    car = _seed_car(db_session)
    caplog.set_level(logging.INFO)

    rental = _rental_service(db_session).register_rental(
        RentalCreate(
            car_id=car.id,
            customer_name="Sensitive Person",
            start_date=TODAY,
            end_date=NEXT_WEEK,
        )
    )
    (record,) = _messages(caplog, "rental started")
    msg = record.getMessage()
    assert f"rental_id={rental.id}" in msg and f"car_id={car.id}" in msg
    assert "Sensitive Person" not in msg
    assert "customer" not in msg


def test_end_rental_logs(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    car = _seed_car(db_session)
    rsvc = _rental_service(db_session)
    rental = rsvc.register_rental(
        RentalCreate(
            car_id=car.id, customer_name="D", start_date=TODAY, end_date=NEXT_WEEK
        )
    )
    caplog.clear()
    caplog.set_level(logging.INFO)

    rsvc.end_rental(rental.id)
    (record,) = _messages(caplog, "rental ended")
    assert f"returned={TODAY}" in record.getMessage()


# --- failure semantics -------------------------------------------


def test_no_success_log_when_transaction_rolls_back(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    car = _seed_car(db_session)
    svc = _rental_service(
        db_session, cars=ExplodingOnUpdate(SqlAlchemyCarRepository(db_session))
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(RuntimeError):
        svc.register_rental(
            RentalCreate(
                car_id=car.id, customer_name="D", start_date=TODAY, end_date=NEXT_WEEK
            )
        )
    assert _messages(caplog, "rental started") == []


def test_publish_failure_is_logged(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    car = _seed_car(db_session)
    caplog.set_level(logging.INFO)

    rental = _rental_service(db_session, RaisingPublisher()).register_rental(
        RentalCreate(
            car_id=car.id, customer_name="D", start_date=TODAY, end_date=NEXT_WEEK
        )
    )
    assert rental.id is not None  # operation still succeeded
    assert _messages(caplog, "rental started")  # the success log still fired
    errors = [
        r for r in _messages(caplog, "failed to publish") if r.levelno >= logging.ERROR
    ]
    assert errors and "rental.started" in errors[0].getMessage()
    assert errors[0].exc_info is not None  # ERROR carries the traceback


# --- API exception handlers ------------------------------------


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_domain_error_logged_as_warning(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    car = client.post("/cars", json={"model": "X", "year": 2020}).json()
    body = {
        "car_id": car["id"],
        "customer_name": "D",
        "start_date": TODAY.isoformat(),
        "end_date": NEXT_WEEK.isoformat(),
    }
    client.post("/rentals", json=body)
    caplog.clear()
    caplog.set_level(logging.WARNING)

    resp = client.post("/rentals", json=body)  # car now in_use
    assert resp.status_code == 409
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "Domain error on POST /rentals" in r.getMessage()
    ]
    assert warnings


def test_unhandled_exception_returns_500_and_logs_traceback(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    from app.api.deps import get_car_service

    app = create_app()
    app.dependency_overrides[get_car_service] = lambda: BoomCarService()
    caplog.set_level(logging.ERROR)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        resp = test_client.post("/cars", json={"model": "X", "year": 2020})

    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal server error"}
    (record,) = _messages(caplog, "unhandled error on POST /cars")
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
