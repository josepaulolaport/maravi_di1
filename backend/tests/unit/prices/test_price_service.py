"""`PriceService` and `PriceReader` with in-memory collaborators (spec §5, §13 item 17;
interfaces.md "Prices"; OQ-25, OQ-26 item 7, OQ-31)."""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from typing import TypedDict
from uuid import UUID, uuid4

import pytest

from di1.modules.prices.application.services.price_service import DefaultPriceReader, PriceService
from di1.modules.prices.public import PriceReader, PriceSource
from di1.modules.pricing.public import Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind
from tests.support.builders import di1_contract
from tests.support.fakes import (
    CALCULATED_PU,
    CALCULATED_RATE,
    CalculationCall,
    FakeAssetReader,
    FakeClock,
    FakePricing,
    FakeUnitOfWork,
)
from tests.unit.prices.fakes import InMemoryRepository

TODAY = date(2026, 10, 19)
DAY = date(2026, 10, 16)


class _SetArgs(TypedDict):
    asset_id: UUID
    reference_date: date
    input_kind: InputKind
    pu: Decimal | None
    rate: Decimal | None
    source: PriceSource


class World:
    def __init__(self) -> None:
        self.assets = FakeAssetReader()
        self.asset = self.assets.add(di1_contract("DI1F28"))
        self.pricing = FakePricing()
        self.repository = InMemoryRepository()
        self.reader = DefaultPriceReader(self.repository)

    def service(self, uow: FakeUnitOfWork) -> PriceService:
        """The service on ``uow``, as the composition builds one per request."""
        return PriceService(
            self.repository,
            uow,
            assets=self.assets,
            pricing=self.pricing,
            clock=FakeClock(TODAY),
        )

    def request(
        self,
        *,
        asset_id: UUID | None = None,
        reference_date: date = DAY,
        source: PriceSource = PriceSource.MANUAL,
        pu: str | None = "89250.3147019396",
        rate: str | None = None,
    ) -> _SetArgs:
        return {
            "asset_id": self.asset.id if asset_id is None else asset_id,
            "reference_date": reference_date,
            "input_kind": InputKind.PU if pu is not None else InputKind.RATE,
            "pu": Decimal(pu) if pu is not None else None,
            "rate": Decimal(rate) if rate is not None else None,
            "source": source,
        }


@pytest.fixture
def world() -> World:
    return World()


