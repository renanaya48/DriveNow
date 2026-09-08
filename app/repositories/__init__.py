"""Data access layer: all DB queries live here.

One narrow ``Protocol`` per aggregate plus a SQLAlchemy implementation, mirroring
``EventPublisher`` / ``NullPublisher``. No business rules, no ``commit``.
"""

from app.repositories.car import CarRepository, SqlAlchemyCarRepository
from app.repositories.rental import RentalRepository, SqlAlchemyRentalRepository

__all__ = [
    "CarRepository",
    "RentalRepository",
    "SqlAlchemyCarRepository",
    "SqlAlchemyRentalRepository",
]
