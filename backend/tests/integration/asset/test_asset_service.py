"""`AssetService` against PostgreSQL 16 (spec §3, §11.2; schema.md "Application invariants";
plan §4.A tests: invalid hierarchy, duplicate codes, missing maturity, futures spec lookup).

- The hierarchy FUTURE → INTEREST_RATE_FUTURE → DI1 → DI1F27 is registered and read back.
- Codes are unique case-insensitively at every level; an instrument code is stored trimmed and
  upper-cased (user, 2026-10-19).
- A body id that does not exist is a ``VALIDATION_ERROR`` on its field (user, 2026-10-19), even
  out of its column's range.
- A refused write reports every problem and leaves nothing behind; an accepted one is committed.
  Each rule itself is tested in ``tests/unit/asset/test_rules.py``; here only that the service
  applies it to what it read from the database (the product's type, the class).
- Products are searched by code, name and class name, instruments by code (the fold itself:
  ``tests/unit/asset/test_search.py``); instruments are listed by maturity.
- The resource of a read that does not exist is ``NOT_FOUND``: ``test_http.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
from tests.support.http import errors_of


async def _count(session_factory: async_sessionmaker[AsyncSession], table: str) -> int:
    async with session_factory() as session:
        return int(
            (await session.execute(text(f"SELECT count(*) FROM asset.{table}"))).scalar_one()
        )


async def _option_class(writer: Writer) -> int:
    option = await writer.instrument_type("OPTION", "Opções")
    return await writer.asset_class(option, "EQUITY_OPTION", "Opções de ações")


async def test_the_di1_catalogue_reads_back(di1: Di1Catalogue, service: AssetService) -> None:
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
    writer: Writer, service: AssetService
) -> None:
    await writer.instrument_type("OPTION", "Opções")

    types = await service.list_instrument_types()

    assert [(t.code, t.asset_classes) for t in types] == [("OPTION", ())]


async def test_a_product_code_is_stored_trimmed_and_upper_cased(
    di1: Di1Catalogue, writer: Writer, service: AssetService
) -> None:
    product_id = await writer.product(di1.interest_rate_class_id, " dap ", "Cupom", DI1_FUTURES)

    assert (await service.get_product(product_id)).code == "DAP"


async def test_a_product_of_another_type_is_stored_without_futures(
    writer: Writer, service: AssetService
) -> None:
    product_id = await writer.product(await _option_class(writer), "PETR", "Opção", None)

    assert (await service.get_product(product_id)).futures is None


async def test_an_instrument_of_another_type_is_stored_without_maturity(
    writer: Writer, service: AssetService
) -> None:
    product_id = await writer.product(await _option_class(writer), "PETR", "Opção", None)

    instrument_id = await writer.instrument(product_id, "PETRA10", None)

    assert (await service.get_instrument(instrument_id)).maturity_date is None


async def test_a_past_maturity_is_stored(
    di1: Di1Catalogue, writer: Writer, service: AssetService
) -> None:
    # The schema has no bound on a maturity either (the rule: test_rules.py).
    instrument_id = await writer.instrument(di1.di1_id, "DI1F20", date(2020, 1, 2))

    assert (await service.get_instrument(instrument_id)).maturity_date == date(2020, 1, 2)


Write = Callable[[Writer, Di1Catalogue], Awaitable[object]]


async def _blank_product_name(writer: Writer, di1: Di1Catalogue) -> object:
    return await writer.product(di1.interest_rate_class_id, "DAP", "   ", DI1_FUTURES)


async def _future_product_without_futures(writer: Writer, di1: Di1Catalogue) -> object:
    return await writer.product(di1.interest_rate_class_id, "DAP", "Cupom", None)


async def _option_product_with_futures(writer: Writer, di1: Di1Catalogue) -> object:
    return await writer.product(await _option_class(writer), "PETR", "Opção", DI1_FUTURES)


async def _every_futures_check(writer: Writer, di1: Di1Catalogue) -> object:
    terms = FuturesTerms(Decimal("0"), Decimal("-1"), "", None)
    return await writer.product(di1.interest_rate_class_id, "DAP", "Cupom", terms)


async def _future_instrument_without_maturity(writer: Writer, di1: Di1Catalogue) -> object:
    return await writer.instrument(di1.di1_id, "DI1N27", None)


VALIDATION = ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize(
    ("write", "table", "problems"),
    [
        pytest.param(_blank_product_name, "products", [(VALIDATION, "name")], id="blank-name"),
        pytest.param(
            _future_product_without_futures,
            "products",
            [(VALIDATION, "futures")],
            id="future-without-futures",
        ),
        pytest.param(
            _option_product_with_futures,
            "products",
            [(VALIDATION, "futures")],
            id="option-with-futures",
        ),
        pytest.param(
            _every_futures_check,
            "products",
            [
                (VALIDATION, "futures.face_value"),
                (VALIDATION, "futures.contract_multiplier"),
                (VALIDATION, "futures.settlement_method"),
            ],
            id="futures-checks",
        ),
        pytest.param(
            _future_instrument_without_maturity,
            "instruments",
            [(VALIDATION, "maturity_date")],
            id="future-without-maturity",
        ),
    ],
)
async def test_a_refused_write_reports_every_problem_and_writes_nothing(
    di1: Di1Catalogue,
    writer: Writer,
    session_factory: async_sessionmaker[AsyncSession],
    write: Write,
    table: str,
    problems: list[tuple[ErrorCode, str]],
) -> None:
    before = await _count(session_factory, table)

    with pytest.raises(DomainError) as error:
        await write(writer, di1)

    assert errors_of(error) == problems
    assert await _count(session_factory, table) == before


async def test_an_unknown_product_is_a_validation_error_with_every_other_problem(
    di1: Di1Catalogue, writer: Writer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    with pytest.raises(DomainError) as error:
        await writer.instrument(uuid4(), "  ", None)

    assert errors_of(error) == [(VALIDATION, "code"), (VALIDATION, "product_id")]
    assert error.value.errors[1].message == "Produto não encontrado."
    assert await _count(session_factory, "instruments") == 4


@pytest.mark.parametrize("asset_class_id", [999, 0, -1, 32768, 10**12])
async def test_a_product_needs_an_existing_class(writer: Writer, asset_class_id: int) -> None:
    # Out of the SMALLINT range is simply not an existing class, never a database error.
    with pytest.raises(DomainError) as error:
        await writer.product(asset_class_id, "DI1", DI1_NAME, DI1_FUTURES)

    assert error.value.errors == (
        ErrorDetail(VALIDATION, "Classe de ativo não encontrada.", "asset_class_id"),
    )


@pytest.mark.parametrize("code", ["DI1", "di1", " Di1 "])
async def test_a_duplicate_product_code_is_refused_case_insensitively(
    di1: Di1Catalogue,
    writer: Writer,
    session_factory: async_sessionmaker[AsyncSession],
    code: str,
) -> None:
    with pytest.raises(DomainError) as error:
        await writer.product(di1.interest_rate_class_id, code, "Outro", DI1_FUTURES)

    assert error.value.errors == (
        ErrorDetail(VALIDATION, "Já existe um produto com este código.", "code"),
    )
    assert await _count(session_factory, "products") == 1


@pytest.mark.parametrize("code", ["DI1F27", "di1f27", "  Di1F27 "])
async def test_a_duplicate_instrument_code_is_refused_case_insensitively(
    di1: Di1Catalogue,
    writer: Writer,
    session_factory: async_sessionmaker[AsyncSession],
    code: str,
) -> None:
    with pytest.raises(DomainError) as error:
        await writer.instrument(di1.di1_id, code, date(2027, 1, 4))

    assert error.value.errors == (
        ErrorDetail(VALIDATION, "Já existe um contrato com este código.", "code"),
    )
    assert await _count(session_factory, "instruments") == 4


async def test_a_concurrent_insert_is_reported_as_a_duplicate(
    di1: Di1Catalogue, reader_session: AsyncSession
) -> None:
    # The service checks first; the unique index on upper(code) catches the race after it.
    repository = SqlAssetRepository(reader_session)

    assert await repository.add_instrument(di1.di1_id, "di1f27", date(2027, 1, 4)) is None


async def test_a_lost_race_is_a_validation_error_and_writes_nothing(
    di1: Di1Catalogue, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    class RacingRepository(SqlAssetRepository):
        async def instrument_code_exists(self, code: str) -> bool:
            return False  # the other writer commits between the check and the insert

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        service = AssetService(RacingRepository(uow.session), uow)
        with pytest.raises(DomainError) as error:
            await service.create_instrument(di1.di1_id, "DI1F27", date(2027, 1, 4))

    assert errors_of(error) == [(VALIDATION, "code")]
    assert await _count(session_factory, "instruments") == 4


async def test_instruments_are_listed_by_maturity(
    di1: Di1Catalogue, writer: Writer, service: AssetService
) -> None:
    await writer.instrument(di1.di1_id, "DI1N27", date(2027, 7, 1))

    listed = await service.list_instruments(product_id=di1.di1_id)

    assert [i.code for i in listed] == ["DI1F27", "DI1N27", "DI1F28", "DI1F29", "DI1F30"]


async def test_instruments_of_another_product_are_not_listed(
    di1: Di1Catalogue, writer: Writer, service: AssetService
) -> None:
    other = await writer.product(di1.interest_rate_class_id, "DAP", "Cupom de IPCA", DI1_FUTURES)
    await writer.instrument(other, "DAPK35", date(2035, 5, 15))

    assert len(await service.list_instruments(product_id=di1.di1_id)) == 4
    assert [i.code for i in await service.list_instruments(product_id=other)] == ["DAPK35"]
    assert len(await service.list_instruments()) == 5


@pytest.mark.parametrize(("search", "codes"), [("f2", ["DI1F27", "DI1F28", "DI1F29"]),
                                                ("DI1F30", ["DI1F30"]), ("x", [])])  # fmt: skip
async def test_instruments_are_searched_by_code(
    di1: Di1Catalogue, service: AssetService, search: str, codes: list[str]
) -> None:
    listed = await service.list_instruments(search=search)

    assert [i.code for i in listed] == codes


@pytest.mark.parametrize("search", ["di1", "depositos", "JUROS", None])
async def test_products_are_searched_by_code_name_and_class(
    di1: Di1Catalogue, service: AssetService, search: str | None
) -> None:
    assert [p.code for p in await service.list_products(search=search)] == ["DI1"]


async def test_products_are_filtered_by_type_code(
    di1: Di1Catalogue, writer: Writer, service: AssetService
) -> None:
    await writer.product(await _option_class(writer), "PETR", "Opção de PETR4", None)

    assert [p.code for p in await service.list_products(instrument_type="FUTURE")] == ["DI1"]
    assert [p.code for p in await service.list_products(instrument_type="future")] == ["DI1"]
    assert [p.code for p in await service.list_products(instrument_type="OPTION")] == ["PETR"]
    assert await service.list_products(instrument_type="SWAP") == []
    assert [p.code for p in await service.list_products()] == ["DI1", "PETR"]


@pytest.mark.parametrize("instrument_type", ["", "   "])
async def test_a_blank_type_filter_is_no_filter(
    di1: Di1Catalogue, service: AssetService, instrument_type: str
) -> None:
    listed = await service.list_products(instrument_type=instrument_type)

    assert [p.code for p in listed] == ["DI1"]


async def test_a_type_filter_with_a_nul_matches_nothing(
    di1: Di1Catalogue, service: AssetService
) -> None:
    assert await service.list_products(instrument_type="FUT\x00URE") == []