class TestSet:
    async def test_a_typed_pu_is_saved_with_the_calculated_rate(self, world: World) -> None:
        uow = FakeUnitOfWork()

        record = await world.service(uow).set_reference_price(**world.request())

        assert (record.source, record.input_kind, record.pu, record.rate) == (
            PriceSource.MANUAL,
            InputKind.PU,
            Decimal("89250.3147019396"),
            CALCULATED_RATE,
        )
        assert world.pricing.calls == [
            CalculationCall(world.asset.id, DAY, Quote(InputKind.PU, Decimal("89250.3147019396")))
        ]
        assert list(world.repository.rows.values()) == [record]

    async def test_a_typed_rate_is_saved_with_the_calculated_pu(self, world: World) -> None:
        record = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(pu=None, rate="0.0980"),
        )

        assert (record.input_kind, record.pu, record.rate) == (
            InputKind.RATE,
            CALCULATED_PU,
            Decimal("0.0980"),
        )

    async def test_the_write_commits_once(self, world: World) -> None:
        uow = FakeUnitOfWork()

        await world.service(uow).set_reference_price(**world.request())

        assert uow.commits == 1

    async def test_a_second_price_of_the_same_source_replaces_the_first_with_a_new_id(
        self, world: World
    ) -> None:
        first = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(pu="89200.9008841512"),
        )

        second = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(pu="89250.3147019396"),
        )

        assert second.id != first.id
        assert list(world.repository.rows.values()) == [second]

    async def test_the_other_source_is_kept(self, world: World) -> None:
        b3 = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(source=PriceSource.B3, pu="89240.4279488087"),
        )
        manual = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())

        assert set(world.repository.rows.values()) == {b3, manual}

    async def test_an_unknown_asset_is_a_validation_error_on_its_field(self, world: World) -> None:
        request = world.request(asset_id=uuid4(), pu="89000")
        uow = FakeUnitOfWork()

        with pytest.raises(DomainError) as excinfo:
            await world.service(uow).set_reference_price(**request)

        assert excinfo.value.errors == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Selecione um contrato.", "asset_id"),
        )
        self._assert_nothing_written(world, uow)

    async def test_an_unknown_asset_is_reported_with_every_other_problem(
        self, world: World
    ) -> None:
        request = world.request(asset_id=uuid4(), reference_date=date(2026, 10, 20), pu="0")
        uow = FakeUnitOfWork()

        with pytest.raises(DomainError) as excinfo:
            await world.service(uow).set_reference_price(**request)

        assert excinfo.value.errors == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Selecione um contrato.", "asset_id"),
            ErrorDetail(
                ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "reference_date"
            ),
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "O PU deve ser maior que zero.", "pu"),
        )
        assert world.pricing.calls == []
        self._assert_nothing_written(world, uow)

    async def test_a_future_date_is_refused_before_any_write(self, world: World) -> None:
        uow = FakeUnitOfWork()

        with pytest.raises(DomainError) as excinfo:
            await world.service(uow).set_reference_price(
                **world.request(reference_date=date(2026, 10, 20)),
            )

        assert excinfo.value.code is ErrorCode.FUTURE_DATE
        assert world.pricing.calls == []
        self._assert_nothing_written(world, uow)

    async def test_a_date_after_maturity_is_refused(self, world: World) -> None:
        matured = world.assets.add(di1_contract("DI1F28", maturity=date(2026, 10, 15)))
        uow = FakeUnitOfWork()
        request = world.request(asset_id=matured.id, pu="100000")

        with pytest.raises(DomainError) as excinfo:
            await world.service(uow).set_reference_price(**request)

        assert excinfo.value.code is ErrorCode.CONTRACT_MATURED
        self._assert_nothing_written(world, uow)

    async def test_too_many_decimals_are_refused(self, world: World) -> None:
        uow = FakeUnitOfWork()

        with pytest.raises(DomainError) as excinfo:
            await world.service(uow).set_reference_price(
                **world.request(pu="89250.31470193961"),
            )

        assert excinfo.value.errors == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Use no máximo 10 casas decimais.", "pu"),
        )
        self._assert_nothing_written(world, uow)

    @staticmethod
    def _assert_nothing_written(world: World, uow: FakeUnitOfWork) -> None:
        assert world.repository.rows == {}
        assert uow.commits == 0


class TestRemove:
    async def test_removal_deletes_and_commits_once(self, world: World) -> None:
        price = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())
        uow = FakeUnitOfWork()

        await world.service(uow).remove_reference_price(price.id)

        assert world.repository.rows == {}
        assert uow.commits == 1

    async def test_removing_manual_lets_b3_prevail(self, world: World) -> None:
        b3 = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(source=PriceSource.B3, pu="89240.4279488087"),
        )
        manual = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())
        assert (await world.reader.get([world.asset.id], [DAY])).get(
            (world.asset.id, DAY)
        ) == manual

        await world.service(FakeUnitOfWork()).remove_reference_price(manual.id)

        assert (await world.reader.get([world.asset.id], [DAY])).get((world.asset.id, DAY)) == b3

    async def test_an_unknown_price_is_not_found_and_nothing_is_committed(
        self, world: World
    ) -> None:
        uow = FakeUnitOfWork()

        with pytest.raises(DomainError) as excinfo:
            await world.service(uow).remove_reference_price(uuid4())

        assert excinfo.value.code is ErrorCode.NOT_FOUND
        assert uow.commits == 0


