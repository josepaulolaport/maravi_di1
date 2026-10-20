"""Asset catalogue: type → class → product → instrument (spec §3, §11.2)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from uuid import UUID

from di1.modules.asset.application.ports import AssetRepository
from di1.modules.asset.domain.model import FuturesTerms, Instrument, InstrumentType, Product
from di1.modules.asset.domain.rules import (
    PRODUCT_NAME_LENGTH,
    SMALLINT_MAX,
    has_nul,
    normalize_code,
    validate_futures_for_type,
    validate_instrument_code,
    validate_maturity,
    validate_name,
    validate_product_code,
)
from di1.modules.asset.domain.search import matches
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

logger = logging.getLogger(__name__)


class AssetService:
    """The catalogue on one request's Unit of Work: each write commits it once."""

    def __init__(self, repository: AssetRepository, uow: UnitOfWork) -> None:
        self._repository = repository
        self._uow = uow

    # Reads (Ativos screen, spec §11.2)

    async def list_instrument_types(self) -> Sequence[InstrumentType]:
        return await self._repository.list_instrument_types()

    async def list_products(
        self, *, instrument_type: str | None = None, search: str | None = None
    ) -> list[Product]:
        type_code = instrument_type.strip() if instrument_type else None
        if type_code and has_nul(type_code):
            return []  # no stored code holds NUL; PostgreSQL could not even compare it
        products = await self._repository.list_products(type_code or None)
        return [p for p in products if matches((p.code, p.name, p.asset_class.name), search)]

    async def get_product(self, product_id: UUID) -> Product:
        product = await self._repository.get_product(product_id)
        if product is None:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Produto não encontrado."))
        return product

    async def list_instruments(
        self, *, product_id: UUID | None = None, search: str | None = None
    ) -> list[Instrument]:
        instruments = await self._repository.list_instruments(product_id)
        return [i for i in instruments if matches((i.code,), search)]

    async def get_instrument(self, instrument_id: UUID) -> Instrument:
        instrument = await self._repository.get_instrument(instrument_id)
        if instrument is None:
            raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado."))
        return instrument

    # Writes

    async def create_product(
        self, asset_class_id: int, code: str, name: str, futures: FuturesTerms | None
    ) -> Product:
        errors = [
            *validate_product_code(code),
            *validate_name(name, max_length=PRODUCT_NAME_LENGTH, non_blank=True),
        ]
        code = normalize_code(code)
        # Out of the SMALLINT range is simply not an existing class, never a database error.
        classified = (
            await self._repository.get_asset_class(asset_class_id)
            if 1 <= asset_class_id <= SMALLINT_MAX
            else None
        )
        if classified is None:
            errors.append(
                ErrorDetail.validation("Classe de ativo não encontrada.", "asset_class_id")
            )
        else:
            _asset_class, instrument_type = classified
            errors.extend(validate_futures_for_type(instrument_type.code, futures))
        duplicate = ErrorDetail.validation("Já existe um produto com este código.", "code")
        if not errors and await self._repository.product_code_exists(code):
            errors.append(duplicate)
        if errors:
            raise DomainError(*errors)
        product_id = await self._repository.add_product(asset_class_id, code, name, futures)
        if product_id is None:
            raise DomainError(duplicate)
        product = await self.get_product(product_id)
        await self._uow.commit()
        logger.info("product %s created", product.code)
        return product

    async def create_instrument(
        self, product_id: UUID, code: str, maturity_date: date | None
    ) -> Instrument:
        code = normalize_code(code)
        code_errors = validate_instrument_code(code)
        errors = list(code_errors)
        product = await self._repository.get_product(product_id)
        if product is None:
            errors.append(ErrorDetail.validation("Produto não encontrado.", "product_id"))
        else:
            errors.extend(validate_maturity(product.instrument_type.code, maturity_date))
        duplicate = ErrorDetail.validation("Já existe um contrato com este código.", "code")
        if not code_errors and await self._repository.instrument_code_exists(code):
            errors.append(duplicate)
        if errors:
            raise DomainError(*errors)
        instrument_id = await self._repository.add_instrument(product_id, code, maturity_date)
        if instrument_id is None:
            raise DomainError(duplicate)
        instrument = await self.get_instrument(instrument_id)
        await self._uow.commit()
        logger.info("instrument %s created", instrument.code)
        return instrument
