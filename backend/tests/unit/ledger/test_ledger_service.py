"""`LedgerService`: a write saves the fact in one Unit of Work and commits once; it touches
nothing else (user decision 2026-10-19: staleness removed from the project).

Only the orchestration is tested here: what reaches Pricing and the repository, what is saved,
one commit, nothing written on a refusal. Each validation rule is tested once against the domain
(test_entry_validation, test_entries, test_listing); ordering, search and paging are SQL
(tests/integration/ledger/test_ledger_persistence.py). Pricing is the real service.

Rules: spec §6, §6.1, §6.2; interfaces "Ledger"; OQ-24 and the user's decision of 2026-10-19
(batch delete of either type, for good, all or nothing); OQ-1, OQ-3
(PU ↔ rate through Pricing, the typed value kept as typed). Golden execution prices are the MSW
fixtures (frontend/src/api/mocks/fixtures.ts at 57b4df0), computed offline with DC/365.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.domain.entries import EntryDraft, EntryType
from di1.modules.ledger.domain.listing import EntryCursor, ListOrder
from di1.modules.pricing.public import Price, Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind
from di1.shared.paging import PageParams
from tests.fakes.clock import FixedClock
from tests.unit.ledger.fakes import (
    DI1F28,
    DI1F29,
    FakeAssets,
    FakeUnitOfWork,
    InMemoryLedgerRepository,
    PricingSpy,
)

TODAY = date(2026, 10, 18)


class Harness:
    def __init__(self) -> None:
        self.assets = FakeAssets()
        self.pricing = PricingSpy(self.assets)
        self.repository = InMemoryLedgerRepository()

    def service(self, uow: FakeUnitOfWork) -> LedgerService:
        """The service on ``uow``, as the composition builds one per request."""
        return LedgerService(
            self.repository,
            uow,
            clock=FixedClock(TODAY),
            assets=self.assets,
            pricing=self.pricing,
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


@pytest.mark.parametrize(
    ("draft", "quote", "pu", "rate", "cash_effect"),
    [
        (
            buy_rate(),
            Quote(InputKind.RATE, Decimal("0.10")),
            "89006.4625467350",
            "0.10",
            "-890064.6254673500",
        ),
        (
            buy_rate(
                asset_id=DI1F29.id,
                entry_date=date(2026, 10, 15),
                entry_time=time(10, 30),
                signed_quantity=5,
                input_kind=InputKind.PU,
                execution_rate=None,
                execution_pu=Decimal("82057.00"),
            ),
            Quote(InputKind.PU, Decimal("82057.00")),
            "82057.00",
            "0.093203413834",
            "-410285.00",
        ),
    ],
    ids=["rate-typed", "pu-typed"],
)
async def test_a_trade_keeps_its_typed_value_and_takes_the_other_from_pricing(
    harness: Harness, draft: EntryDraft, quote: Quote, pu: str, rate: str, cash_effect: str
) -> None:
    uow = FakeUnitOfWork()

    view = await harness.service(uow).create_entry(draft)

    entry = view.entry
    assert harness.pricing.calls == [(draft.asset_id, draft.entry_date, quote)]
    assert (str(entry.execution_pu), str(entry.execution_rate)) == (pu, rate)  # typed as typed
    assert entry.input_kind is quote.kind
    assert entry.cash_effect == Decimal(cash_effect)
    assert view.instrument_type_code == "FUTURE"
    assert view.asset_code == ("DI1F28" if draft.asset_id == DI1F28.id else "DI1F29")
    assert harness.repository.rows == [entry]
    assert uow.commits == 1


async def test_a_cash_movement_is_saved_without_pricing(harness: Harness) -> None:
    uow = FakeUnitOfWork()

    view = await harness.service(uow).create_entry(deposit())

    assert view.entry.cash_amount == Decimal("1500000.00")
    assert view.asset_code is None
    assert harness.repository.rows == [view.entry]
    assert harness.pricing.calls == []
    assert uow.commits == 1


@pytest.mark.parametrize(
    ("draft", "errors", "priced"),
    [
        (deposit(entry_date=date(2026, 10, 19)), [(ErrorCode.FUTURE_DATE, "date")], False),
        (buy_rate(asset_id=uuid4()), [(ErrorCode.VALIDATION_ERROR, "asset_id")], False),
        (buy_rate(description="Compra"), [(ErrorCode.VALIDATION_ERROR, "description")], False),
        # A rate so high that the PU rounds to zero at 10 places: Pricing refuses it on its
        # `rate`, which Ledger reports on the request's `execution_rate`.
        (
            buy_rate(execution_rate=Decimal("1E+40")),
            [(ErrorCode.VALIDATION_ERROR, "execution_rate")],
            True,
        ),
    ],
    ids=["future-date", "unknown-contract", "trade-description", "pricing-refusal"],
)
async def test_a_refused_entry_writes_nothing(
    harness: Harness,
    draft: EntryDraft,
    errors: list[tuple[ErrorCode, str]],
    priced: bool,
) -> None:
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as error:
        await harness.service(uow).create_entry(draft)

    assert [(e.code, e.field) for e in error.value.errors] == errors
    assert bool(harness.pricing.calls) is priced  # Ledger's own refusals never reach Pricing
    assert harness.repository.rows == []
    assert uow.commits == 0


class RefusingPricing:
    """A `PricingService` that refuses every quote with one error, as lane B's service does."""

    def __init__(self, error: ErrorDetail) -> None:
        self.error = error

    async def calculate(self, instrument_id: UUID, reference_date: date, quote: Quote) -> Price:
        raise DomainError(self.error)