class TestListDays:
    async def test_days_with_a_price_newest_first_with_the_preferred_source_first(
        self, world: World
    ) -> None:
        older = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(reference_date=date(2026, 10, 14), source=PriceSource.B3),
        )
        b3 = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(source=PriceSource.B3, pu="89240.4279488087"),
        )
        manual = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())

        days = await world.service(FakeUnitOfWork()).list_reference_days(
            world.asset.id,
            date(2026, 10, 1),
            DAY,
        )

        assert [(d.reference_date, d.preferred, d.sources) for d in days] == [
            (DAY, manual, (manual, b3)),
            (date(2026, 10, 14), older, (older,)),
        ]

    async def test_dates_outside_the_range_and_without_a_price_are_absent(
        self, world: World
    ) -> None:
        await world.service(FakeUnitOfWork()).set_reference_price(**world.request())

        days = await world.service(FakeUnitOfWork()).list_reference_days(
            world.asset.id,
            date(2026, 10, 17),
            date(2026, 10, 18),
        )

        assert days == []

    async def test_an_inverted_range_and_an_unknown_asset_are_reported(self, world: World) -> None:
        with pytest.raises(DomainError) as excinfo:
            await world.service(FakeUnitOfWork()).list_reference_days(
                uuid4(),
                date(2026, 10, 18),
                date(2026, 10, 17),
            )

        assert excinfo.value.errors == (
            ErrorDetail(
                ErrorCode.INVALID_RANGE,
                "A data inicial deve ser anterior ou igual à data final.",
                "start_date",
            ),
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Selecione um contrato.", "asset_id"),
        )


class TestPriceReader:
    def test_it_satisfies_the_public_contract(self, world: World) -> None:
        reader: PriceReader = world.reader
        assert reader is world.reader

    async def test_exact_date_only_never_carry_forward(self, world: World) -> None:
        await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(reference_date=date(2026, 10, 16)),
        )

        # 17/10 is a Saturday with no price: the 16/10 price is not used for it.
        assert (await world.reader.get([world.asset.id], [date(2026, 10, 17)])).get(
            (world.asset.id, date(2026, 10, 17))
        ) is None

    async def test_many_pairs_in_one_read_with_absent_pairs_left_out(self, world: World) -> None:
        other = world.assets.add(di1_contract("DI1F28", maturity=date(2029, 1, 2)))
        b3 = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(source=PriceSource.B3),
        )
        manual = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())
        other_price = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(
                asset_id=other.id,
                reference_date=date(2026, 10, 15),
                pu="80206.1333187932",
                source=PriceSource.B3,
            ),
        )

        found = await world.reader.get([world.asset.id, other.id], [date(2026, 10, 15), DAY])

        assert b3 not in found.values()
        assert found == {(world.asset.id, DAY): manual, (other.id, date(2026, 10, 15)): other_price}

    async def test_nothing_asked_reads_nothing(self, world: World) -> None:
        assert await world.reader.get([], [DAY]) == {}
        assert await world.reader.get([world.asset.id], []) == {}


class TestLatest:
    """`PriceReader.latest`, for ``Instrument.last_reference`` (OQ-48)."""

    def test_it_satisfies_the_public_contract(self, world: World) -> None:
        reader: PriceReader = world.reader
        assert inspect.signature(type(reader).latest) == inspect.signature(PriceReader.latest)

    async def test_the_latest_date_wins_over_the_source(self, world: World) -> None:
        # MANUAL on 14/10 is older than B3 on 16/10: the latest date comes first, then MANUAL > B3.
        await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(reference_date=date(2026, 10, 14)),
        )
        b3 = await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(source=PriceSource.B3, pu="89240.4279488087"),
        )

        assert await world.reader.latest([world.asset.id]) == {world.asset.id: b3}

    async def test_on_the_latest_date_manual_wins_over_b3(self, world: World) -> None:
        await world.service(FakeUnitOfWork()).set_reference_price(
            **world.request(source=PriceSource.B3, pu="89240.4279488087"),
        )
        manual = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())

        assert await world.reader.latest([world.asset.id]) == {world.asset.id: manual}

    async def test_assets_without_a_price_are_absent(self, world: World) -> None:
        other = world.assets.add(di1_contract("DI1F28", maturity=date(2029, 1, 2)))
        price = await world.service(FakeUnitOfWork()).set_reference_price(**world.request())

        found = await world.reader.latest([world.asset.id, other.id, uuid4()])

        assert found == {world.asset.id: price}

    async def test_nothing_asked_reads_nothing(self, world: World) -> None:
        assert await world.reader.latest([]) == {}
