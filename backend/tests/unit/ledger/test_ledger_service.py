"""`LedgerService`: a write saves the fact in one Unit of Work and commits once; it touches
nothing else (user decision 2026-10-19: staleness removed from the project).

Rules: spec §6, §6.1, §6.2; interfaces "Ledger"; OQ-24 and the user's decision of 2026-10-19
(batch delete of either type, for good, all or nothing); OQ-1, OQ-3
(PU ↔ rate through Pricing, the typed value kept as typed). Golden execution prices are the MSW
fixtures (frontend/src/api/mocks/fixtures.ts at 57b4df0), computed offline with DC/365.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.domain.entries import EntryDraft, EntryType
from di1.modules.ledger.domain.listing import ListOrder
from di1.modules.pricing.public import Price, Quote
from di1.shared.clock import FixedClock
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind
from tests.unit.ledger.fakes import (
    DI1F28,
    DI1F29,
    FakeAssets,
    FakeUnitOfWork,
    FormulaPricing,
    InMemoryLedgerRepository,
)

TODAY = date(2026, 10, 18)


class Harness:
    def __init__(self) -> None:
        self.assets = FakeAssets()
        self.pricing = FormulaPricing(self.assets)
        self.repository = InMemoryLedgerRepository()
        self.service = LedgerService(
            clock=FixedClock(TODAY),
            assets=self.assets,
            pricing=self.pricing,
            repository_for=lambda _uow: self.repository,
        )


@pytest.fixture
def harness() -> Harness:
    return Harness()


def buy_rate(**overrides: object) -> EntryDraft:
    fields: dict[str, object] = {
        "type": EntryType.TRADE,
        "entry_date": date(2026, 10, 14),
        "entry_time": time(14, 10),
        "asset_id": DI1F28.id,
        "signed_quantity": 10,
        "input_kind": InputKind.RATE,
        "execution_rate": Decimal("0.10"),
    }
    fields.update(overrides)
    return EntryDraft(**fields)  # type: ignore[arg-type]


def deposit(**overrides: object) -> EntryDraft:
    fields: dict[str, object] = {
        "type": EntryType.CASH,
        "entry_date": date(2026, 10, 14),
        "entry_time": time(9, 0),
        "cash_amount": Decimal("1500000.00"),
    }
    fields.update(overrides)
    return EntryDraft(**fields)  # type: ignore[arg-type]


# --- create -------------------------------------------------------------------------------------


async def test_a_rate_typed_trade_gets_its_pu_from_pricing(harness: Harness) -> None:
    uow = FakeUnitOfWork()

    view = await harness.service.create_entry(buy_rate(), uow=uow)

    entry = view.entry
    assert entry.execution_pu == Decimal("89006.4625467350")
    assert str(entry.execution_rate) == "0.10"  # as typed
    assert entry.input_kind is InputKind.RATE
    assert entry.cash_effect == Decimal("-890064.6254673500")
    assert (view.asset_code, view.instrument_type_code) == ("DI1F28", "FUTURE")
    assert harness.pricing.calls == [
        (DI1F28.id, date(2026, 10, 14), Quote(InputKind.RATE, Decimal("0.10")))
    ]


async def test_a_pu_typed_trade_gets_its_rate_from_pricing(harness: Harness) -> None:
    view = await harness.service.create_entry(
        buy_rate(
            asset_id=DI1F29.id,
            entry_date=date(2026, 10, 15),
            entry_time=time(10, 30),
            signed_quantity=5,
            input_kind=InputKind.PU,
            execution_rate=None,
            execution_pu=Decimal("82057.00"),
        ),
        uow=FakeUnitOfWork(),
    )

    assert str(view.entry.execution_pu) == "82057.00"
    assert view.entry.execution_rate == Decimal("0.093203413834")
    assert view.entry.cash_effect == Decimal("-410285.00")


async def test_a_sell_at_a_typed_rate_matches_the_golden_fixture(harness: Harness) -> None:
    view = await harness.service.create_entry(
        buy_rate(
            entry_date=date(2026, 10, 16),
            entry_time=time(15, 0),
            signed_quantity=-4,
            execution_rate=Decimal("0.0995"),
        ),
        uow=FakeUnitOfWork(),
    )

    assert view.entry.execution_pu == Decimal("89102.2226533433")
    assert view.entry.cash_effect == Decimal("356408.8906133732")


async def test_a_trade_is_saved_and_committed_once(harness: Harness) -> None:
    uow = FakeUnitOfWork()

    view = await harness.service.create_entry(buy_rate(), uow=uow)

    assert harness.repository.rows == [view.entry]
    assert uow.commits == 1


async def test_a_cash_movement_is_saved_without_pricing(harness: Harness) -> None:
    uow = FakeUnitOfWork()

    view = await harness.service.create_entry(deposit(), uow=uow)

    assert view.entry.cash_amount == Decimal("1500000.00")
    assert view.asset_code is None
    assert harness.pricing.calls == []
    assert uow.commits == 1


async def test_trades_and_cash_share_one_seq(harness: Harness) -> None:
    first = await harness.service.create_entry(deposit(), uow=FakeUnitOfWork())
    second = await harness.service.create_entry(buy_rate(), uow=FakeUnitOfWork())

    assert second.entry.seq == first.entry.seq + 1


async def test_on_the_maturity_date_the_typed_pu_is_kept_and_the_rate_is_zero(
    harness: Harness,
) -> None:
    harness.assets.instruments[DI1F28.id] = replace(DI1F28, maturity_date=date(2026, 10, 16))

    view = await harness.service.create_entry(
        buy_rate(
            entry_date=date(2026, 10, 16),
            signed_quantity=-10,
            input_kind=InputKind.PU,
            execution_rate=None,
            execution_pu=Decimal("100000.00"),
        ),
        uow=FakeUnitOfWork(),
    )

    assert str(view.entry.execution_pu) == "100000.00"
    assert view.entry.execution_rate == 0


async def test_an_unknown_contract_is_a_validation_error_and_writes_nothing(
    harness: Harness,
) -> None:
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as error:
        await harness.service.create_entry(buy_rate(asset_id=uuid4()), uow=uow)

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.errors[0].field == "asset_id"
    assert harness.repository.rows == []
    assert uow.commits == 0


async def test_a_future_entry_writes_nothing(harness: Harness) -> None:
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as error:
        await harness.service.create_entry(deposit(entry_date=date(2026, 10, 19)), uow=uow)

    assert error.value.code is ErrorCode.FUTURE_DATE
    assert harness.repository.rows == []
    assert uow.commits == 0


async def test_a_pricing_refusal_writes_nothing(harness: Harness) -> None:
    uow = FakeUnitOfWork()
    # A rate so high that the PU rounds to zero at 10 places: Pricing refuses it on its `rate`,
    # which Ledger reports on the request's `execution_rate`.
    with pytest.raises(DomainError) as error:
        await harness.service.create_entry(buy_rate(execution_rate=Decimal("1E+40")), uow=uow)

    assert [(e.code, e.field) for e in error.value.errors] == [
        (ErrorCode.VALIDATION_ERROR, "execution_rate")
    ]

    assert harness.repository.rows == []
    assert uow.commits == 0


class RefusingPricing:
    """A `PricingService` that refuses every quote with one error, as lane B's service does."""

    def __init__(self, error: ErrorDetail) -> None:
        self.error = error

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        raise DomainError(self.error)


