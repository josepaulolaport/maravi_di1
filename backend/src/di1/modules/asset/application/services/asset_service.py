"""The Asset catalogue: browse type → class → product → instrument, and register them (spec §3,
§11.2; interfaces.md "Asset").

Reads serve the Ativos screen. Writes validate the whole request, report every problem at once
(all 422 ``VALIDATION_ERROR``), save and commit the Unit of Work once. An id named inside a request
body that does not exist is a ``VALIDATION_ERROR`` on its field; ``NOT_FOUND`` is only for the
resource of the URL (user, 2026-10-19). Instrument types, asset classes and products have no HTTP
route: they are registered by seeding (lane X), through this same service.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from di1.modules.asset.application.interfaces.repository import (
    AssetRepository,
    DuplicateCodeError,
)
from di1.modules.asset.domain.model import (
    AssetClass,
    Instrument,
    InstrumentType,
    InstrumentTypeRef,
    Product,
)
from di1.modules.asset.domain.rules import (
    ASSET_CLASS_CODE_LENGTH,
    ASSET_CLASS_NAME_LENGTH,
    INSTRUMENT_TYPE_CODE_LENGTH,
    INSTRUMENT_TYPE_NAME_LENGTH,
    PRODUCT_NAME_LENGTH,
    SMALLINT_MAX,
    FuturesTerms,
    has_nul,
    normalize_instrument_code,
    validate_catalogue_code,
    validate_futures_for_type,
    validate_maturity,
    validate_name,
    validate_product_code,
)
from di1.modules.asset.domain.search import matches
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NewInstrumentType:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class NewAssetClass:
    instrument_type_id: int
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class NewProduct:
    asset_class_id: int
    code: str
    name: str
    futures: FuturesTerms | None


@dataclass(frozen=True, slots=True)
class NewInstrument:
    product_id: UUID
    code: str
    maturity_date: date | None


def _invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)


def _raise_if(errors: Sequence[ErrorDetail]) -> None:
    if errors:
        raise DomainError(*errors)


def _is_smallint(value: int) -> bool:
    """Catalogue ids are SMALLINT identities: anything else names no row (and PostgreSQL would
    refuse to compare it)."""
    return 1 <= value <= SMALLINT_MAX


async def _insert[T](insert: Awaitable[T], duplicate: ErrorDetail) -> T:
    """Run ``insert``; a code taken by a concurrent writer after the service's own check (the
    unique index on ``upper(code)``) is the same ``duplicate`` error."""
    try:
        return await insert
    except DuplicateCodeError:
        raise DomainError(duplicate) from None


class AssetService:
    def __init__(self, repository: AssetRepository) -> None:
        self._repository = repository

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

    async def create_instrument_type(
        self, request: NewInstrumentType, *, uow: UnitOfWork
    ) -> InstrumentTypeRef:
        errors = [
            *validate_catalogue_code(request.code, max_length=INSTRUMENT_TYPE_CODE_LENGTH),
            *validate_name(request.name, max_length=INSTRUMENT_TYPE_NAME_LENGTH),
        ]
        duplicate = _invalid("Já existe um tipo de instrumento com este código.", "code")
        if not errors and await self._repository.instrument_type_code_exists(request.code):
            errors.append(duplicate)
        _raise_if(errors)
        created = await _insert(
            self._repository.add_instrument_type(request.code, request.name), duplicate
        )
        await uow.commit()
        logger.info("instrument type %s created", created.code)
        return created

    async def create_asset_class(self, request: NewAssetClass, *, uow: UnitOfWork) -> AssetClass:
        errors = [
            *validate_catalogue_code(request.code, max_length=ASSET_CLASS_CODE_LENGTH),
            *validate_name(request.name, max_length=ASSET_CLASS_NAME_LENGTH),
        ]
        type_id = request.instrument_type_id
        if not _is_smallint(type_id) or await self._repository.get_instrument_type(type_id) is None:
            errors.append(_invalid("Tipo de instrumento não encontrado.", "instrument_type_id"))
        duplicate = _invalid("Já existe uma classe de ativo com este código.", "code")
        if not errors and await self._repository.asset_class_code_exists(request.code):
            errors.append(duplicate)
        _raise_if(errors)
        created = await _insert(
            self._repository.add_asset_class(
                request.instrument_type_id, request.code, request.name
            ),
            duplicate,
        )
        await uow.commit()
        logger.info("asset class %s created", created.code)
        return created

    async def create_product(self, request: NewProduct, *, uow: UnitOfWork) -> Product:
        errors = [
            *validate_product_code(request.code),
            *validate_name(request.name, max_length=PRODUCT_NAME_LENGTH, non_blank=True),
        ]
        classified = (
            await self._repository.get_asset_class(request.asset_class_id)
            if _is_smallint(request.asset_class_id)
            else None
        )
        if classified is None:
            errors.append(_invalid("Classe de ativo não encontrada.", "asset_class_id"))
        else:
            errors.extend(
                validate_futures_for_type(classified.instrument_type.code, request.futures)
            )
        duplicate = _invalid("Já existe um produto com este código.", "code")
        if not errors and await self._repository.product_code_exists(request.code):
            errors.append(duplicate)
        _raise_if(errors)
        product_id = await _insert(
            self._repository.add_product(
                request.asset_class_id, request.code, request.name, request.futures
            ),
            duplicate,
        )
        product = await self.get_product(product_id)
        await uow.commit()
        logger.info("product %s created", product.code)
        return product

    async def create_instrument(self, request: NewInstrument, *, uow: UnitOfWork) -> Instrument:
        code, code_errors = normalize_instrument_code(request.code)
        errors = list(code_errors)
        product = await self._repository.get_product(request.product_id)
        if product is None:
            errors.append(_invalid("Produto não encontrado.", "product_id"))
        else:
            errors.extend(validate_maturity(product.instrument_type.code, request.maturity_date))
        duplicate = _invalid("Já existe um contrato com este código.", "code")
        if not code_errors and await self._repository.instrument_code_exists(code):
            errors.append(duplicate)
        _raise_if(errors)
        instrument_id = await _insert(
            self._repository.add_instrument(request.product_id, code, request.maturity_date),
            duplicate,
        )
        instrument = await self.get_instrument(instrument_id)
        await uow.commit()
        logger.info("instrument %s created", instrument.code)
        return instrument
