"""FastAPI dependency-injection providers (the API composition root).

``get_db`` yields a DB session; ``get_*_service`` assemble a service from one
shared session + its repositories + a Unit of Work + an event publisher. This is
the only place FastAPI's ``Depends`` appears - services and repositories are
plain Python.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.messaging.publisher import EventPublisher, NullPublisher
from app.messaging.rabbitmq import RabbitMQPublisher
from app.repositories.car import SqlAlchemyCarRepository
from app.repositories.rental import SqlAlchemyRentalRepository
from app.services import CarService, RentalService

__all__ = ["get_car_service", "get_db", "get_event_publisher", "get_rental_service"]


@lru_cache
def get_event_publisher() -> EventPublisher:
    """One publisher per process: ``RabbitMQPublisher`` when the message queue is
    enabled, else the no-op ``NullPublisher``.

    Cached so the RabbitMQ connection (opened lazily on the first publish) is
    shared across requests; tests reset it with ``cache_clear()``.
    """
    settings = get_settings()
    if settings.enable_message_queue:
        return RabbitMQPublisher(settings.rabbitmq_url)
    return NullPublisher()


def get_car_service(
    session: Annotated[Session, Depends(get_db)],
    publisher: Annotated[EventPublisher, Depends(get_event_publisher)],
) -> CarService:
    return CarService(
        uow=SqlAlchemyUnitOfWork(session),
        cars=SqlAlchemyCarRepository(session),
        rentals=SqlAlchemyRentalRepository(session),
        publisher=publisher,
    )


def get_rental_service(
    session: Annotated[Session, Depends(get_db)],
    publisher: Annotated[EventPublisher, Depends(get_event_publisher)],
) -> RentalService:
    return RentalService(
        uow=SqlAlchemyUnitOfWork(session),
        cars=SqlAlchemyCarRepository(session),
        rentals=SqlAlchemyRentalRepository(session),
        publisher=publisher,
    )


# API-layer convenience aliases (not domain types - do not re-export).
CarSvc = Annotated[CarService, Depends(get_car_service)]
RentalSvc = Annotated[RentalService, Depends(get_rental_service)]
