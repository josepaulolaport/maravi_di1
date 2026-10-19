"""The reference PU around maturity (spec §5, §7.4; OQ-1): the exact-date price up to and
including the maturity date, 0 by definition after it, whatever price exists."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from di1.modules.portfolio.public import is_past_maturity, reference_pu_on

MATURITY = date(2027, 1, 6)
BEFORE, AFTER = date(2027, 1, 5), date(2027, 1, 7)


def test_only_a_day_after_the_maturity_date_is_past_maturity() -> None:
    assert not is_past_maturity(BEFORE, MATURITY)
    assert not is_past_maturity(MATURITY, MATURITY)  # closing on the maturity date is allowed
    assert is_past_maturity(AFTER, MATURITY)


def test_up_to_maturity_the_reference_pu_is_the_exact_date_price() -> None:
    assert reference_pu_on(BEFORE, MATURITY, Decimal("99985")) == Decimal("99985")
    assert reference_pu_on(MATURITY, MATURITY, Decimal("100000")) == Decimal("100000")


def test_up_to_maturity_a_missing_price_stays_missing() -> None:
    # No carry-forward and never zero (spec §5, §8.3).
    assert reference_pu_on(MATURITY, MATURITY, None) is None


def test_after_maturity_the_reference_pu_is_zero_with_or_without_a_price() -> None:
    assert reference_pu_on(AFTER, MATURITY, None) == 0
    assert reference_pu_on(AFTER, MATURITY, Decimal("100000")) == 0
