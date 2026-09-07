"""Domain-event publishing abstraction.

The service layer depends only on the ``EventPublisher`` protocol (Dependency
Inversion). ``NullPublisher`` is the default in the skeleton and in tests;
``RabbitMQPublisher`` is added in step 9 and is a drop-in replacement.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EventPublisher(Protocol):
    """Publish a single domain event. Implementations must not raise on failure
    in a way that breaks the caller's request; publishing is best-effort."""

    def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


class NullPublisher:
    """No-op publisher. Used when the message queue is disabled or in tests."""

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        logger.debug("NullPublisher: dropping event '%s' payload=%s", event_type, payload)
