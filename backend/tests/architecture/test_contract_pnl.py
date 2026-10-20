"""PnL's statuses match the schema's CHECK lists (plan §3, W0.3c; interfaces.md "PnL"). The
calculators are tested in tests/unit/pnl."""

from __future__ import annotations

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from tests.architecture.schema_checks import check_values


@pytest.mark.parametrize(
    "constraint",
    [
        "position_metrics_pnl_status",
        "portfolio_metrics_pnl_status",
        # A portfolio day stores its market value's completeness (COMPLETE or MISSING).
        "portfolio_metrics_valuation_status",
    ],
)
def test_completeness_matches_the_schema_check(constraint: str) -> None:
    assert {status.value for status in CalculationCompleteness} == check_values(constraint)
