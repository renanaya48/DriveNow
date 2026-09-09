"""Smoke tests for application wiring: routers, error handlers, lifespan.

Model/schema tests live in test_models.py; `/metrics` is covered by test_metrics.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.messaging.publisher import EventPublisher, NullPublisher


def test_health_endpoint_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_null_publisher_satisfies_protocol() -> None:
    publisher: EventPublisher = NullPublisher()
    assert isinstance(publisher, EventPublisher)
    publisher.publish("rental.started", {"rental_id": 1})


def test_lifespan_shutdown_closes_the_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    """On shutdown the app calls ``publisher.close()`` when the publisher has one.

    ``app.main`` calls ``get_event_publisher()`` directly in the lifespan (not via
    ``Depends``), so we patch the name it imported rather than ``dependency_overrides``.
    """

    class ClosingPublisher:
        def __init__(self) -> None:
            self.closed = False

        def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...

        def close(self) -> None:
            self.closed = True

    spy = ClosingPublisher()
    monkeypatch.setattr("app.main.get_event_publisher", lambda: spy)

    with TestClient(create_app()):
        pass

    assert spy.closed is True
