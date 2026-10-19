"""Which database errors the worker retries: only those a retry or a restart can clear."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from di1.modules.processing.infrastructure.persistence.errors import is_transient


def _dbapi(kind: type[DBAPIError], *, invalidated: bool = False) -> DBAPIError:
    return kind(
        "UPDATE processing.requests", {}, Exception("driver"), connection_invalidated=invalidated
    )


@pytest.mark.parametrize(
    ("error", "transient"),
    [
        (_dbapi(OperationalError), True),  # a dropped connection, a lock or statement timeout
        (_dbapi(DBAPIError, invalidated=True), True),  # the pool lost the connection
        (PoolTimeoutError("QueuePool limit reached"), True),  # no connection free in time
        (_dbapi(DBAPIError), False),
        (_dbapi(IntegrityError), False),  # a CHECK or a foreign key: the same on every try
        (_dbapi(ProgrammingError), False),  # wrong SQL
        (ValueError("a bug"), False),
        (RuntimeError("a bug"), False),
    ],
)
def test_only_a_connection_or_operational_error_is_transient(
    error: Exception, transient: bool
) -> None:
    assert is_transient(error) is transient
