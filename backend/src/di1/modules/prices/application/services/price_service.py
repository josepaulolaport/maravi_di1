"""Reference prices: set (replace same key), remove, read by date (spec §5; OQ-25, OQ-26)."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Mapping
from datetime import date
from decimal import Decimal
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.prices.application.ports import ReferencePriceRepository
from di1.modules.prices.domain.reference_price import (
    PriceSource,
    ReferencePriceDay,
    ReferencePriceRecord,
    choose_preferred,
    reference_days,
    validate_reference_date,
)
from di1.modules.pricing.public import PricingService, Quote, validate_quote
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail, invalid_range, unknown_asset
from di1.shared.input_kind import InputKind

logger = logging.getLogger(__name__)

_PRICE_NOT_FOUND = ErrorDetail(ErrorCode.NOT_FOUND, "Preço de referência não encontrado.")


def validate_new_price(
    *,
    today: date,
    maturity_date: date | None,
    reference_date: date,
    input_kind: InputKind,
    pu: Decimal | None,
    rate: Decimal | None,
) -> tuple[ErrorDetail, ...]:
    """Every problem of a typed reference price: its date, then Pricing's one quote validation,
    whose field names the price request already uses."""
    return validate_reference_date(reference_date, today=today) + validate_quote(
        input_kind, pu=pu, rate=rate, reference_date=reference_date, maturity_date=maturity_date
    )


class PriceService:
    """Reference prices on one request's Unit of Work: each write commits it once."""

    def __init__(
        self,
        repository: ReferencePriceRepository,
        uow: UnitOfWork,
        *,
        assets: AssetReader,
        pricing: PricingService,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._uow = uow
        self._assets = assets
        self._pricing = pricing
        self._clock = clock

    async def set_reference_price(
        self,
        asset_id: UUID,
        reference_date: date,
        input_kind: InputKind,
        pu: Decimal | None,
        rate: Decimal | None,
        *,
        source: PriceSource = PriceSource.MANUAL,
    ) -> ReferencePriceRecord:
        """Save the price of (asset, date, source); one already there is replaced, with a new
        id (OQ-26 item 7)."""
        priced_pu, priced_rate = await self._priced(asset_id, reference_date, input_kind, pu, rate)
        record = await self._repository.replace(
            asset_id=asset_id,
            reference_date=reference_date,
            source=source,
            input_kind=input_kind,
            pu=priced_pu,
            rate=priced_rate,
        )
        await self._uow.commit()
        logger.info(
            "reference price set: asset %s, %s, %s",
            record.asset_id,
            record.reference_date,
            record.source,
        )
        return record

    async def remove_reference_price(self, price_id: UUID) -> None:
        """Delete a price; with MANUAL gone, B3 becomes preferred for that date (OQ-25)."""
        removed = await self._repository.delete(price_id)
        if removed is None:
            raise DomainError(_PRICE_NOT_FOUND)
        await self._uow.commit()
        logger.info("reference price %s removed", removed.id)

    async def list_reference_days(
        self, asset_id: UUID, start_date: date, end_date: date
    ) -> list[ReferencePriceDay]:
        """The dates of [start_date, end_date] that have a price, newest first; a date without
        one is absent (no carry-forward). Reads only; nothing is committed."""
        errors = []
        if start_date > end_date:
            errors.append(invalid_range())
        if asset_id not in await self._assets.get_instruments([asset_id]):
            errors.append(unknown_asset())
        if errors:
            raise DomainError(*errors)
        return reference_days(await self._repository.find_in_range(asset_id, start_date, end_date))

    async def _priced(
        self,
        asset_id: UUID,
        reference_date: date,
        input_kind: InputKind,
        pu: Decimal | None,
        rate: Decimal | None,
    ) -> tuple[Decimal, Decimal]:
        """The validated price pair. An unknown asset is reported together with every other
        problem of the request, as the frontend contract does."""
        instrument = (await self._assets.get_instruments([asset_id])).get(asset_id)
        errors = validate_new_price(
            today=self._clock.today(),
            maturity_date=None if instrument is None else instrument.maturity_date,
            reference_date=reference_date,
            input_kind=input_kind,
            pu=pu,
            rate=rate,
        )
        if instrument is None:
            errors = (unknown_asset(), *errors)
        typed = pu if input_kind is InputKind.PU else rate
        if errors or instrument is None or typed is None:  # the last two always come with errors
            raise DomainError(*errors)
        price = await self._pricing.calculate(
            instrument.id, reference_date, Quote(input_kind, typed)
        )
        return price.pu, price.rate


class DefaultPriceReader:
    """Implements `prices.public.PriceReader`: the winning MANUAL/B3 price on the caller's
    session."""

    def __init__(self, repository: ReferencePriceRepository) -> None:
        self._repository = repository

    async def get(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        if not asset_ids or not dates:
            return {}
        by_pair: defaultdict[tuple[UUID, date], list[ReferencePriceRecord]] = defaultdict(list)
        for record in await self._repository.find(asset_ids, dates):
            by_pair[(record.asset_id, record.reference_date)].append(record)
        return _winning(by_pair)

    async def latest(self, asset_ids: Collection[UUID]) -> Mapping[UUID, ReferencePriceRecord]:
        """Winning price of the latest date that has one, for ``last_reference`` (OQ-48)."""
        if not asset_ids:
            return {}
        by_asset: defaultdict[UUID, list[ReferencePriceRecord]] = defaultdict(list)
        for record in await self._repository.find_on_latest_date(asset_ids):
            by_asset[record.asset_id].append(record)
        return _winning(by_asset)


def _winning[K](groups: Mapping[K, list[ReferencePriceRecord]]) -> dict[K, ReferencePriceRecord]:
    winning = {key: choose_preferred(records) for key, records in groups.items()}
    return {key: record for key, record in winning.items() if record is not None}
