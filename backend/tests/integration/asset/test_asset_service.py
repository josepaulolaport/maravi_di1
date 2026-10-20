"""`AssetService` against PostgreSQL 16 (spec §3, §11.2; schema.md "Application invariants";
plan §4.A tests: invalid hierarchy, duplicate codes, missing maturity, futures spec lookup).

- The hierarchy FUTURE → INTEREST_RATE_FUTURE → DI1 → DI1F27 is registered and read back.
- Codes are unique case-insensitively at every level; an instrument code is stored trimmed and
  upper-cased (user, 2026-10-19).
- The futures specification is product-level and only on FUTURE products; maturity is
  instrument-level and required for a future.
- A body id that does not exist is a ``VALIDATION_ERROR`` on its field (user, 2026-10-19); the
  resource of a read that does not exist is ``NOT_FOUND``.
- A refused write leaves nothing behind; an accepted one is committed.
- Search is case- and accent-insensitive (user, 2026-10-19); instruments are listed by maturity.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.asset.application.services.asset_service import AssetService
from di1.modules.asset.domain.model import AssetClass, FuturesTerms, InstrumentType
from di1.modules.asset.infrastructure.persistence.repositories import SqlAssetRepository
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from tests.support.builders import DI1_NAME
from tests.support.db import DI1_FUTURES, Di1Catalogue, Writer


def _problems(error: pytest.ExceptionInfo[DomainError]) -> list[tuple[ErrorCode, str | None]]:
    return [(detail.code, detail.field) for detail in error.value.errors]


async def _count(session_factory: async_sessionmaker[AsyncSession], table: str) -> int:
    async with session_factory() as session:
        return int(
            (await session.execute(text(f"SELECT count(*) FROM asset.{table}"))).scalar_one()
        )


class TestHierarchy:
    async def test_the_di1_catalogue_reads_back(
        self, di1: Di1Catalogue, service: AssetService
    ) -> None:
        types = await service.list_instrument_types()

        assert types == [
            InstrumentType(
                id=di1.future_type_id,
                code="FUTURE",
                name="Futuros",
                asset_classes=(
                    AssetClass(di1.interest_rate_class_id, "INTEREST_RATE_FUTURE",
                               "Futuros de Taxa de Juros"),
                ),
            )
        ]  # fmt: skip
        product = await service.get_product(di1.di1_id)
        assert (product.code, product.name, product.instrument_count) == ("DI1", DI1_NAME, 4)
        assert product.asset_class.code == "INTEREST_RATE_FUTURE"
        assert product.instrument_type.code == "FUTURE"
        assert product.futures == DI1_FUTURES

    async def test_a_type_without_classes_is_listed_with_none(
        self, writer: Writer, service: AssetService
    ) -> None:
        await writer.instrument_type("OPTION", "Opções")

        types = await service.list_instrument_types()

        assert [(t.code, t.asset_classes) for t in types] == [("OPTION", ())]

    @pytest.mark.parametrize("asset_class_id", [999, 0, -1, 32768, 10**12])
    async def test_a_product_needs_an_existing_class(
        self, writer: Writer, asset_class_id: int
    ) -> None:
        # Out of the SMALLINT range is simply not an existing class, never a database error.
        with pytest.raises(DomainError) as error:
            await writer.product(asset_class_id, "DI1", DI1_NAME, DI1_FUTURES)

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "asset_class_id")]

    @pytest.mark.parametrize("name", ["", "   "])
    async def test_a_product_name_is_not_blank(
        self, di1: Di1Catalogue, writer: Writer, name: str
    ) -> None:
        with pytest.raises(DomainError) as error:
            await writer.product(di1.interest_rate_class_id, "DAP", name, DI1_FUTURES)

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "name")]


class TestFuturesSpecification:
    async def test_a_future_product_without_one_is_refused(
        self, writer: Writer, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        future = await writer.instrument_type("FUTURE", "Futuros")
        rates = await writer.asset_class(future, "INTEREST_RATE_FUTURE", "Juros")

        with pytest.raises(DomainError) as error:
            await writer.product(rates, "DI1", DI1_NAME, None)

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "futures")]
        assert await _count(session_factory, "products") == 0

    async def test_a_product_of_another_type_cannot_have_one(self, writer: Writer) -> None:
        option = await writer.instrument_type("OPTION", "Opções")
        equity = await writer.asset_class(option, "EQUITY_OPTION", "Opções de ações")

        with pytest.raises(DomainError) as error:
            await writer.product(equity, "PETR", "Opção de PETR4", DI1_FUTURES)

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "futures")]

    async def test_a_product_of_another_type_has_none(
        self, writer: Writer, service: AssetService
    ) -> None:
        option = await writer.instrument_type("OPTION", "Opções")
        equity = await writer.asset_class(option, "EQUITY_OPTION", "Opções de ações")
        product_id = await writer.product(equity, "PETR", "Opção de PETR4", None)

        assert (await service.get_product(product_id)).futures is None

    async def test_its_checks_are_reported_on_their_fields(self, writer: Writer) -> None:
        future = await writer.instrument_type("FUTURE", "Futuros")
        rates = await writer.asset_class(future, "INTEREST_RATE_FUTURE", "Juros")
        terms = FuturesTerms(Decimal("0"), Decimal("-1"), "", None)

        with pytest.raises(DomainError) as error:
            await writer.product(rates, "DI1", DI1_NAME, terms)

        assert _problems(error) == [
            (ErrorCode.VALIDATION_ERROR, "futures.face_value"),
            (ErrorCode.VALIDATION_ERROR, "futures.contract_multiplier"),
            (ErrorCode.VALIDATION_ERROR, "futures.settlement_method"),
        ]


class TestDuplicateCodes:
    @pytest.mark.parametrize("code", ["DI1", "di1", "Di1"])
    async def test_products_case_insensitively(
        self, di1: Di1Catalogue, writer: Writer, code: str
    ) -> None:
        with pytest.raises(DomainError) as error:
            await writer.product(di1.interest_rate_class_id, code, "Outro", DI1_FUTURES)

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "code")]

    @pytest.mark.parametrize("code", ["DI1F27", "di1f27", "  Di1F27 "])
    async def test_instruments_case_insensitively(
        self,
        di1: Di1Catalogue,
        writer: Writer,
        session_factory: async_sessionmaker[AsyncSession],
        code: str,
    ) -> None:
        with pytest.raises(DomainError) as error:
            await writer.instrument(di1.di1_id, code, date(2027, 1, 4))

        assert error.value.errors == (
            ErrorDetail(
                ErrorCode.VALIDATION_ERROR, "Já existe um contrato com este código.", "code"
            ),
        )
        assert await _count(session_factory, "instruments") == 4

    async def test_a_concurrent_insert_is_reported_as_a_duplicate(
        self, di1: Di1Catalogue, reader_session: AsyncSession
    ) -> None:
        # The service checks first; the unique index on upper(code) catches the race after it.
        repository = SqlAssetRepository(reader_session)

        assert await repository.add_instrument(di1.di1_id, "di1f27", date(2027, 1, 4)) is None

    async def test_a_lost_race_is_a_validation_error_and_writes_nothing(
        self, di1: Di1Catalogue, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        class RacingRepository(SqlAssetRepository):
            async def instrument_code_exists(self, code: str) -> bool:
                return False  # the other writer commits between the check and the insert

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            service = AssetService(RacingRepository(uow.session), uow)
            with pytest.raises(DomainError) as error:
                await service.create_instrument(di1.di1_id, "DI1F27", date(2027, 1, 4))

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "code")]
        assert await _count(session_factory, "instruments") == 4


class TestInstruments:
    async def test_the_code_is_stored_trimmed_and_upper_cased(
        self, di1: Di1Catalogue, writer: Writer, service: AssetService
    ) -> None:
        instrument_id = await writer.instrument(di1.di1_id, "  di1n27 ", date(2027, 7, 1))

        instrument = await service.get_instrument(instrument_id)
        assert (instrument.code, instrument.product_id, instrument.product_code) == (
            "DI1N27",
            di1.di1_id,
            "DI1",
        )
        assert instrument.maturity_date == date(2027, 7, 1)
        assert instrument.created_at is not None
        assert instrument.created_at.tzinfo is not None

    async def test_a_future_needs_a_maturity(
        self,
        di1: Di1Catalogue,
        writer: Writer,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        with pytest.raises(DomainError) as error:
            await writer.instrument(di1.di1_id, "DI1N27", None)

        assert error.value.errors == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe o vencimento.", "maturity_date"),
        )
        assert await _count(session_factory, "instruments") == 4

    async def test_an_instrument_of_another_type_may_have_no_maturity(
        self, writer: Writer, service: AssetService
    ) -> None:
        option = await writer.instrument_type("OPTION", "Opções")
        equity = await writer.asset_class(option, "EQUITY_OPTION", "Opções de ações")
        product_id = await writer.product(equity, "PETR", "Opção de PETR4", None)

        instrument_id = await writer.instrument(product_id, "PETRA10", None)

        assert (await service.get_instrument(instrument_id)).maturity_date is None

    async def test_an_unknown_product_is_a_validation_error_with_every_other_problem(
        self, di1: Di1Catalogue, writer: Writer
    ) -> None:
        with pytest.raises(DomainError) as error:
            await writer.instrument(uuid4(), "  ", None)

        assert _problems(error) == [
            (ErrorCode.VALIDATION_ERROR, "code"),
            (ErrorCode.VALIDATION_ERROR, "product_id"),
        ]
        assert error.value.errors[1].message == "Produto não encontrado."

    async def test_a_nul_in_the_code_is_a_validation_error(
        self, di1: Di1Catalogue, writer: Writer
    ) -> None:
        with pytest.raises(DomainError) as error:
            await writer.instrument(di1.di1_id, "DI1\x00N27", date(2027, 7, 1))

        assert _problems(error) == [(ErrorCode.VALIDATION_ERROR, "code")]

    async def test_a_past_maturity_is_accepted(
        self, di1: Di1Catalogue, writer: Writer, service: AssetService
    ) -> None:
        # Maturities are exempt from the "nothing after today" rule and have no other bound.
        instrument_id = await writer.instrument(di1.di1_id, "DI1F20", date(2020, 1, 2))

        assert (await service.get_instrument(instrument_id)).code == "DI1F20"


class TestReads:
    async def test_instruments_are_listed_by_maturity(
        self, di1: Di1Catalogue, writer: Writer, service: AssetService
    ) -> None:
        await writer.instrument(di1.di1_id, "DI1N27", date(2027, 7, 1))

        listed = await service.list_instruments(product_id=di1.di1_id)

        assert [i.code for i in listed] == ["DI1F27", "DI1N27", "DI1F28", "DI1F29", "DI1F30"]

    async def test_instruments_of_another_product_are_not_listed(
        self, di1: Di1Catalogue, writer: Writer, service: AssetService
    ) -> None:
        other = await writer.product(
            di1.interest_rate_class_id, "DAP", "Cupom de IPCA", DI1_FUTURES
        )
        await writer.instrument(other, "DAPK35", date(2035, 5, 15))

        assert len(await service.list_instruments(product_id=di1.di1_id)) == 4
        assert [i.code for i in await service.list_instruments(product_id=other)] == ["DAPK35"]
        assert len(await service.list_instruments()) == 5

    @pytest.mark.parametrize(("search", "codes"), [("f2", ["DI1F27", "DI1F28", "DI1F29"]),
                                                    ("DI1F30", ["DI1F30"]), ("x", [])])  # fmt: skip
    async def test_instruments_are_searched_by_code(
        self, di1: Di1Catalogue, service: AssetService, search: str, codes: list[str]
    ) -> None:
        listed = await service.list_instruments(search=search)

        assert [i.code for i in listed] == codes

    @pytest.mark.parametrize("search", ["di1", "depositos", "JUROS", None])
    async def test_products_are_searched_by_code_name_and_class(
        self, di1: Di1Catalogue, service: AssetService, search: str | None
    ) -> None:
        assert [p.code for p in await service.list_products(search=search)] == ["DI1"]

    async def test_products_are_filtered_by_type_code(
        self, di1: Di1Catalogue, writer: Writer, service: AssetService
    ) -> None:
        option = await writer.instrument_type("OPTION", "Opções")
        equity = await writer.asset_class(option, "EQUITY_OPTION", "Opções de ações")
        await writer.product(equity, "PETR", "Opção de PETR4", None)

        assert [p.code for p in await service.list_products(instrument_type="FUTURE")] == ["DI1"]
        assert [p.code for p in await service.list_products(instrument_type="future")] == ["DI1"]
        assert [p.code for p in await service.list_products(instrument_type="OPTION")] == ["PETR"]
        assert await service.list_products(instrument_type="SWAP") == []
        assert [p.code for p in await service.list_products()] == ["DI1", "PETR"]

    @pytest.mark.parametrize("instrument_type", ["", "   "])
    async def test_a_blank_type_filter_is_no_filter(
        self, di1: Di1Catalogue, service: AssetService, instrument_type: str
    ) -> None:
        assert [p.code for p in await service.list_products(instrument_type=instrument_type)] == [
            "DI1"
        ]

    async def test_a_type_filter_with_a_nul_matches_nothing(
        self, di1: Di1Catalogue, service: AssetService
    ) -> None:
        assert await service.list_products(instrument_type="FUT\x00URE") == []

    async def test_a_missing_product_or_instrument_is_not_found(
        self, di1: Di1Catalogue, service: AssetService
    ) -> None:
        with pytest.raises(DomainError) as product:
            await service.get_product(uuid4())
        with pytest.raises(DomainError) as instrument:
            await service.get_instrument(uuid4())

        assert product.value.errors == (
            ErrorDetail(ErrorCode.NOT_FOUND, "Produto não encontrado."),
        )
        assert instrument.value.errors == (
            ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."),
        )
