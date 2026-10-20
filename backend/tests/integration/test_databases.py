"""Database tests are skipped without a test server, unless the run requires them (plan §3 G0).

``REQUIRE_DATABASE_TESTS=1`` (set in CI) turns a missing ``TEST_DATABASE_URL`` into a failure, so
a green run can never hide that the migration was not applied.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg import sql

from tests.support import db
from tests.support.db import fresh_database_url


def test_missing_server_is_a_skip_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("REQUIRE_DATABASE_TESTS", raising=False)
    with pytest.raises(pytest.skip.Exception, match="not run"):
        next(fresh_database_url())


def test_missing_server_fails_when_database_tests_are_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("REQUIRE_DATABASE_TESTS", "1")
    with pytest.raises(pytest.fail.Exception, match="REQUIRE_DATABASE_TESTS"):
        next(fresh_database_url())


def test_only_a_template_left_by_a_dead_session_is_dropped() -> None:
    # A killed run never reaches pytest_sessionfinish; the next session drops its template.
    admin_url = db._admin_url()
    dead, live = "di1_template_999999999_deadbeef0000", f"di1_template_{os.getpid()}_live00000000"
    legacy = "di1_template_0123456789ab"  # an older branch's naming, without a pid
    for name in (dead, live, legacy):
        db._execute(admin_url, sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        db._drop_stale_templates(admin_url)

        with psycopg.connect(db.psycopg_url(admin_url)) as admin:
            left = {
                row[0]
                for row in admin.execute(
                    "SELECT datname FROM pg_database WHERE datname = ANY(%s)",
                    ([dead, live, legacy],),
                )
            }
        assert left == {live, legacy}
    finally:
        for name in (dead, live, legacy):
            db._drop(admin_url, name)
