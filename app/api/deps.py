"""FastAPI dependency-injection providers.

``get_db`` yields a DB session. The service providers ``get_car_service`` /
``get_rental_service`` are added in step 5. Centralising them keeps routers free
of construction logic and makes them trivial to override in tests.
"""

from __future__ import annotations

from app.core.db import get_db

__all__ = ["get_db"]
