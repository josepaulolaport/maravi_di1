"""Fixtures for Portfolio's integration tests: a fresh, migrated PostgreSQL 16 database per test
with the DI1 catalogue (the published rows reference ``asset.instruments``).

The fixtures are the Asset tests' own, imported so that both modules build their databases the
same way."""

from __future__ import annotations

from tests.integration.asset.conftest import (  # noqa: F401  (pytest registers imported fixtures)
    Di1Catalogue,
    database_url,
    di1,
    engine,
    migrated_database_url,
    seed_di1,
    session_factory,
    settings,
)
