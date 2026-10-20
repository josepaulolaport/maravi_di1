"""`PriceService` and `DefaultPriceReader` orchestration with in-memory collaborators and Pricing's
real service (spec §5, §13 item 17; interfaces.md "Prices"; OQ-25, OQ-26 item 7, OQ-31): what is
priced, what is passed to the repository, one commit per write and nothing written on a refusal.

The validation rules are in ``test_reference_price_rules.py``; replacing a key, MANUAL over B3,
exact dates and the latest date are SQL, in ``tests/integration/prices/
test_reference_prices_persistence.py``.

DI1F28 matures on 03/01/2028: on 16/10/2026 (444 calendar days) the rate 0.0980 is the PU
89250.3147019396 and that PU is the rate 0.098000000000 (the frontend demo fixtures, recomputed
with ``decimal`` at 34 digits, half-up; spec §4.1).
"""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from di1.modules.prices.application.services.price_service import DefaultPriceReader, PriceService
from di1.modules.prices.public import PriceReader, PriceSource
from di1.modules.pricing.dependencies import build_pricing_service
from di1.modules.pricing.public import PricingService
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind
from tests.fakes.clock import FixedClock
from tests.unit.prices.fakes import (
    FakeAssets,
    FakeUnitOfWork,
    PricingSpy,
    RecordingRepository,
    instrument,
    record,
)

TODAY = date(2026, 10, 19)
DAY = date(2026, 10, 16)
UNKNOWN_ASSET = ErrorDetail(ErrorCode.VALIDATION_ERROR, "Selecione um contrato.", "asset_id")

ASSETS = FakeAssets()
DI1F28 = ASSETS.add(instrument(maturity_date=date(2028, 1, 3)))


def _service(
    repository: RecordingRepository, uow: FakeUnitOfWork, pricing: PricingService | None = None
) -> PriceService:
    """The service on ``uow``, as the composition builds one per request."""
    return PriceService(
        repository,
        uow,
        assets=ASSETS,
        pricing=pricing or build_pricing_service(ASSETS),
        clock=FixedClock(TODAY),
    )


def _request(
    *,
    asset_id: UUID = DI1F28.id,
    reference_date: date = DAY,
    pu: str | None = "89250.3147019396",
    rate: str | None = None,
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "reference_date": reference_date,
        "input_kind": InputKind.PU if pu is not None else InputKind.RATE,
        "pu": Decimal(pu) if pu is not None else None,
        "rate": Decimal(rate) if rate is not None else None,
    }


# --- set ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "input_kind", "pu", "rate"),
    [
        pytest.param(
            {"pu": "89250.3147019396"},
            InputKind.PU,
            "89250.3147019396",
            "0.098000000000",
            id="typed-pu",
        ),
        pytest.param(
            {"pu": None, "rate": "0.0980"},
            InputKind.RATE,
            "89250.3147019396",
            "0.0980",
            id="typed-rate",
        ),
    ],
)
async def test_the_typed_value_is_saved_with_the_calculated_one_and_committed_once(
    typed: dict[str, str | None], input_kind: InputKind, pu: str, rate: str
) -> None:
    repository, uow = RecordingRepository(), FakeUnitOfWork()

    saved = await _service(repository, uow).set_reference_price(**_request(**typed))  # type: ignore[arg-type]

    assert repository.calls == [
        (
            "replace",
            {
                "asset_id": DI1F28.id,
                "reference_date": DAY,
                "source": PriceSource.MANUAL,
                "input_kind": input_kind,
                "pu": Decimal(pu),
                "rate": Decimal(rate),
            },
        )
    ]
    assert (str(saved.pu), str(saved.rate)) == (pu, rate)  # the typed value keeps its scale
    assert uow.commits == 1


async def test_the_given_source_is_saved() -> None:
    repository = RecordingRepository()

    saved = await _service(repository, FakeUnitOfWork()).set_reference_price(
        **_request(), source=PriceSource.B3
    )

    assert saved.source is PriceSource.B3
    assert repository.calls[0][1]["source"] is PriceSource.B3


