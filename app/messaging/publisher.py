"""Domain-event publishing abstraction.

The service layer depends only on the ``EventPublisher`` protocol (Dependency
Inversion). ``NullPublisher`` is the default (message queue disabled) and the
one used in tests; :class:`app.messaging.rabbitmq.RabbitMQPublisher` is the
drop-in replacement when ``ENABLE_MESSAGE_QUEUE`` is true. The choice is made in
:func:`app.api.deps.get_event_publisher`.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EventPublisher(Protocol):
    """Publish a single domain event.

    Implementations may raise on transport failure. The *best-effort* policy
    lives in the service layer, not here: ``CarService`` / ``RentalService``
    call this from ``_publish``, which catches any exception so a dropped event
    never fails the business operation.
    """

    def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


class NullPublisher:
    """No-op publisher. Used when the message queue is disabled or in tests."""

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        logger.debug("NullPublisher: dropping event '%s' payload=%s", event_type, payload)
