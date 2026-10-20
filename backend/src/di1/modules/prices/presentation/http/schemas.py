"""HTTP shapes of ``/reference-prices``, as the frontend contract ``prices.ts`` freezes them
(OQ-26 item 8). Decimals cross as strings in plain notation; these schemas check syntax only,
the business checks are the service's."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from di1.modules.prices.application.services.price_service import ReferencePriceDay
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.platform.http import DecimalString
from di1.shared.decimals import to_plain
from di1.shared.input_kind import InputKind


class SetReferencePriceBody(BaseModel):
    """``POST /reference-prices``: a MANUAL price typed as a PU or as a rate. One flat model, so a
    field error names ``pu`` or ``rate`` as the client sent it."""

    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    reference_date: date
    input_kind: InputKind
    pu: DecimalString | None = None
    rate: DecimalString | None = None


class ReferencePriceResponse(BaseModel):
    """``ReferencePrice`` of the contract."""

    id: UUID
    asset_id: UUID
    reference_date: date
    source: PriceSource
    input_kind: InputKind
    pu: str
    rate: str | None
    created_at: datetime

    @classmethod
    def of(cls, record: ReferencePriceRecord) -> Self:
        return cls(
            id=record.id,
            asset_id=record.asset_id,
            reference_date=record.reference_date,
            source=record.source,
            input_kind=record.input_kind,
            pu=to_plain(record.pu),
            rate=None if record.rate is None else to_plain(record.rate),
            created_at=record.created_at,
        )


class ReferencePriceDayResponse(BaseModel):
    """``ReferencePriceDay`` of the contract: the preferred price (MANUAL > B3) and each
    source's price of one date."""

    reference_date: date
    preferred: ReferencePriceResponse
    sources: list[ReferencePriceResponse]

    @classmethod
    def of(cls, day: ReferencePriceDay) -> Self:
        return cls(
            reference_date=day.reference_date,
            preferred=ReferencePriceResponse.of(day.preferred),
            sources=[ReferencePriceResponse.of(source) for source in day.sources],
        )


class ReferencePriceDayList(BaseModel):
    """``ListResponse<ReferencePriceDay>``: newest date first, dates without a price absent."""

    items: list[ReferencePriceDayResponse]
