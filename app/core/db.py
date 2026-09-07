"""Database engine and session management.

The rest of the app never imports SQLAlchemy engine internals directly - it
depends on :func:`get_db` (a FastAPI dependency) or on ``SessionLocal``.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the process-wide SQLAlchemy engine (once)."""
    settings = get_settings()
    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("sqlite"):
        # Needed when a SQLite connection is shared across threads (tests).
        connect_args["check_same_thread"] = False
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


SessionLocal = sessionmaker(
    bind=get_engine(),
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """Yield a database session and always close it.

    Commit/rollback policy belongs to the service layer, not here.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
