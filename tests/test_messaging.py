"""Unit tests for the messaging layer (publisher + consumer).

No live broker: ``pika.BlockingConnection`` is patched, so the tests exercise
our topology declarations, envelope format, retry policy and message handling
without a network. ``pika``'s real exception classes and ``BasicProperties`` are
kept so the retry ``except`` clauses and property assertions are meaningful.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import pika.exceptions
import pytest

from app.api.deps import get_event_publisher
from app.messaging import consumer
from app.messaging.publisher import NullPublisher
from app.messaging.rabbitmq import EXCHANGE, RabbitMQPublisher, build_envelope

_URL = "amqp://guest:guest@localhost:5672/"


# --- build_envelope ----------------------------------------------------------


def test_build_envelope_shape() -> None:
    payload = {"car_id": 7}
    env = build_envelope("car.added", payload)

    assert uuid.UUID(env["id"])  # parses as a UUID
    assert datetime.fromisoformat(env["occurred_at"])  # parses as ISO-8601
    assert env["event_type"] == "car.added"
    assert env["payload"] == payload


def test_build_envelope_ids_are_unique() -> None:
    assert build_envelope("car.added", {})["id"] != build_envelope("car.added", {})["id"]


# --- RabbitMQPublisher: connection parameters -------------------------------


def test_publisher_uses_bounded_timeouts() -> None:
    params = RabbitMQPublisher(_URL)._params
    assert params.socket_timeout == 3
    assert params.blocked_connection_timeout == 3
    assert params.connection_attempts == 1


# --- RabbitMQPublisher: publish path --------------------------------------


@pytest.fixture
def blocking_connection() -> Iterator[mock.MagicMock]:
    """Patch ``pika.BlockingConnection`` in the publisher module."""
    with mock.patch("app.messaging.rabbitmq.pika.BlockingConnection") as bc:
        yield bc


def _channel_of(blocking_connection: mock.MagicMock) -> mock.MagicMock:
    channel: mock.MagicMock = blocking_connection.return_value.channel.return_value
    return channel


def test_publish_declares_topology_and_publishes(
    blocking_connection: mock.MagicMock,
) -> None:
    channel = _channel_of(blocking_connection)
    publisher = RabbitMQPublisher(_URL)

    publisher.publish("rental.started", {"rental_id": 1, "car_id": 2})

    channel.exchange_declare.assert_called_once_with(
        exchange=EXCHANGE, exchange_type="topic", durable=True
    )
    channel.confirm_delivery.assert_called_once()

    channel.basic_publish.assert_called_once()
    kwargs = channel.basic_publish.call_args.kwargs
    assert kwargs["exchange"] == EXCHANGE
    assert kwargs["routing_key"] == "rental.started"
    assert kwargs["mandatory"] is True

    props = kwargs["properties"]
    assert props.delivery_mode == 2
    assert props.content_type == "application/json"
    assert props.type == "rental.started"

    envelope = json.loads(kwargs["body"])
    assert envelope["event_type"] == "rental.started"
    assert envelope["payload"] == {"rental_id": 1, "car_id": 2}
    assert envelope["id"] == props.message_id


def test_publish_reuses_the_channel(blocking_connection: mock.MagicMock) -> None:
    channel = _channel_of(blocking_connection)
    publisher = RabbitMQPublisher(_URL)

    publisher.publish("car.added", {"car_id": 1})
    publisher.publish("car.added", {"car_id": 2})

    assert blocking_connection.call_count == 1
    assert channel.basic_publish.call_count == 2


def test_publish_retries_once_then_succeeds(
    blocking_connection: mock.MagicMock,
) -> None:
    channel = _channel_of(blocking_connection)
    channel.basic_publish.side_effect = [
        pika.exceptions.AMQPConnectionError("broker gone"),
        None,
    ]
    publisher = RabbitMQPublisher(_URL)

    publisher.publish("car.added", {"car_id": 1})  # must not raise

    assert blocking_connection.call_count == 2  # reset + fresh connection


def test_publish_reraises_when_retry_also_fails(
    blocking_connection: mock.MagicMock,
) -> None:
    channel = _channel_of(blocking_connection)
    channel.basic_publish.side_effect = pika.exceptions.StreamLostError("still gone")
    publisher = RabbitMQPublisher(_URL)

    with pytest.raises(pika.exceptions.StreamLostError):
        publisher.publish("car.added", {"car_id": 1})

    assert blocking_connection.call_count == 2
    assert publisher._conn is None  # reset on the way out


def test_publish_does_not_retry_non_retryable_error(
    blocking_connection: mock.MagicMock,
) -> None:
    channel = _channel_of(blocking_connection)
    channel.basic_publish.side_effect = pika.exceptions.UnroutableError([])
    publisher = RabbitMQPublisher(_URL)

    with pytest.raises(pika.exceptions.UnroutableError):
        publisher.publish("car.added", {"car_id": 1})

    assert blocking_connection.call_count == 1  # no second attempt, no reset


def test_publish_serialization_error_never_opens_a_connection(
    blocking_connection: mock.MagicMock,
) -> None:
    publisher = RabbitMQPublisher(_URL)

    with pytest.raises(TypeError):
        publisher.publish("car.added", {"bad": object()})

    blocking_connection.assert_not_called()


def test_close_drops_the_connection(blocking_connection: mock.MagicMock) -> None:
    publisher = RabbitMQPublisher(_URL)
    publisher.publish("car.added", {"car_id": 1})

    publisher.close()

    blocking_connection.return_value.close.assert_called_once()
    assert publisher._conn is None
    assert publisher._channel is None


# --- get_event_publisher selection ---------------------------------------


@pytest.fixture
def _reset_publisher_cache() -> Iterator[None]:
    get_event_publisher.cache_clear()
    yield
    get_event_publisher.cache_clear()


@pytest.mark.usefixtures("_reset_publisher_cache")
def test_get_event_publisher_is_null_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.deps.get_settings",
        lambda: SimpleNamespace(enable_message_queue=False, rabbitmq_url=_URL),
    )
    assert isinstance(get_event_publisher(), NullPublisher)


@pytest.mark.usefixtures("_reset_publisher_cache")
def test_get_event_publisher_is_rabbitmq_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.deps.get_settings",
        lambda: SimpleNamespace(enable_message_queue=True, rabbitmq_url=_URL),
    )
    with mock.patch("app.messaging.rabbitmq.pika.BlockingConnection") as bc:
        publisher = get_event_publisher()
        assert isinstance(publisher, RabbitMQPublisher)
        bc.assert_not_called()  # connection is lazy


# --- consumer: message handling ----------------------------------------


def _delivery(tag: int = 7) -> mock.MagicMock:
    return mock.MagicMock(delivery_tag=tag)


def test_consumer_acks_a_valid_envelope(caplog: pytest.LogCaptureFixture) -> None:
    channel = mock.MagicMock()
    body = json.dumps(build_envelope("car.added", {"car_id": 1})).encode()

    with caplog.at_level(logging.INFO, logger="app.messaging.consumer"):
        consumer._on_message(channel, _delivery(), None, body)

    channel.basic_ack.assert_called_once_with(delivery_tag=7)
    channel.basic_nack.assert_not_called()
    assert "event received event_type=car.added" in caplog.text


def test_consumer_drops_malformed_json(caplog: pytest.LogCaptureFixture) -> None:
    channel = mock.MagicMock()

    with caplog.at_level(logging.ERROR, logger="app.messaging.consumer"):
        consumer._on_message(channel, _delivery(), None, b"not json{")

    channel.basic_nack.assert_called_once_with(delivery_tag=7, requeue=False)
    channel.basic_ack.assert_not_called()
    assert "dropping malformed event" in caplog.text


def test_consumer_drops_envelope_missing_a_required_key() -> None:
    channel = mock.MagicMock()
    body = json.dumps({"id": "x", "occurred_at": "now", "payload": {}}).encode()

    consumer._on_message(channel, _delivery(), None, body)

    channel.basic_nack.assert_called_once_with(delivery_tag=7, requeue=False)
    channel.basic_ack.assert_not_called()


def test_consumer_drops_envelope_with_wrong_field_types() -> None:
    channel = mock.MagicMock()
    body = json.dumps(
        {"id": 17, "event_type": None, "occurred_at": [], "payload": "hi"}
    ).encode()

    consumer._on_message(channel, _delivery(), None, body)

    channel.basic_nack.assert_called_once_with(delivery_tag=7, requeue=False)
    channel.basic_ack.assert_not_called()


def test_consumer_main_exits_when_queue_disabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        consumer, "get_settings", lambda: SimpleNamespace(enable_message_queue=False)
    )
    monkeypatch.setattr(consumer, "configure_logging", lambda _settings: None)

    with (
        mock.patch("app.messaging.consumer.pika.BlockingConnection") as bc,
        caplog.at_level(logging.WARNING, logger="app.messaging.consumer"),
    ):
        consumer.main()

    bc.assert_not_called()
    assert "message queue disabled" in caplog.text
