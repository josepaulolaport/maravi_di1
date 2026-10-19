"""A stored ledger entry, its cash effect, and the entries a batch soft delete marks.

Rules: spec §6 and §7.3 (a trade's cash effect is −signed_quantity × execution_pu, computed on
read, never stored; a cash entry's effect is its signed amount); OQ-24 (one batch deletes entries
of either type all or nothing); interfaces "Ledger".
Expected cash effects are the MSW golden fixtures (frontend/src/api/mocks/fixtures.ts at 57b4df0).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from di1.modules.ledger.domain.entries import EntryType, LedgerEntry, entries_to_delete
from di1.shared.clock import SAO_PAULO
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind

CREATED = datetime(2026, 10, 14, 14, 11, 2, tzinfo=SAO_PAULO)


def trade(
    entry_date: date = date(2026, 10, 14),
    *,
    quantity: int = 10,
    pu: str = "89006.4625467350",
    deleted: bool = False,
    entry_id: UUID | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        id=entry_id or uuid4(),
        type=EntryType.TRADE,
        entry_date=entry_date,
        entry_time=time(14, 10),
        seq=2,
        created_at=CREATED,
        asset_id=uuid4(),
        signed_quantity=quantity,
        execution_pu=Decimal(pu),
        execution_rate=Decimal("0.10"),
        input_kind=InputKind.RATE,
        cash_amount=None,
        deleted_at=CREATED if deleted else None,
    )


def cash(
    entry_date: date = date(2026, 10, 14),
    *,
    amount: str = "1500000.00",
    deleted: bool = False,
    entry_id: UUID | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        id=entry_id or uuid4(),
        type=EntryType.CASH,
        entry_date=entry_date,
        entry_time=time(9, 0),
        seq=1,
        created_at=CREATED,
        asset_id=None,
        signed_quantity=None,
        execution_pu=None,
        execution_rate=None,
        input_kind=None,
        cash_amount=Decimal(amount),
        deleted_at=CREATED if deleted else None,
    )


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
    effect = trade(quantity=quantity, pu=pu).cash_effect

    assert effect == Decimal(expected)
    assert str(effect) == expected  # exact: no rounding, scale of the PU kept


def test_the_cash_effect_is_exact_for_the_largest_quantity() -> None:
    # 2147483647 × (100000 − 10⁻¹⁰) = 214748364700000 − 0.2147483647
    effect = trade(quantity=2**31 - 1, pu="99999.9999999999").cash_effect
    assert effect == Decimal("-214748364699999.7852516353")


def test_a_cash_entrys_effect_is_its_signed_amount() -> None:
    assert cash(amount="1500000.00").cash_effect == Decimal("1500000.00")
    assert cash(amount="-50000.00").cash_effect == Decimal("-50000.00")


def test_the_order_key_is_date_time_seq() -> None:
    entry = cash()
    assert entry.order_key == (date(2026, 10, 14), time(9, 0), 1)


# --- batch soft delete --------------------------------------------------------------------------


def test_an_unknown_id_deletes_nothing() -> None:
    known = trade()
    with pytest.raises(DomainError) as error:
        entries_to_delete([known.id, uuid4()], [known])

    assert error.value.code is ErrorCode.NOT_FOUND
    assert error.value.errors[0].message == "Lançamento não encontrado."


def test_an_empty_batch_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        entries_to_delete([], [])

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.errors[0].field == "ids"


def test_a_mixed_batch_deletes_every_requested_entry() -> None:
    deposit, sell = cash(date(2026, 10, 14)), trade(date(2026, 10, 16), quantity=-4)

    assert set(entries_to_delete([sell.id, deposit.id], [deposit, sell])) == {deposit.id, sell.id}


def test_deleting_an_already_deleted_entry_changes_nothing() -> None:
    gone = trade(deleted=True)

    assert entries_to_delete([gone.id], [gone]) == ()


def test_already_deleted_entries_do_not_join_the_batch() -> None:
    gone = cash(date(2026, 10, 1), deleted=True)
    live = trade(date(2026, 10, 16))

    assert entries_to_delete([gone.id, live.id], [gone, live]) == (live.id,)


def test_a_repeated_id_is_deleted_once() -> None:
    entry = trade()

    assert entries_to_delete([entry.id, entry.id], [entry]) == (entry.id,)
