"""Event-logging consumer - run as its own process (``python -m app.messaging.consumer``).

Subscribes to every domain event on the ``drivenow.events`` topic exchange and
writes one INFO line per event. It demonstrates the messaging seam; it is not a
durable audit store (that would be a DB writer with idempotency keys).

Lifecycle:
  * declares the exchange + a durable queue ``drivenow.event_logger`` bound to
    ``#`` (all events), prefetch 10;
  * ``basic_ack`` on a well-formed envelope, ``basic_nack(requeue=False)`` (drop)
    on a malformed one - a poison message must not loop forever;
  * SIGTERM / SIGINT set a ``threading.Event`` and call ``stop_consuming()``; a
    broker outage reconnects after a short backoff, but a shutdown requested
    during that backoff returns immediately and never reconnects.
"""

from __future__ import annotations

import contextlib
import json
import logging
import signal
import threading
from typing import Any

import pika
import pika.exceptions

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

EXCHANGE = "drivenow.events"
QUEUE = "drivenow.event_logger"
_PREFETCH = 10
_RECONNECT_DELAY_SECONDS = 5
_REQUIRED_KEYS = ("id", "event_type", "occurred_at", "payload")

_shutdown = threading.Event()
_active_channel: Any = None


def _parse_event(body: bytes) -> dict[str, Any]:
    """Decode + validate the transport envelope. Raises ``ValueError`` (which
    covers ``json.JSONDecodeError``) if the body is not a well-formed envelope."""
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise ValueError(f"event body is not a JSON object: {type(decoded).__name__}")
    missing = [key for key in _REQUIRED_KEYS if key not in decoded]
    if missing:
        raise ValueError(f"event envelope missing keys: {missing}")
    for key in ("id", "event_type", "occurred_at"):
        if not isinstance(decoded[key], str):
            raise ValueError(f"event field {key!r} must be a string")
    if not isinstance(decoded["payload"], dict):
        raise ValueError("event field 'payload' must be an object")
    return decoded


def _on_message(channel: Any, method: Any, _properties: Any, body: bytes) -> None:
    """Handle one delivery: log + ack, or (malformed) log + drop without requeue."""
    try:
        event = _parse_event(body)
    except ValueError as exc:
        logger.error("dropping malformed event: %s", exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return
    logger.info(
        "event received event_type=%s id=%s payload=%s",
        event["event_type"],
        event["id"],
        event["payload"],
    )
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _consume_once(url: str) -> None:
    """Open one connection and consume until shutdown or the connection drops."""
    global _active_channel
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        channel = connection.channel()
        channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
        channel.queue_declare(queue=QUEUE, durable=True)
        channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key="#")
        channel.basic_qos(prefetch_count=_PREFETCH)
        channel.basic_consume(queue=QUEUE, on_message_callback=_on_message)
        _active_channel = channel
        logger.info("consumer ready: exchange=%s queue=%s", EXCHANGE, QUEUE)
        channel.start_consuming()
    finally:
        _active_channel = None
        with contextlib.suppress(Exception):
            connection.close()


def _handle_signal(signum: int, _frame: Any) -> None:
    logger.info("signal %s received; stopping consumer", signum)
    _shutdown.set()
    if _active_channel is not None:
        with contextlib.suppress(Exception):
            _active_channel.stop_consuming()


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def main() -> None:
    settings = get_settings()
    configure_logging(settings)

    if not settings.enable_message_queue:
        logger.warning(
            "message queue disabled (ENABLE_MESSAGE_QUEUE=false); consumer exiting"
        )
        return

    _install_signal_handlers()
    logger.info("starting event-logging consumer")

    while not _shutdown.is_set():
        try:
            _consume_once(settings.rabbitmq_url)
        except (pika.exceptions.AMQPConnectionError, OSError) as exc:
            if _shutdown.is_set():
                break
            logger.warning(
                "broker connection lost (%s); retrying in %ss",
                exc,
                _RECONNECT_DELAY_SECONDS,
            )
            _shutdown.wait(_RECONNECT_DELAY_SECONDS)
        else:
            break  # clean return == stop_consuming() ran (graceful shutdown)

    logger.info("consumer stopped")


if __name__ == "__main__":
    main()
