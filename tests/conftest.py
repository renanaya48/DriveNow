"""Shared pytest fixtures.

An in-memory SQLite engine with a clean schema per test and a Session bound to
it. Step 10 (service-layer tests) builds on these - e.g. by overriding the
FastAPI ``get_db`` dependency with ``db_session``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Fresh in-memory SQLite DB with the full schema, torn down after the test.

    ``StaticPool`` keeps a single connection so every session sees the same
    in-memory database. A ``connect`` hook turns on FK enforcement, which SQLite
    leaves off by default.
    """
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fks(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A Session bound to the per-test engine; rolled back and closed after."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
