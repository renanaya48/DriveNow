"""Unit tests for app/core/db.py: session lifecycle and engine connect args.

Behaviour, not implementation - we check that a session is yielded and always
closed, and that the sqlite-only ``connect_args`` branch fires for a sqlite URL
and not otherwise. ``get_engine`` is ``@lru_cache``d, so every test that swaps
settings clears the cache on the way in and out.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from app.core import db


def test_get_db_yields_a_session_and_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    session = mock.MagicMock()
    monkeypatch.setattr(db, "SessionLocal", lambda: session)

    gen = db.get_db()
    assert next(gen) is session
    session.close.assert_not_called()

    gen.close()  # runs the generator's finally
    session.close.assert_called_once()


def test_get_db_closes_the_session_on_an_error_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = mock.MagicMock()
    monkeypatch.setattr(db, "SessionLocal", lambda: session)

    gen = db.get_db()
    next(gen)
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))

    session.close.assert_called_once()


def test_get_engine_adds_check_same_thread_for_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        db, "create_engine", lambda url, **kw: captured.update(kw) or mock.MagicMock()
    )
    monkeypatch.setattr(
        db, "get_settings", lambda: SimpleNamespace(database_url="sqlite:///:memory:")
    )

    db.get_engine.cache_clear()
    try:
        db.get_engine()
    finally:
        db.get_engine.cache_clear()

    assert captured["connect_args"] == {"check_same_thread": False}


def test_get_engine_has_no_sqlite_args_for_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        db, "create_engine", lambda url, **kw: captured.update(kw) or mock.MagicMock()
    )
    monkeypatch.setattr(
        db,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+psycopg://drivenow:drivenow@localhost/drivenow"
        ),
    )

    db.get_engine.cache_clear()
    try:
        db.get_engine()
    finally:
        db.get_engine.cache_clear()

    assert captured["connect_args"] == {}
