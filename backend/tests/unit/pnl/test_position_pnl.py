"""Position P&L: Q[D-1] × (PU_D − PU_{D-1}) (spec §8.1; OQ-1, OQ-4).

``None`` when a required price is missing; exactly 0 with no price when Q[D-1] = 0.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from di1.modules.pnl.domain.position_pnl import calculate_position_pnl

D = Decimal


@pytest.mark.parametrize(
    ("quantity", "previous", "current", "expected"),
    [
        (10, "90000", "90100", "1000"),  # long, PU up
        (-5, "90000", "90100", "-500"),  # short, PU up
        (-10, "90000", "89900", "1000"),  # short, PU down
        (10, "99990", "0", "-999900"),  # day after maturity: PU_D = 0 (OQ-1)
        (10, "0", "0", "0"),  # later days after maturity
    ],
)
def test_signed_quantity_times_the_reference_move(
    quantity: int, previous: str, current: str, expected: str
) -> None:
    assert calculate_position_pnl(quantity, D(previous), D(current)) == D(expected)


def test_no_previous_position_is_exactly_zero_without_prices() -> None:
    # OQ-4
    result = calculate_position_pnl(0, None, None)
    assert result == D("0")
    assert result is not None and not result.is_signed()


@pytest.mark.parametrize(("previous", "current"), [(None, "90100"), ("90000", None), (None, None)])
def test_open_position_with_a_missing_price_is_none(
    previous: str | None, current: str | None
) -> None:
    result = calculate_position_pnl(
        10,
        None if previous is None else D(previous),
        None if current is None else D(current),
    )
    assert result is None


def test_short_with_unchanged_price_is_unsigned_zero() -> None:
    result = calculate_position_pnl(-5, D("90000"), D("90000"))
    assert result is not None and result == 0 and not result.is_signed()
