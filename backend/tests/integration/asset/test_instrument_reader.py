"""`AssetReader` against PostgreSQL 16 (asset/public.py; interfaces.md "Asset"; plan §4.A "Done":
the public API supplies the full DI1 descriptor for the trade and pricing calculators).

The descriptor carries the type and class codes, the product's shared futures specification
(``None`` for a product that is not a future) and the contract's own maturity. ``get_instrument``
raises ``NOT_FOUND`` for an unknown id; ``get_instruments`` leaves unknown ids out.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.dependencies import asset_reader
from di1.modules.asset.public import InstrumentDescriptor
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from tests.integration.asset.conftest import Di1Catalogue, Writer


async def test_a_di1_contract_has_its_full_descriptor(
    di1: Di1Catalogue, reader_session: AsyncSession
) -> None:
    f27 = di1.instrument_ids["DI1F27"]

    descriptor = await asset_reader(reader_session).get_instrument(f27)

    assert descriptor == InstrumentDescriptor(
        id=f27,
        code="DI1F27",
        product_id=di1.di1_id,
        product_code="DI1",
        instrument_type="FUTURE",
        asset_class="INTEREST_RATE_FUTURE",
        maturity_date=date(2027, 1, 4),
        face_value=Decimal("100000"),
        multiplier=Decimal("1"),
        settlement_method="CASH",
    )


async def test_an_unknown_instrument_is_not_found(
    di1: Di1Catalogue, reader_session: AsyncSession
) -> None:
    with pytest.raises(DomainError) as error:
        await asset_reader(reader_session).get_instrument(uuid4())

    assert error.value.errors == (ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."),)


async def test_many_leaves_unknown_ids_out(di1: Di1Catalogue, reader_session: AsyncSession) -> None:
    f28, f30 = di1.instrument_ids["DI1F28"], di1.instrument_ids["DI1F30"]

    found = await asset_reader(reader_session).get_instruments([f28, uuid4(), f30])

    assert set(found) == {f28, f30}
    assert (found[f28].code, found[f30].maturity_date) == ("DI1F28", date(2030, 1, 2))


async def test_many_with_no_ids_is_empty(reader_session: AsyncSession) -> None:
    assert await asset_reader(reader_session).get_instruments([]) == {}


async def test_a_product_that_is_not_a_future_has_no_futures_fields(
    writer: Writer, reader_session: AsyncSession
) -> None:
    option = await writer.instrument_type("OPTION", "Opções")
    equity = await writer.asset_class(option, "EQUITY_OPTION", "Opções de ações")
    product_id = await writer.product(equity, "PETR", "Opção de PETR4", None)
    instrument_id = await writer.instrument(product_id, "PETRA10", None)

    descriptor = await asset_reader(reader_session).get_instrument(instrument_id)

    assert (descriptor.instrument_type, descriptor.asset_class) == ("OPTION", "EQUITY_OPTION")
    assert (
        descriptor.maturity_date,
        descriptor.face_value,
        descriptor.multiplier,
        descriptor.settlement_method,
    ) == (None, None, None, None)
