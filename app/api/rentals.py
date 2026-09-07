"""Rentals router.

Endpoints (register rental / end rental) are implemented in step 6. The router
object exists now so app.main can wire it and the OpenAPI schema is stable.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/rentals", tags=["rentals"])
