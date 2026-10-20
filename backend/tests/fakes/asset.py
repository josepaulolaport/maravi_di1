"""Shared values for tests that build Asset's `Instrument` by hand."""

from __future__ import annotations

from datetime import UTC, datetime

CREATED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
"""When a hand-built instrument was registered; no test asserts it."""
