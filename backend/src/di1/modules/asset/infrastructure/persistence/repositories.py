"""The ``asset`` schema: rows in, read models out, no business rule. One class serves the
service (`AssetRepository`) and other modules (`asset.public.AssetReader`)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from di1.modules.asset.domain.model import (
    AssetClass,
    FuturesTerms,
    Instrument,
    InstrumentType,
    Product,
)
from di1.modules.asset.infrastructure.persistence.models import (
    AssetClassRow,
    FuturesRow,
    InstrumentRow,
    InstrumentTypeRow,
    ProductRow,
)
from di1.modules.asset.infrastructure.persistence.queries import catalogue


def _to_instrument_type(row: InstrumentTypeRow) -> InstrumentType:
    return InstrumentType(id=row.id, code=row.code, name=row.name, asset_classes=())


def _to_asset_class(row: AssetClassRow) -> AssetClass:
    return AssetClass(id=row.id, code=row.code, name=row.name)


def _to_futures(row: FuturesRow | None) -> FuturesTerms | None:
    if row is None:
        return None
    return FuturesTerms(
        face_value=row.face_value,
        contract_multiplier=row.contract_multiplier,
        settlement_method=row.settlement_method,
        settlement_description=row.settlement_description,
    )


def _to_instrument(
    row: InstrumentRow,
    product: ProductRow,
    asset_class: AssetClassRow,
    instrument_type: InstrumentTypeRow,
    futures: FuturesRow | None,
) -> Instrument:
    return Instrument(
        id=row.id,
        code=row.code,
        product_id=row.product_id,
        product_code=product.code,
        instrument_type=instrument_type.code,
        asset_class=asset_class.code,
        maturity_date=row.maturity_date,
        face_value=None if futures is None else futures.face_value,
        multiplier=None if futures is None else futures.contract_multiplier,
        settlement_method=None if futures is None else futures.settlement_method,
        created_at=row.created_at,
    )


class SqlAssetRepository:
    """Implements `AssetRepository` and `asset.public.AssetReader` on one session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_instrument_types(self) -> Sequence[InstrumentType]:
        rows = (await self._session.execute(catalogue.instrument_types_with_classes())).all()
        types: dict[int, InstrumentTypeRow] = {}
        classes: dict[int, list[AssetClass]] = {}
        for type_row, class_row in rows:
            types.setdefault(type_row.id, type_row)
            members = classes.setdefault(type_row.id, [])
            if class_row is not None:
                members.append(_to_asset_class(class_row))
        return [
            InstrumentType(id=t.id, code=t.code, name=t.name, asset_classes=tuple(classes[t.id]))
            for t in types.values()
        ]

    async def get_asset_class(
        self, asset_class_id: int
    ) -> tuple[AssetClass, InstrumentType] | None:
        found = (
            await self._session.execute(catalogue.asset_class_with_type(asset_class_id))
        ).one_or_none()
        if found is None:
            return None
        class_row, type_row = found
        return _to_asset_class(class_row), _to_instrument_type(type_row)

    async def _code_taken(self, column: InstrumentedAttribute[str], code: str) -> bool:
        return bool((await self._session.execute(catalogue.code_taken(column, code))).scalar_one())

    async def product_code_exists(self, code: str) -> bool:
        return await self._code_taken(ProductRow.code, code)

    async def instrument_code_exists(self, code: str) -> bool:
        return await self._code_taken(InstrumentRow.code, code)

    async def _flush(self) -> bool:
        """Flush; ``False`` when a unique code index refused the row (a concurrent writer won)."""
        try:
            await self._session.flush()
        except IntegrityError as error:
            diag = getattr(error.orig, "diag", None)
            if getattr(diag, "constraint_name", None) in catalogue.CODE_INDEXES:
                return False
            raise
        return True

    async def add_product(
        self, asset_class_id: int, code: str, name: str, futures: FuturesTerms | None
    ) -> UUID | None:
        row = ProductRow(asset_class_id=asset_class_id, code=code, name=name)
        self._session.add(row)
        if not await self._flush():
            return None
        if futures is not None:
            self._session.add(
                FuturesRow(
                    product_id=row.id,
                    face_value=futures.face_value,
                    contract_multiplier=futures.contract_multiplier,
                    settlement_method=futures.settlement_method,
                    settlement_description=futures.settlement_description,
                )
            )
            await self._session.flush()
        return row.id

    async def add_instrument(
        self, product_id: UUID, code: str, maturity_date: date | None
    ) -> UUID | None:
        row = InstrumentRow(product_id=product_id, code=code, maturity_date=maturity_date)
        self._session.add(row)
        return row.id if await self._flush() else None

    async def _products(
        self, *, instrument_type_code: str | None = None, product_id: UUID | None = None
    ) -> list[Product]:
        statement = catalogue.products(
            instrument_type_code=instrument_type_code, product_id=product_id
        )
        rows = (await self._session.execute(statement)).all()
        return [
            Product(
                id=product.id,
                code=product.code,
                name=product.name,
                asset_class=_to_asset_class(asset_class),
                instrument_type=_to_instrument_type(instrument_type),
                instrument_count=count,
                futures=_to_futures(futures),
                created_at=product.created_at,
            )
            for product, asset_class, instrument_type, futures, count in rows
        ]

    async def list_products(self, instrument_type_code: str | None) -> Sequence[Product]:
        return await self._products(instrument_type_code=instrument_type_code)

    async def get_product(self, product_id: UUID) -> Product | None:
        found = await self._products(product_id=product_id)
        return found[0] if found else None

    async def list_instruments(self, product_id: UUID | None) -> Sequence[Instrument]:
        rows = (await self._session.execute(catalogue.instruments(product_id=product_id))).all()
        return [_to_instrument(*row) for row in rows]

    async def get_instrument(self, instrument_id: UUID) -> Instrument | None:
        statement = catalogue.instruments(instrument_id=instrument_id)
        found = (await self._session.execute(statement)).one_or_none()
        return None if found is None else _to_instrument(*found)

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        if not instrument_ids:
            return {}
        rows = (
            await self._session.execute(catalogue.instruments(instrument_ids=instrument_ids))
        ).all()
        return {row[0].id: _to_instrument(*row) for row in rows}