@pytest.mark.parametrize(
    ("code", "pricing_field", "ledger_field"),
    [
        (ErrorCode.VALIDATION_ERROR, "rate", "execution_rate"),
        (ErrorCode.VALIDATION_ERROR, "pu", "execution_pu"),
        (ErrorCode.CONTRACT_MATURED, "reference_date", "date"),
        (ErrorCode.VALIDATION_ERROR, "asset_id", "asset_id"),
    ],
)
async def test_a_pricing_error_names_the_request_field(
    harness: Harness, code: ErrorCode, pricing_field: str, ledger_field: str
) -> None:
    # Pricing names its own parameters; the client keys on the request's fields (lane B, PR #52).
    service = LedgerService(
        clock=FixedClock(TODAY),
        assets=harness.assets,
        pricing=RefusingPricing(ErrorDetail(code, "Mensagem do Pricing.", pricing_field)),
        repository_for=lambda _uow: harness.repository,
    )

    with pytest.raises(DomainError) as error:
        await service.create_entry(buy_rate(), uow=FakeUnitOfWork())

    assert [(e.code, e.message, e.field) for e in error.value.errors] == [
        (code, "Mensagem do Pricing.", ledger_field)
    ]
    assert harness.repository.rows == []


async def test_an_instrument_pricing_cannot_find_is_a_validation_error_on_asset_id(
    harness: Harness,
) -> None:
    # A body field never answers 404 (contract-mismatch rule E2).
    service = LedgerService(
        clock=FixedClock(TODAY),
        assets=harness.assets,
        pricing=RefusingPricing(ErrorDetail(ErrorCode.NOT_FOUND, "Instrumento não encontrado.")),
        repository_for=lambda _uow: harness.repository,
    )

    with pytest.raises(DomainError) as error:
        await service.create_entry(buy_rate(), uow=FakeUnitOfWork())

    assert [(e.code, e.field) for e in error.value.errors] == [
        (ErrorCode.VALIDATION_ERROR, "asset_id")
    ]