@pytest.mark.parametrize(
    ("pricing_error", "expected"),
    [
        (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Mensagem do Pricing.", "rate"),
            (ErrorCode.VALIDATION_ERROR, "Mensagem do Pricing.", "execution_rate"),
        ),
        (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Mensagem do Pricing.", "pu"),
            (ErrorCode.VALIDATION_ERROR, "Mensagem do Pricing.", "execution_pu"),
        ),
        (
            ErrorDetail(ErrorCode.CONTRACT_MATURED, "Mensagem do Pricing.", "reference_date"),
            (ErrorCode.CONTRACT_MATURED, "Mensagem do Pricing.", "date"),
        ),
        (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Mensagem do Pricing.", "asset_id"),
            (ErrorCode.VALIDATION_ERROR, "Mensagem do Pricing.", "asset_id"),
        ),
        # A body field never answers 404 (contract-mismatch rule E2).
        (
            ErrorDetail(ErrorCode.NOT_FOUND, "Instrumento não encontrado."),
            (ErrorCode.VALIDATION_ERROR, None, "asset_id"),  # Ledger's own message
        ),
    ],
    ids=["rate", "pu", "reference-date", "asset-id", "not-found"],
)
async def test_a_pricing_error_names_the_request_field(
    harness: Harness, pricing_error: ErrorDetail, expected: tuple[ErrorCode, str | None, str]
) -> None:
    # Pricing names its own parameters; the client keys on the request's fields (lane B, PR #52).
    uow = FakeUnitOfWork()
    service = LedgerService(
        harness.repository,
        uow,
        clock=FixedClock(TODAY),
        assets=harness.assets,
        pricing=RefusingPricing(pricing_error),
    )

    with pytest.raises(DomainError) as error:
        await service.create_entry(buy_rate())

    code, message, field = expected
    [detail] = error.value.errors
    assert (detail.code, detail.field) == (code, field)
    if message is not None:  # Pricing's message is passed on as it is
        assert detail.message == message
    assert harness.repository.rows == []
    assert uow.commits == 0


# --- delete -------------------------------------------------------------------------------------


async def test_a_mixed_batch_deletes_the_entries_in_one_commit(harness: Harness) -> None:
    cash = await harness.service(FakeUnitOfWork()).create_entry(deposit())
    sell = await harness.service(FakeUnitOfWork()).create_entry(
        buy_rate(entry_date=date(2026, 10, 16), signed_quantity=-4),
    )
    kept = await harness.service(FakeUnitOfWork()).create_entry(
        buy_rate(entry_date=date(2026, 10, 17)),
    )
    uow = FakeUnitOfWork()

    await harness.service(uow).delete_entries([sell.entry.id, cash.entry.id])

    assert harness.repository.rows == [kept.entry]
    assert uow.commits == 1


# --- list ---------------------------------------------------------------------------------------


async def test_a_full_page_carries_the_cursor_of_its_last_item(harness: Harness) -> None:
    for draft in (deposit(), buy_rate(), deposit(entry_date=date(2026, 10, 16))):
        await harness.service(FakeUnitOfWork()).create_entry(draft)
    first_two = harness.repository.rows[:2]
    uow = FakeUnitOfWork()

    page = await harness.service(uow).list_entries(
        start_date=date(2026, 10, 1),
        end_date=TODAY,
        search=None,
        order=ListOrder.DESC,
        page=PageParams(limit=2),
    )
    last = first_two[-1]

    # The repository's extra row only says that there is a next page.
    assert [item.entry for item in page.items] == first_two
    assert [item.asset_code for item in page.items] == [None, "DI1F28"]
    assert page.next_cursor == EntryCursor(last.entry_date, last.entry_time, last.seq).encode()
    assert uow.commits == 0  # a read writes nothing

    following = await harness.service(FakeUnitOfWork()).list_entries(
        start_date=date(2026, 10, 1),
        end_date=TODAY,
        search=None,
        order=ListOrder.DESC,
        page=PageParams(limit=3, cursor=page.next_cursor),
    )

    request, _ = harness.repository.page_calls[-1]
    assert (request.limit, request.order, request.after) == (
        3,
        ListOrder.DESC,
        EntryCursor(last.entry_date, last.entry_time, last.seq),
    )
    assert following.next_cursor is None  # no row beyond the limit


async def test_a_search_passes_the_contracts_whose_code_matches(harness: Harness) -> None:
    for draft in (
        deposit(),
        buy_rate(),
        buy_rate(asset_id=DI1F29.id, entry_date=date(2026, 10, 15), entry_time=time(10, 30)),
    ):
        await harness.service(FakeUnitOfWork()).create_entry(draft)

    for search, matching in (("f28", {DI1F28.id}), ("DI1F", {DI1F28.id, DI1F29.id})):
        await harness.service(FakeUnitOfWork()).list_entries(
            start_date=date(2026, 10, 1),
            end_date=TODAY,
            search=search,
            order=ListOrder.ASC,
            page=PageParams(),
        )
        request, passed = harness.repository.page_calls[-1]
        assert request.search is not None
        assert passed == matching

    await harness.service(FakeUnitOfWork()).list_entries(
        start_date=date(2026, 10, 1),
        end_date=TODAY,
        search="   ",
        order=ListOrder.ASC,
        page=PageParams(),
    )
    request, passed = harness.repository.page_calls[-1]
    assert (request.search, passed) == (None, set())  # a blank search filters nothing
