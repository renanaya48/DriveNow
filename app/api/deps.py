"""FastAPI dependency-injection providers.

``get_db`` (step 2) and the service providers ``get_car_service`` /
``get_rental_service`` (step 5) are added here. Centralising them keeps routers
free of construction logic and makes them trivial to override in tests.
"""

from __future__ import annotations