# --- delete -------------------------------------------------------------------------------------


async def test_a_mixed_batch_deletes_the_entries_in_one_commit(harness: Harness) -> None:
    cash = await harness.service.create_entry(deposit(), uow=FakeUnitOfWork())
    sell = await harness.service.create_entry(
        buy_rate(entry_date=date(2026, 10, 16), signed_quantity=-4), uow=FakeUnitOfWork()
    )
    kept = await harness.service.create_entry(
        buy_rate(entry_date=date(2026, 10, 17)), uow=FakeUnitOfWork()
    )
    uow = FakeUnitOfWork()

    await harness.service.delete_entries([sell.entry.id, cash.entry.id], uow=uow)

    assert harness.repository.rows == [kept.entry]
    assert uow.commits == 1


async def test_an_unknown_id_deletes_nothing(harness: Harness) -> None:
    kept = await harness.service.create_entry(deposit(), uow=FakeUnitOfWork())
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as error:
        await harness.service.delete_entries([kept.entry.id, uuid4()], uow=uow)

    assert error.value.code is ErrorCode.NOT_FOUND
    assert harness.repository.rows == [kept.entry]
    assert uow.commits == 0


async def test_a_deleted_entry_no_longer_exists(harness: Harness) -> None:
    entry = await harness.service.create_entry(deposit(), uow=FakeUnitOfWork())
    await harness.service.delete_entries([entry.entry.id], uow=FakeUnitOfWork())

    with pytest.raises(DomainError) as error:
        await harness.service.delete_entries([entry.entry.id], uow=FakeUnitOfWork())

    assert error.value.code is ErrorCode.NOT_FOUND


# --- list ---------------------------------------------------------------------------------------


async def test_the_list_pages_newest_first_across_both_types(harness: Harness) -> None:
    for draft in (
        deposit(),
        buy_rate(),
        buy_rate(asset_id=DI1F29.id, entry_date=date(2026, 10, 15), entry_time=time(10, 30)),
    ):
        await harness.service.create_entry(draft, uow=FakeUnitOfWork())

    async def page(cursor: str | None) -> tuple[list[int], str | None]:
        result = await harness.service.list_entries(
            start_date=date(2026, 10, 1),
            end_date=TODAY,
            search=None,
            order=ListOrder.DESC,
            limit=2,
            cursor=cursor,
            uow=FakeUnitOfWork(),
        )
        return [item.entry.seq for item in result.items], result.next_cursor

    first, cursor = await page(None)
    second, last = await page(cursor)

    assert first == [3, 2]
    assert second == [1]
    assert last is None


async def test_the_search_matches_contract_codes_and_cash_labels(harness: Harness) -> None:
    await harness.service.create_entry(deposit(), uow=FakeUnitOfWork())
    await harness.service.create_entry(buy_rate(), uow=FakeUnitOfWork())
    await harness.service.create_entry(
        deposit(cash_amount=Decimal("-50000.00"), entry_date=date(2026, 10, 16)),
        uow=FakeUnitOfWork(),
    )

    async def search(text: str) -> list[str | None]:
        result = await harness.service.list_entries(
            start_date=date(2026, 10, 1),
            end_date=TODAY,
            search=text,
            order=ListOrder.ASC,
            limit=None,
            cursor=None,
            uow=FakeUnitOfWork(),
        )
        return [item.asset_code or str(item.entry.cash_amount) for item in result.items]

    assert await search("f28") == ["DI1F28"]
    assert await search("aporte") == ["1500000.00"]
    assert await search("RETIRADA") == ["-50000.00"]
    assert await search("xyz") == []


async def test_the_list_writes_nothing(harness: Harness) -> None:
    uow = FakeUnitOfWork()
    await harness.service.list_entries(
        start_date=date(2026, 10, 1),
        end_date=TODAY,
        search=None,
        order=ListOrder.DESC,
        limit=None,
        cursor=None,
        uow=uow,
    )
    assert uow.commits == 0
