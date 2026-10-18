"""Throwaway PostgreSQL databases for integration tests (CLAUDE.md §4: never a shared database).

``TEST_DATABASE_URL`` is an admin URL on a test server (SQLAlchemy form,
``postgresql+psycopg://user:password@host:port/postgres``). Each test gets a new database with a
unique name, dropped afterwards. Without the variable the database tests are skipped, and the
run reports them as skipped: they are then **not verified**. With ``REQUIRE_DATABASE_TESTS=1``
(set in CI) a missing variable fails the run instead, so a green run always applied them.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url


def psycopg_url(sqlalchemy_url: str) -> str:
    """The libpq form of a SQLAlchemy URL (``postgresql+psycopg://`` → ``postgresql://``)."""
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


def fresh_database_url() -> Iterator[str]:
    """Create a uniquely named database, yield its SQLAlchemy URL, then drop it."""
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        if os.environ.get("REQUIRE_DATABASE_TESTS") == "1":
            pytest.fail("REQUIRE_DATABASE_TESTS=1 but TEST_DATABASE_URL is not set")
        pytest.skip("TEST_DATABASE_URL is not set: database tests not run")
    name = f"di1_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(psycopg_url(admin_url), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(psycopg_url(admin_url), autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
