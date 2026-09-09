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


class CarStatusTransitionError(DomainError):
    """Requested status change is not a legal transition via update."""


class CarHasActiveRentalError(DomainError):
    """Car cannot be removed while it has an active rental."""


class RentalAlreadyEndedError(DomainError):
    """Rental has already been ended and cannot be ended again."""


class RentalDateError(DomainError):
    """Rental dates violate a business rule (e.g. not starting today)."""
