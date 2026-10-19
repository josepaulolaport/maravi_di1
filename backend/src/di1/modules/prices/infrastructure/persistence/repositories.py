"""`ReferencePriceRepository` over one `AsyncSession`: rows to `ReferencePriceRecord`, no rules."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.prices.application.interfaces.ports import NewReferencePrice
from di1.modules.prices.infrastructure.persistence.queries import reference_prices as queries
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.input_kind import InputKind


class SqlReferencePriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @classmethod
    def of(cls, uow: UnitOfWork) -> SqlReferencePriceRepository:
        """The repository over ``uow``'s session (a `RepositoryFactory`)."""
        return cls(uow.session)

    async def replace(self, price: NewReferencePrice) -> ReferencePriceRecord:
        result = await self._session.execute(
            queries.replace_price(
                asset_id=price.asset_id,
                reference_date=price.reference_date,
                source=price.source.value,
                input_kind=price.input_kind.value,
                pu=price.pu,
                rate=price.rate,
            )
        )
        return _record(result.one())

    async def update(
        self, price_id: UUID, input_kind: InputKind, pu: Decimal, rate: Decimal | None
    ) -> ReferencePriceRecord | None:
        result = await self._session.execute(
            queries.update_price(price_id, input_kind=input_kind.value, pu=pu, rate=rate)
        )
        return _optional(result.one_or_none())

    async def get(self, price_id: UUID) -> ReferencePriceRecord | None:
        result = await self._session.execute(queries.select_price(price_id))
        return _optional(result.one_or_none())

    async def delete(self, price_id: UUID) -> ReferencePriceRecord | None:
        result = await self._session.execute(queries.delete_price(price_id))
        return _optional(result.one_or_none())

    async def find(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Sequence[ReferencePriceRecord]:
        result = await self._session.execute(queries.select_prices(asset_ids, dates))
        return [_record(row) for row in result]

    async def find_on_latest_date(
        self, asset_ids: Collection[UUID]
    ) -> Sequence[ReferencePriceRecord]:
        result = await self._session.execute(queries.select_prices_on_latest_date(asset_ids))
        return [_record(row) for row in result]

    async def find_in_range(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> Sequence[ReferencePriceRecord]:
        result = await self._session.execute(
            queries.select_prices_in_range(asset_id, start_date, end_date)
        )
        return [_record(row) for row in result]


def _optional(row: Row[Any] | None) -> ReferencePriceRecord | None:
    return None if row is None else _record(row)


def _record(row: Row[Any]) -> ReferencePriceRecord:
    return ReferencePriceRecord(
        id=row.id,
        asset_id=row.asset_id,
        reference_date=row.reference_date,
        source=PriceSource(row.source),
        input_kind=InputKind(row.input_kind),
        pu=row.pu,
        rate=row.rate,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
