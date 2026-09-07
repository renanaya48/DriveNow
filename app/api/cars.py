"""Cars router.

Endpoints (add car / update car / list cars) are implemented in step 6. The
router object exists now so app.main can wire it and the OpenAPI schema is stable.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/cars", tags=["cars"])
