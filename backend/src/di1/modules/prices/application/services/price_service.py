"""`PriceService`: reference prices are set, corrected and removed here, and read by date
(spec §5; interfaces.md "Prices"; OQ-25, OQ-26, OQ-30, OQ-31).

A write only saves the price and commits once: it calls no Processing contract, marks nothing
and never enqueues processing (OQ-31). The PU or rate not typed is calculated by Pricing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.prices.application.interfaces.ports import (
    NewReferencePrice,
    ReferencePriceRepository,
    RepositoryFactory,
)
from di1.modules.prices.domain.reference_price import choose_preferred, validate_reference_price
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.pricing.public import PricingService, Quote
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

logger = logging.getLogger(__name__)

_UNKNOWN_ASSET = ErrorDetail(ErrorCode.VALIDATION_ERROR, "Selecione um contrato.", "asset_id")
_PRICE_NOT_FOUND = ErrorDetail(ErrorCode.NOT_FOUND, "Preço de referência não encontrado.")


@dataclass(frozen=True, slots=True)
class SetReferencePrice:
    """A price typed as a PU or as a rate; the other value is calculated."""

    asset_id: UUID
    reference_date: date
    input_kind: InputKind
    pu: Decimal | None
    rate: Decimal | None
    source: PriceSource = PriceSource.MANUAL


@dataclass(frozen=True, slots=True)
class ReferencePriceDay:
    """One date of an asset with at least one observation: the preferred one (MANUAL > B3)
    and the observation of each source, preferred first."""

    reference_date: date
    preferred: ReferencePriceRecord
    sources: tuple[ReferencePriceRecord, ...]


class PriceService:
    def __init__(
        self,
        *,
        assets: AssetReader,
        pricing: PricingService,
        repositories: RepositoryFactory,
        clock: Clock,
    ) -> None:
        self._assets = assets
        self._pricing = pricing
        self._repositories = repositories
        self._clock = clock

    async def set_reference_price(
        self, request: SetReferencePrice, *, uow: UnitOfWork
    ) -> ReferencePriceRecord:
        """Save the price of (asset, date, source); one already there is replaced, with a new
        id (OQ-26 item 7)."""
        pu, rate = await self._priced(
            request.asset_id, request.reference_date, request.input_kind, request.pu, request.rate
        )
        repository = self._repositories(uow)
        record = await repository.replace(
            NewReferencePrice(
                asset_id=request.asset_id,
                reference_date=request.reference_date,
                source=request.source,
                input_kind=request.input_kind,
                pu=pu,
                rate=rate,
            )
        )
        await uow.commit()
        logger.info(
            "reference price set: asset %s, %s, %s",
            record.asset_id,
            record.reference_date,
            record.source,
        )
        return record

    async def correct_reference_price(
        self,
        price_id: UUID,
        *,
        input_kind: InputKind,
        pu: Decimal | None,
        rate: Decimal | None,
        uow: UnitOfWork,
    ) -> ReferencePriceRecord:
        """Change the values of a price in place: same id, same asset, date and source (OQ-25)."""
        repository = self._repositories(uow)
        current = await repository.get(price_id)
        if current is None:
            raise DomainError(_PRICE_NOT_FOUND)
        new_pu, new_rate = await self._priced(
            current.asset_id, current.reference_date, input_kind, pu, rate
        )
        record = await repository.update(price_id, input_kind, new_pu, new_rate)
        if record is None:  # deleted after the read above
            raise DomainError(_PRICE_NOT_FOUND)
        await uow.commit()
        logger.info("reference price %s corrected", record.id)
        return record

    async def remove_reference_price(self, price_id: UUID, *, uow: UnitOfWork) -> None:
        """Delete a price; with MANUAL gone, B3 becomes preferred for that date (OQ-25)."""
        removed = await self._repositories(uow).delete(price_id)
        if removed is None:
            raise DomainError(_PRICE_NOT_FOUND)
        await uow.commit()
        logger.info("reference price %s removed", removed.id)

    async def list_reference_days(
        self, asset_id: UUID, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> list[ReferencePriceDay]:
        """The dates of [start_date, end_date] that have a price, newest first; a date without
        one is absent (no carry-forward). Reads only; nothing is committed."""
        errors = []
        if start_date > end_date:
            errors.append(
                ErrorDetail(
                    ErrorCode.INVALID_RANGE,
                    "A data inicial deve ser anterior ou igual à data final.",
                    "start_date",
                )
            )
        if asset_id not in await self._assets.get_instruments([asset_id]):
            errors.append(_UNKNOWN_ASSET)
        if errors:
            raise DomainError(*errors)
        observations = await self._repositories(uow).find_in_range(asset_id, start_date, end_date)
        by_date: defaultdict[date, list[ReferencePriceRecord]] = defaultdict(list)
        for observation in observations:
            by_date[observation.reference_date].append(observation)
        days = []
        for reference_date in sorted(by_date, reverse=True):
            sources = by_date[reference_date]
            preferred = choose_preferred(sources)
            assert preferred is not None  # every date here has an observation
            days.append(
                ReferencePriceDay(
                    reference_date=reference_date,
                    preferred=preferred,
                    sources=tuple(sorted(sources, key=lambda o: o is not preferred)),
                )
            )
        return days

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
        try:
            quote = validate_reference_price(
                today=self._clock.today(),
                maturity_date=None if instrument is None else instrument.maturity_date,
                reference_date=reference_date,
                input_kind=input_kind,
                pu=pu,
                rate=rate,
            )
        except DomainError as error:
            if instrument is None:
                raise DomainError(_UNKNOWN_ASSET, *error.errors) from None
            raise
        if instrument is None:
            raise DomainError(_UNKNOWN_ASSET)
        price = await self._pricing.calculate(
            instrument.id, reference_date, Quote(quote.kind, quote.value)
        )
        return price.pu, price.rate


class PreferredPriceReader:
    """`prices.public.PriceReader` over the repository of one session: exact dates only,
    MANUAL before B3, in one query for any number of pairs."""

    def __init__(self, repository: ReferencePriceRepository) -> None:
        self._repository = repository

    async def get_preferred(
        self, asset_id: UUID, reference_date: date
    ) -> ReferencePriceRecord | None:
        return (await self.get_preferred_many([asset_id], [reference_date])).get(
            (asset_id, reference_date)
        )

    async def get_preferred_many(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        if not asset_ids or not dates:
            return {}
        observations: Sequence[ReferencePriceRecord] = await self._repository.find(asset_ids, dates)
        by_pair: defaultdict[tuple[UUID, date], list[ReferencePriceRecord]] = defaultdict(list)
        for observation in observations:
            by_pair[(observation.asset_id, observation.reference_date)].append(observation)
        preferred = {pair: choose_preferred(found) for pair, found in by_pair.items()}
        return {pair: record for pair, record in preferred.items() if record is not None}
