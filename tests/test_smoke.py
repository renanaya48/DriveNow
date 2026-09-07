"""Skeleton smoke tests.

These verify the wiring created in steps 0-1. Real unit tests for the service
layer (>= 4 of them) are added in step 10.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.messaging.publisher import EventPublisher, NullPublisher
from app.models import CarStatus


def test_health_endpoint_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint_exposes_prometheus_text() -> None:
    client = TestClient(create_app())
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "drivenow_" in response.text


def test_null_publisher_satisfies_protocol() -> None:
    publisher: EventPublisher = NullPublisher()
    assert isinstance(publisher, EventPublisher)
    publisher.publish("rental.started", {"rental_id": 1})


def test_car_status_values() -> None:
    assert {s.value for s in CarStatus} == {"available", "in_use", "under_maintenance"}
