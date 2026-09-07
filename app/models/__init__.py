"""SQLAlchemy ORM models and shared enums.

Importing this package registers every model on ``Base.metadata`` (used by
Alembic's ``env.py`` and by ``create_all`` in tests).
"""

from app.models.base import Base
from app.models.car import Car
from app.models.enums import CarStatus
from app.models.rental import Rental

__all__ = ["Base", "Car", "CarStatus", "Rental"]
