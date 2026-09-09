"""HTTP-level tests for the REST API.

A ``TestClient`` over ``create_app()`` with ``get_db`` overridden to the
in-memory ``db_session`` fixture. Exercises status codes, response bodies and the
domain-error -> HTTP mapping.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.main import create_app

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
NEXT_WEEK = (date.today() + timedelta(days=7)).isoformat()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        # The context manager runs the app's lifespan (startup/shutdown).
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _new_car(client: TestClient, model: str = "Corolla", year: int = 2022) -> dict:
    resp = client.post("/cars", json={"model": model, "year": year})
    assert resp.status_code == 201
    return resp.json()


def _rental_body(car_id: int, *, start: str = TODAY, end: str = NEXT_WEEK) -> dict:
    return {
        "car_id": car_id,
        "customer_name": "Dana",
        "start_date": start,
        "end_date": end,
    }


# --- POST /cars ----------------------------------------------------------


def test_add_car_201(client: TestClient) -> None:
    body = _new_car(client, "Yaris", 2023)
    assert body["model"] == "Yaris"
    assert body["status"] == "available"
    assert isinstance(body["id"], int)
    assert "deleted_at" not in body


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "X", "year": 1500},
        {"model": "", "year": 2020},
        {"model": "X", "year": 2020, "id": 5},
        {"model": "X", "year": 2020, "status": "in_use"},
    ],
)
def test_add_car_422(client: TestClient, payload: dict) -> None:
    assert client.post("/cars", json=payload).status_code == 422


# --- GET /cars ---------------------------------------------------------


def test_list_cars_and_status_filter(client: TestClient) -> None:
    _new_car(client, "A", 2020)
    b = _new_car(client, "B", 2021)
    client.patch(f"/cars/{b['id']}", json={"status": "under_maintenance"})

    assert [c["model"] for c in client.get("/cars").json()] == ["A", "B"]
    filtered = client.get("/cars", params={"status": "under_maintenance"}).json()
    assert [c["id"] for c in filtered] == [b["id"]]


def test_list_cars_bad_status_422(client: TestClient) -> None:
    assert client.get("/cars", params={"status": "bogus"}).status_code == 422


# --- PATCH /cars/{id} ------------------------------------------------


def test_patch_car_status_toggle(client: TestClient) -> None:
    car = _new_car(client)
    resp = client.patch(f"/cars/{car['id']}", json={"status": "under_maintenance"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "under_maintenance"


def test_patch_car_missing_404_body(client: TestClient) -> None:
    resp = client.patch("/cars/999", json={"model": "Z"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "car 999 not found"}


def test_patch_car_illegal_transition_409(client: TestClient) -> None:
    car = _new_car(client)
    assert client.patch(f"/cars/{car['id']}", json={"status": "in_use"}).status_code == 409


def test_patch_car_explicit_null_422(client: TestClient) -> None:
    car = _new_car(client)
    assert client.patch(f"/cars/{car['id']}", json={"model": None}).status_code == 422


def test_patch_car_empty_body_is_200(client: TestClient) -> None:
    car = _new_car(client)
    resp = client.patch(f"/cars/{car['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["id"] == car["id"]


# --- path-id validation --------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [("patch", "/cars/0"), ("delete", "/cars/-1"), ("post", "/rentals/0/end")],
)
def test_path_id_must_be_positive(
    client: TestClient, method: str, path: str
) -> None:
    call = getattr(client, method)
    kwargs = {"json": {}} if method == "patch" else {}
    assert call(path, **kwargs).status_code == 422


# --- DELETE /cars/{id} ---------------------------------------------


def test_delete_car_204_empty_body(client: TestClient) -> None:
    car = _new_car(client)
    resp = client.delete(f"/cars/{car['id']}")
    assert resp.status_code == 204
    assert resp.content == b""
    assert client.get("/cars").json() == []


def test_delete_car_missing_404(client: TestClient) -> None:
    assert client.delete("/cars/999").status_code == 404


def test_delete_car_with_active_rental_409_body(client: TestClient) -> None:
    car = _new_car(client)
    client.post("/rentals", json=_rental_body(car["id"]))
    resp = client.delete(f"/cars/{car['id']}")
    assert resp.status_code == 409
    assert resp.json() == {
        "detail": f"car {car['id']} has an active rental and cannot be removed"
    }


# --- POST /rentals ------------------------------------------------


def test_register_rental_201_marks_car_in_use(client: TestClient) -> None:
    car = _new_car(client)
    resp = client.post("/rentals", json=_rental_body(car["id"]))
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_active"] is True
    assert body["returned_date"] is None
    assert client.get("/cars").json()[0]["status"] == "in_use"


def test_register_rental_car_unavailable_409(client: TestClient) -> None:
    car = _new_car(client)
    client.patch(f"/cars/{car['id']}", json={"status": "under_maintenance"})
    assert client.post("/rentals", json=_rental_body(car["id"])).status_code == 409


def test_register_rental_missing_car_404(client: TestClient) -> None:
    assert client.post("/rentals", json=_rental_body(999)).status_code == 404


def test_register_rental_start_not_today_422_body(client: TestClient) -> None:
    car = _new_car(client)
    resp = client.post("/rentals", json=_rental_body(car["id"], start=TOMORROW))
    assert resp.status_code == 422
    assert resp.json() == {"detail": "a rental must start today"}


def test_register_rental_end_before_start_422(client: TestClient) -> None:
    car = _new_car(client)
    # DTO-level validator (end_date < start_date) -> FastAPI 422
    resp = client.post("/rentals", json=_rental_body(car["id"], end=YESTERDAY))
    assert resp.status_code == 422


# --- POST /rentals/{id}/end -------------------------------------


def test_end_rental_200_frees_car(client: TestClient) -> None:
    car = _new_car(client)
    rental = client.post("/rentals", json=_rental_body(car["id"])).json()
    resp = client.post(f"/rentals/{rental['id']}/end")
    assert resp.status_code == 200
    body = resp.json()
    assert body["returned_date"] == TODAY
    assert body["is_active"] is False
    assert client.get("/cars").json()[0]["status"] == "available"


def test_end_rental_missing_404(client: TestClient) -> None:
    assert client.post("/rentals/999/end").status_code == 404


def test_end_rental_already_ended_409(client: TestClient) -> None:
    car = _new_car(client)
    rental = client.post("/rentals", json=_rental_body(car["id"])).json()
    client.post(f"/rentals/{rental['id']}/end")
    assert client.post(f"/rentals/{rental['id']}/end").status_code == 409
