"""Tests for the Prometheus metrics: /metrics scrape + the latency middleware."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.metrics import CARS, ONGOING_RENTALS, OPERATIONS_TOTAL, REQUEST_LATENCY
from app.main import create_app
from app.models import Car
from app.schemas.car import CarCreate

TODAY = date.today().isoformat()
NEXT_WEEK = (date.today() + timedelta(days=7)).isoformat()


def _reset() -> None:
    REQUEST_LATENCY.clear()
    OPERATIONS_TOTAL.clear()
    CARS.clear()
    ONGOING_RENTALS.set(0)


@pytest.fixture(autouse=True)
def reset_metrics() -> Iterator[None]:
    _reset()
    yield
    _reset()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _value(text: str, name: str, **labels: str) -> float | None:
    """The float value of a sample line, matched by metric name + labels (in order)."""
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        pattern = re.escape(f"{name}{{{label_str}}}") + r"\s+([0-9eE.+-]+)"
    else:
        pattern = r"^" + re.escape(name) + r"\s+([0-9eE.+-]+)"
    match = re.search(pattern, text, re.MULTILINE)
    return float(match.group(1)) if match else None


def _add_car(client: TestClient, model: str = "Corolla") -> dict[str, Any]:
    resp = client.post("/cars", json={"model": model, "year": 2022})
    assert resp.status_code == 201
    return resp.json()


def _rental(car_id: int) -> dict[str, Any]:
    return {
        "car_id": car_id,
        "customer_name": "Dana",
        "start_date": TODAY,
        "end_date": NEXT_WEEK,
    }


# --- exposition ------------------------------------------------------


def test_metrics_endpoint_exposes_all_families(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    for name in (
        "drivenow_request_duration_seconds",
        "drivenow_operations_total",
        "drivenow_cars",
        "drivenow_ongoing_rentals",
    ):
        assert name in resp.text


# --- gauges (scrape-time DB counts) -------------------------------


def test_cars_gauge_by_status(client: TestClient) -> None:
    a = _add_car(client, "A")
    _add_car(client, "B")
    client.patch(f"/cars/{a['id']}", json={"status": "under_maintenance"})

    text = client.get("/metrics").text
    assert _value(text, "drivenow_cars", status="available") == 1.0
    assert _value(text, "drivenow_cars", status="under_maintenance") == 1.0
    assert _value(text, "drivenow_cars", status="in_use") == 0.0


def test_cars_gauge_excludes_deleted(client: TestClient) -> None:
    car = _add_car(client)
    client.delete(f"/cars/{car['id']}")

    text = client.get("/metrics").text
    assert _value(text, "drivenow_cars", status="available") == 0.0


def test_ongoing_rentals_gauge_tracks_lifecycle(client: TestClient) -> None:
    car = _add_car(client)
    rental = client.post("/rentals", json=_rental(car["id"])).json()

    text = client.get("/metrics").text
    assert _value(text, "drivenow_ongoing_rentals") == 1.0
    assert _value(text, "drivenow_cars", status="in_use") == 1.0

    client.post(f"/rentals/{rental['id']}/end")
    text = client.get("/metrics").text
    assert _value(text, "drivenow_ongoing_rentals") == 0.0
    assert _value(text, "drivenow_cars", status="available") == 1.0


# --- latency histogram + request counter --------------------


def test_latency_histogram_counts_a_request(client: TestClient) -> None:
    before = _value(
        client.get("/metrics").text,
        "drivenow_request_duration_seconds_count",
        operation="POST /cars",
    )
    _add_car(client)
    after = _value(
        client.get("/metrics").text,
        "drivenow_request_duration_seconds_count",
        operation="POST /cars",
    )
    assert (before or 0.0) + 1.0 == after


def test_metrics_and_health_are_not_timed(client: TestClient) -> None:
    client.get("/metrics")
    client.get("/health")
    text = client.get("/metrics").text
    assert (
        _value(text, "drivenow_request_duration_seconds_count", operation="GET /metrics")
        is None
    )
    assert (
        _value(text, "drivenow_request_duration_seconds_count", operation="GET /health")
        is None
    )


def test_operations_total_outcome_2xx_and_4xx(client: TestClient) -> None:
    _add_car(client)
    client.patch("/cars/999", json={"model": "Z"})  # 404

    text = client.get("/metrics").text
    assert (
        _value(
            text, "drivenow_operations_total", operation="POST /cars", outcome="2xx"
        )
        == 1.0
    )
    assert (
        _value(
            text,
            "drivenow_operations_total",
            operation="PATCH /cars/{car_id}",
            outcome="4xx",
        )
        == 1.0
    )


def test_operations_total_outcome_5xx_recorded_once(db_session: Session) -> None:
    from app.api.deps import get_car_service

    class Boom:
        def add_car(self, dto: CarCreate) -> Car:
            raise RuntimeError("kaboom")

    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_car_service] = lambda: Boom()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        assert test_client.post("/cars", json={"model": "X", "year": 2020}).status_code == 500
        text = test_client.get("/metrics").text

    assert (
        _value(
            text, "drivenow_operations_total", operation="POST /cars", outcome="5xx"
        )
        == 1.0
    )
    assert (
        _value(
            text,
            "drivenow_request_duration_seconds_count",
            operation="POST /cars",
        )
        == 1.0
    )
