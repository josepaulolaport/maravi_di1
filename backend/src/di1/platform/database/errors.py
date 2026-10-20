"""Which database errors are transient: those a retry, or a worker's restart, can clear."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


def is_transient(error: Exception) -> bool:
    """An operational error (a dropped connection, a lock or statement timeout, the server
    restarting), any driver error that invalidated the connection, or the pool's checkout
    timeout. Anything else (a CHECK or a foreign key, wrong SQL, a bug in our code) fails the
    same way on every try. Limits: psycopg reports a few deterministic errors as operational
    (SQLSTATE class 54, "program limit exceeded"), which this treats as transient; none comes
    from the worker's fixed queries. A bare asyncio TimeoutError or OSError that SQLAlchemy did
    not wrap is not transient here: the run is ended FAILED (OQ-47 item 7), not retried."""
    if isinstance(error, OperationalError | PoolTimeoutError):
        return True
    return isinstance(error, DBAPIError) and error.connection_invalidated
