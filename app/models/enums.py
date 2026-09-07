"""Domain enums shared across layers."""

from __future__ import annotations

from enum import StrEnum


class CarStatus(StrEnum):
    """Lifecycle status of a car in the fleet."""

    AVAILABLE = "available"
    IN_USE = "in_use"
    UNDER_MAINTENANCE = "under_maintenance"
