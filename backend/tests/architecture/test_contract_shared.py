"""Shared value types match the schema's CHECK lists (plan §3, W0.3b)."""

from __future__ import annotations

from di1.shared.input_kind import InputKind


def test_input_kind_matches_the_schema_checks() -> None:
    assert {kind.value for kind in InputKind} == {"PU", "RATE"}
