"""Test data: the one DI1 catalogue the tests share, and builders for the values they hand to the
code under test.

The catalogue is the frontend's test fixtures (``frontend/src/test/msw/fixtures.ts``): the DI1
product and DI1F27…DI1F30, each with one id and one maturity, plus DI1V26, a contract that matured
before the tests' "today" (OQ-1). The challenge's own example (spec §13) prices a DI1F28 that
matures on 01/01/2028; `CHALLENGE_DI1F28` is that contract, kept apart because its expected values
come from the challenge text.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from di1.modules.asset.public import Instrument
from di1.modules.ledger.domain.entries import EntryDraft, EntryType, LedgerEntry
from di1.modules.portfolio.domain.positions import OpenPosition
from di1.modules.portfolio.domain.trade import Trade
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=SAO_PAULO)
"""The tests' "now" when the time of day matters (queue order, processing times)."""

CREATED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
"""When a hand-built instrument or entry was registered; no test asserts it."""

PRODUCT_ID = UUID("6f1c2a10-0000-4000-8000-000000000001")
DI1_NAME = "Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia"


def di1_contract(
    code: str,
    instrument_id: UUID | None = None,
    maturity: date | None = date(2028, 1, 3),
    *,
    product_id: UUID = PRODUCT_ID,
) -> Instrument:
    """A DI1 future as Asset describes it (``asset.public.Instrument``): face value 100000,
    multiplier 1, cash settlement."""
    return Instrument(
        id=instrument_id or uuid4(),
        code=code,
        product_id=product_id,
        product_code="DI1",
        instrument_type="FUTURE",
        asset_class="INTEREST_RATE_FUTURE",
        maturity_date=maturity,
        face_value=Decimal("100000"),
        multiplier=Decimal("1"),
        settlement_method="CASH",
        created_at=CREATED_AT,
    )


DI1F27 = di1_contract("DI1F27", UUID("6f1c2a10-0000-4000-8000-0000000000f7"), date(2027, 1, 4))
DI1F28 = di1_contract("DI1F28", UUID("6f1c2a10-0000-4000-8000-0000000000f8"), date(2028, 1, 3))
DI1F29 = di1_contract("DI1F29", UUID("6f1c2a10-0000-4000-8000-0000000000f9"), date(2029, 1, 2))
DI1F30 = di1_contract("DI1F30", UUID("6f1c2a10-0000-4000-8000-0000000000fa"), date(2030, 1, 2))
DI1V26 = di1_contract("DI1V26", UUID("6f1c2a10-0000-4000-8000-0000000000a1"), date(2026, 10, 1))
"""Not in the frontend fixtures: matured on 01/10/2026, before the tests' "today" (OQ-1)."""

CATALOGUE = (DI1F27, DI1F28, DI1F29, DI1F30, DI1V26)

CHALLENGE_DI1F28 = di1_contract(
    "DI1F28", UUID("00000000-0000-0000-0000-00000000f028"), date(2028, 1, 1)
)
"""The challenge's contract (spec §13): 365 calendar days from 01/01/2027 to its maturity."""


def draft_trade(
    entry_date: date = date(2026, 10, 14),
    entry_time: time = time(14, 10),
    *,
    quantity: int = 10,
    rate: str = "0.10",
    contract_id: UUID = DI1F28.id,
) -> EntryDraft:
    """A trade as the user types it, by rate (Ledger's write side)."""
    return EntryDraft(
        type=EntryType.TRADE,
        entry_date=entry_date,
        entry_time=entry_time,
        asset_id=contract_id,
        signed_quantity=quantity,
        input_kind=InputKind.RATE,
        execution_rate=Decimal(rate),
    )


def draft_cash(
    entry_date: date = date(2026, 10, 14),
    entry_time: time = time(9, 0),
    *,
    amount: str = "1500000.00",
    description: str | None = None,
) -> EntryDraft:
    """A cash movement as the user types it: positive deposits, negative withdrawals."""
    return EntryDraft(
        type=EntryType.CASH,
        entry_date=entry_date,
        entry_time=entry_time,
        cash_amount=Decimal(amount),
        description=description,
    )


def ledger_trade(
    asset_id: UUID,
    day: date,
    quantity: int,
    pu: str,
    rate: str = "0.1",
    *,
    seq: int = 1,
    at: time = time(10),
) -> LedgerEntry:
    """A stored trade as ``ledger.public`` returns it."""
    return LedgerEntry(
        id=uuid4(),
        type=EntryType.TRADE,
        entry_date=day,
        entry_time=at,
        seq=seq,
        created_at=CREATED_AT,
        asset_id=asset_id,
        signed_quantity=quantity,
        execution_pu=Decimal(pu),
        execution_rate=Decimal(rate),
        input_kind=InputKind.PU,
        cash_amount=None,
    )


def ledger_cash(day: date, amount: str, *, seq: int = 1) -> LedgerEntry:
    """A stored cash movement as ``ledger.public`` returns it."""
    return LedgerEntry(
        id=uuid4(),
        type=EntryType.CASH,
        entry_date=day,
        entry_time=time(9),
        seq=seq,
        created_at=CREATED_AT,
        asset_id=None,
        signed_quantity=None,
        execution_pu=None,
        execution_rate=None,
        input_kind=None,
        cash_amount=Decimal(amount),
    )


DAY = date(2027, 1, 4)
"""The portfolio accounting tests' date: a Monday, and DI1F27's maturity."""


def portfolio_trade(
    quantity: int,
    pu: str,
    rate: str = "0.1",
    *,
    asset_id: UUID = DI1F27.id,
    on: date = DAY,
    at: str = "10:00",
    seq: int = 1,
) -> Trade:
    """A Ledger trade as Portfolio reads it: buys positive, sells negative, execution PU/rate."""
    return Trade(
        asset_id=asset_id,
        trade_date=on,
        trade_time=time.fromisoformat(at),
        seq=seq,
        signed_quantity=quantity,
        execution_pu=Decimal(pu),
        execution_rate=Decimal(rate),
    )


def open_position(quantity: int, pu: str, rate: str, *, asset_id: UUID = DI1F27.id) -> OpenPosition:
    """An open position carried from D−1: signed quantity and weighted averages."""
    return OpenPosition(
        asset_id=asset_id,
        quantity=quantity,
        average_entry_pu=Decimal(pu),
        average_entry_rate=Decimal(rate),
    )
