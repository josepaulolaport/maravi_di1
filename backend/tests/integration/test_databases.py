"""Database tests are skipped without a test server, unless the run requires them (plan §3 G0).

``REQUIRE_DATABASE_TESTS=1`` (set in CI) turns a missing ``TEST_DATABASE_URL`` into a failure, so
a green run can never hide that the migration was not applied.
"""

from __future__ import annotations

import pytest

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
