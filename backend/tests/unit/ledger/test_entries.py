"""A stored ledger entry, its cash effect, and the entries a batch delete removes.

Rules: spec §6 and §7.3 (a trade's cash effect is −signed_quantity × execution_pu, computed on
read, never stored; a cash entry's effect is its signed amount); OQ-24 and the user's decision of
2026-10-19 (one batch deletes entries of either type, for good, all or nothing); interfaces
"Ledger".
Expected cash effects are the MSW golden fixtures (frontend/src/api/mocks/fixtures.ts at 57b4df0).
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.ledger.domain.entries import validate_deletion
from di1.shared.errors import ErrorCode, ErrorDetail
from tests.support.builders import DI1F28, ledger_cash, ledger_trade

# --- cash effect --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "pu", "expected"),
    [
        (10, "89006.4625467350", "-890064.6254673500"),  # a buy spends cash
        (5, "82057.00", "-410285.00"),
        (-4, "89102.2226533433", "356408.8906133732"),  # a sell receives cash
    ],
)
def test_a_trades_cash_effect_is_minus_quantity_times_pu(
    quantity: int, pu: str, expected: str
) -> None:
    effect = ledger_trade(DI1F28.id, date(2026, 10, 14), quantity, pu).cash_effect

    assert effect == Decimal(expected)
    assert str(effect) == expected  # exact: no rounding, scale of the PU kept


def test_the_cash_effect_is_exact_for_the_largest_quantity() -> None:
    # 2147483647 × (100000 − 10⁻¹⁰) = 214748364700000 − 0.2147483647
    effect = ledger_trade(DI1F28.id, date(2026, 10, 14), 2**31 - 1, "99999.9999999999").cash_effect
    assert effect == Decimal("-214748364699999.7852516353")


def test_a_cash_entrys_effect_is_its_signed_amount() -> None:
    assert ledger_cash(date(2026, 10, 14), "1500000.00").cash_effect == Decimal("1500000.00")
    assert ledger_cash(date(2026, 10, 14), "-50000.00").cash_effect == Decimal("-50000.00")


def test_the_order_key_is_date_time_seq() -> None:
    entry = ledger_cash(date(2026, 10, 14), "1500000.00")
    assert entry.order_key == (date(2026, 10, 14), time(9, 0), 1)


# --- batch delete -------------------------------------------------------------------------------


def test_an_unknown_id_deletes_nothing() -> None:
    known = ledger_trade(DI1F28.id, date(2026, 10, 14), 10, "89006.4625467350")
    assert validate_deletion([known.id, uuid4()], {known.id}) == (
        ErrorDetail(ErrorCode.NOT_FOUND, "Lançamento não encontrado."),
    )


def test_an_empty_batch_is_rejected() -> None:
    (error,) = validate_deletion([], set())

    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.field == "ids"


def test_a_mixed_batch_deletes_every_requested_entry() -> None:
    deposit = ledger_cash(date(2026, 10, 14), "1500000.00")
    sell = ledger_trade(DI1F28.id, date(2026, 10, 16), -4, "89006.4625467350")

    assert validate_deletion([sell.id, deposit.id], {deposit.id, sell.id}) == ()


def test_a_repeated_id_is_valid() -> None:
    entry = ledger_trade(DI1F28.id, date(2026, 10, 14), 10, "89006.4625467350")

    assert validate_deletion([entry.id, entry.id], {entry.id}) == ()
