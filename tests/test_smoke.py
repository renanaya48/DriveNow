"""Smoke tests for application wiring: routers, error handlers.

Model/schema tests live in test_models.py; `/metrics` is covered by test_metrics.py.
"""

from __future__ import annotations

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
