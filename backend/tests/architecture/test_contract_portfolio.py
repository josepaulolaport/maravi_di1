"""Portfolio's statuses match the schema's CHECK lists (plan §3, W0.3c; interfaces.md
"Portfolio"). The read models' JSON shapes are tested in
tests/unit/portfolio/test_http_schemas.py."""

from __future__ import annotations

from di1.modules.portfolio.public import ValuationStatus
from tests.architecture.schema_checks import check_values


def test_an_asset_valuation_status_matches_the_position_metrics_check() -> None:
    # A flat position is NOT_REQUIRED: worth 0 with or without a price (spec §8.3).
    assert {status.value for status in ValuationStatus} == check_values(
        "position_metrics_valuation_status"
    )