@pytest.mark.parametrize(
    ("request_args", "errors"),
    [
        pytest.param({"asset_id": uuid4(), "pu": "89000"}, (UNKNOWN_ASSET,), id="unknown-asset"),
        pytest.param(
            # An unknown asset is reported together with every other problem of the request.
            {"asset_id": uuid4(), "reference_date": date(2026, 10, 20), "pu": "0"},
            (
                UNKNOWN_ASSET,
                ErrorDetail(
                    ErrorCode.FUTURE_DATE,
                    "A data não pode ser posterior a hoje.",
                    "reference_date",
                ),
                ErrorDetail(ErrorCode.VALIDATION_ERROR, "O PU deve ser maior que zero.", "pu"),
            ),
            id="unknown-asset-and-every-other-problem",
        ),
        pytest.param(
            {"reference_date": date(2026, 10, 20)},
            (
                ErrorDetail(
                    ErrorCode.FUTURE_DATE,
                    "A data não pode ser posterior a hoje.",
                    "reference_date",
                ),
            ),
            id="a-rule-of-the-price",
        ),
    ],
)
async def test_a_refused_write_writes_nothing(
    request_args: dict[str, Any], errors: tuple[ErrorDetail, ...]
) -> None:
    repository, uow, pricing = RecordingRepository(), FakeUnitOfWork(), PricingSpy(ASSETS)

    with pytest.raises(DomainError) as excinfo:
        await _service(repository, uow, pricing).set_reference_price(**_request(**request_args))

    assert excinfo.value.errors == errors
    # Refused before anything is priced or written.
    assert (pricing.calls, repository.calls, uow.commits) == ([], [], 0)


# --- remove -------------------------------------------------------------------------------------


async def test_removal_deletes_the_price_and_commits_once() -> None:
    price = record(DI1F28.id, DAY, PriceSource.MANUAL)
    repository, uow = RecordingRepository(rows=[price]), FakeUnitOfWork()

    await _service(repository, uow).remove_reference_price(price.id)

    assert repository.calls == [("delete", {"price_id": price.id})]
    assert uow.commits == 1


async def test_an_unknown_price_is_not_found_and_nothing_is_committed() -> None:
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as excinfo:
        await _service(RecordingRepository(), uow).remove_reference_price(uuid4())

    assert excinfo.value.errors == (
        ErrorDetail(ErrorCode.NOT_FOUND, "Preço de referência não encontrado."),
    )
    assert uow.commits == 0


# --- list ---------------------------------------------------------------------------------------


async def test_the_days_of_the_range_are_read_and_grouped_without_a_commit() -> None:
    b3, manual = record(DI1F28.id, DAY, PriceSource.B3), record(DI1F28.id, DAY, PriceSource.MANUAL)
    repository, uow = RecordingRepository(rows=[b3, manual]), FakeUnitOfWork()

    days = await _service(repository, uow).list_reference_days(DI1F28.id, date(2026, 10, 1), DAY)

    assert repository.calls == [
        (
            "find_in_range",
            {"asset_id": DI1F28.id, "start_date": date(2026, 10, 1), "end_date": DAY},
        )
    ]
    assert [(d.reference_date, d.preferred, d.sources) for d in days] == [
        (DAY, manual, (manual, b3))
    ]
    assert uow.commits == 0


async def test_an_inverted_range_and_an_unknown_asset_are_reported_together() -> None:
    repository = RecordingRepository()

    with pytest.raises(DomainError) as excinfo:
        await _service(repository, FakeUnitOfWork()).list_reference_days(
            uuid4(), date(2026, 10, 18), date(2026, 10, 17)
        )

    assert excinfo.value.errors == (
        ErrorDetail(
            ErrorCode.INVALID_RANGE,
            "A data inicial deve ser anterior ou igual à data final.",
            "start_date",
        ),
        UNKNOWN_ASSET,
    )
    assert repository.calls == []


# --- PriceReader --------------------------------------------------------------------------------


def test_the_reader_satisfies_the_public_contract() -> None:
    reader: PriceReader = DefaultPriceReader(RecordingRepository())

    for method in ("get", "latest"):
        assert inspect.signature(getattr(type(reader), method)) == inspect.signature(
            getattr(PriceReader, method)
        )


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda reader: reader.get([], [DAY]), id="get-no-asset"),
        pytest.param(lambda reader: reader.get([uuid4()], []), id="get-no-date"),
        pytest.param(lambda reader: reader.latest([]), id="latest-no-asset"),
    ],
)
async def test_nothing_asked_reads_nothing(read: Any) -> None:
    repository = RecordingRepository(rows=[record(DI1F28.id, DAY, PriceSource.MANUAL)])

    assert await read(DefaultPriceReader(repository)) == {}
    assert repository.calls == []
