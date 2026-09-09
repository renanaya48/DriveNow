"""RabbitMQ implementation of :class:`EventPublisher` (blocking ``pika``).

Selected by :func:`app.api.deps.get_event_publisher` when
``ENABLE_MESSAGE_QUEUE`` is true; otherwise the app uses ``NullPublisher`` and
needs no broker.

The API routers are sync ``def``, so FastAPI runs each request in a worker
thread from its threadpool: a blocking ``pika`` publish plus a
``threading.Lock`` guarding the one shared connection are the right primitives
here (an async router would instead need an async AMQP client). Publishing is
best-effort - a publish that cannot be confirmed raises, ``CarService._publish``
catches it, logs ``ERROR``, and the HTTP request still succeeds. Guaranteed
delivery would need a transactional outbox (out of scope - see
docs/architecture.md section 6).
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pika
import pika.exceptions

logger = logging.getLogger(__name__)

EXCHANGE = "drivenow.events"

# Socket / connection timeouts (seconds). Publishing runs inline in the request
# path, so an unreachable broker must fail fast instead of stalling the response.
_TIMEOUT_SECONDS = 3

# Errors a fresh connection might fix -> reset and retry once. Semantic/topology
# failures (``ChannelClosedByBroker`` - e.g. an exchange-type mismatch),
# ``UnroutableError`` / ``NackError`` (nothing bound) and serialization errors
# are deliberately NOT here: reconnecting would not help, so they propagate to
# ``CarService._publish`` unchanged.
_RETRYABLE: tuple[type[BaseException], ...] = (
    pika.exceptions.AMQPConnectionError,
    pika.exceptions.StreamLostError,
    pika.exceptions.ChannelWrongStateError,
    OSError,
)


def build_envelope(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a domain event in the transport envelope the consumer expects."""
    return {
        "id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


class RabbitMQPublisher:
    """Publishes domain events to a durable topic exchange.

    One lazily-opened :class:`pika.BlockingConnection` is reused across requests,
    guarded by a lock (request threads share this instance). ``confirm_delivery``
    + ``mandatory=True`` turn an unroutable or unconfirmed publish into an error.
    """

    def __init__(self, url: str) -> None:
        params = pika.URLParameters(url)
        params.socket_timeout = _TIMEOUT_SECONDS
        params.blocked_connection_timeout = _TIMEOUT_SECONDS
        params.connection_attempts = 1
        self._params = params
        self._lock = threading.Lock()
        self._conn: Any = None
        self._channel: Any = None

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        # Build + serialize first: a non-serializable payload is a caller bug,
        # not a broker problem - it raises here, before any connection or retry.
        envelope = build_envelope(event_type, payload)
        body = json.dumps(envelope).encode()
        message_id = envelope["id"]

        with self._lock:
            for attempt in (1, 2):
                try:
                    self._publish_once(event_type, message_id, body)
                    return
                except _RETRYABLE as exc:
                    self._reset()
                    if attempt == 2:
                        logger.error(
                            "publish failed after retry event_type=%s: %s",
                            event_type,
                            exc,
                        )
                        raise
                    logger.warning(
                        "publish attempt failed event_type=%s (%s); reconnecting",
                        event_type,
                        exc,
                    )

    def close(self) -> None:
        """Drop the connection. Called from the app lifespan shutdown; takes the
        same lock so it cannot race a request-thread publish."""
        with self._lock:
            self._reset()

    # --- internals ---------------------------------------------------------

    def _publish_once(self, event_type: str, message_id: str, body: bytes) -> None:
        channel = self._ensure_channel()
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=event_type,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,  # persistent
                message_id=message_id,
                type=event_type,
            ),
            mandatory=True,
        )

    def _ensure_channel(self) -> Any:
        if self._channel is not None and self._channel.is_open:
            return self._channel
        self._reset()  # drop any half-open connection before reconnecting
        self._conn = pika.BlockingConnection(self._params)
        channel = self._conn.channel()
        channel.exchange_declare(
            exchange=EXCHANGE, exchange_type="topic", durable=True
        )
        channel.confirm_delivery()
        self._channel = channel
        return channel

    def _reset(self) -> None:
        conn = self._conn
        self._conn = None
        self._channel = None
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
