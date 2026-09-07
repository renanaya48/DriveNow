"""Domain-level exceptions.

Services raise these; the API layer (app/api/errors.py) maps them to HTTP
status codes. Keeping them HTTP-agnostic keeps the service layer independent of
the transport.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all business-rule violations."""


class CarNotFoundError(DomainError):
    """Requested car does not exist."""


class RentalNotFoundError(DomainError):
    """Requested rental does not exist."""


class CarNotAvailableError(DomainError):
    """Car cannot be rented because it is not in the 'available' state."""


class RentalAlreadyEndedError(DomainError):
    """Rental has already been ended and cannot be ended again."""
