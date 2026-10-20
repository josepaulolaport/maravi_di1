"""`ReferencePriceRepository` over one `AsyncSession`: rows to `ReferencePriceRecord`, no rules."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.prices.domain.reference_price import PriceSource, ReferencePriceRecord
from di1.modules.prices.infrastructure.persistence.models import ReferencePriceRow
from di1.modules.prices.infrastructure.persistence.queries import reference_prices as queries
from di1.shared.input_kind import InputKind


class SqlReferencePriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace(
        self,
        *,
        asset_id: UUID,
        reference_date: date,
        source: PriceSource,
        input_kind: InputKind,
        pu: Decimal,
        rate: Decimal | None,
    ) -> ReferencePriceRecord:
        statement = queries.replace_price(
            asset_id=asset_id,
            reference_date=reference_date,
            source=source.value,
            input_kind=input_kind.value,
            pu=pu,
            rate=rate,
        )
        return _to_record((await self._session.scalars(statement)).one())

    async def delete(self, price_id: UUID) -> ReferencePriceRecord | None:
        row = (await self._session.scalars(queries.delete_price(price_id))).one_or_none()
        return None if row is None else _to_record(row)

    async def find(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Sequence[ReferencePriceRecord]:
        rows = await self._session.scalars(queries.select_prices(asset_ids, dates))
        return [_to_record(row) for row in rows]

    async def find_on_latest_date(
        self, asset_ids: Collection[UUID]
    ) -> Sequence[ReferencePriceRecord]:
        rows = await self._session.scalars(queries.select_prices_on_latest_date(asset_ids))
        return [_to_record(row) for row in rows]

    async def find_in_range(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> Sequence[ReferencePriceRecord]:
        rows = await self._session.scalars(
            queries.select_prices_in_range(asset_id, start_date, end_date)
        )
        return [_to_record(row) for row in rows]


def _to_record(row: ReferencePriceRow) -> ReferencePriceRecord:
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
