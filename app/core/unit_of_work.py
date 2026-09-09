"""Transaction boundary abstraction.

Repositories ``flush`` but never ``commit`` / ``rollback``. A service opens a
``UnitOfWork`` around a set of repository calls and commits (or rolls back) them
as one. The service depends on the Protocol, not on the SQLAlchemy ``Session``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session


@runtime_checkable
class UnitOfWork(Protocol):
    """Commit or roll back the work done since the last boundary."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    """A :class:`UnitOfWork` backed by a SQLAlchemy session.

    The session is shared with the repositories the service holds, so one
    ``commit`` persists every change they made.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
