"""The reference PU around maturity (spec §5, §7.4; OQ-1): the exact-date price up to and
including the maturity date, 0 by definition after it, whatever price exists. An instrument
without a maturity date never matures."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.modules.portfolio.public import is_past_maturity, reference_pu_on

MATURITY = date(2027, 1, 6)
BEFORE, AFTER = date(2027, 1, 5), date(2027, 1, 7)


@pytest.mark.parametrize(
    ("day", "maturity", "past"),
    [
        pytest.param(BEFORE, MATURITY, False, id="before"),
        pytest.param(MATURITY, MATURITY, False, id="on-the-maturity-date-closing-is-allowed"),
        pytest.param(AFTER, MATURITY, True, id="after"),
        pytest.param(AFTER, None, False, id="no-maturity-date"),
    ],
)
def test_only_a_day_after_the_maturity_date_is_past_maturity(
    day: date, maturity: date | None, past: bool
) -> None:
    assert is_past_maturity(day, maturity) is past


@pytest.mark.parametrize(
    ("day", "maturity", "price", "reference"),
    [
        pytest.param(BEFORE, MATURITY, "99985", "99985", id="before-exact-date-price"),
        pytest.param(MATURITY, MATURITY, "100000", "100000", id="on-maturity-exact-date-price"),
        # No carry-forward and never zero (spec §5, §8.3).
        pytest.param(MATURITY, MATURITY, None, None, id="on-maturity-missing-stays-missing"),
        pytest.param(AFTER, MATURITY, None, "0", id="after-zero-without-a-price"),
        pytest.param(AFTER, MATURITY, "100000", "0", id="after-zero-whatever-the-price"),
        pytest.param(AFTER, None, "95000", "95000", id="no-maturity-date-exact-date-price"),
        pytest.param(AFTER, None, None, None, id="no-maturity-date-missing-stays-missing"),
    ],
)
def test_the_reference_pu_is_the_exact_date_price_until_maturity_then_zero(
    day: date, maturity: date | None, price: str | None, reference: str | None
) -> None:
    result = reference_pu_on(day, maturity, None if price is None else Decimal(price))

    assert result == (None if reference is None else Decimal(reference))
