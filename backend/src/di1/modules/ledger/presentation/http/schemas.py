"""HTTP shapes of ``/ledger/entries``: the frozen frontend contract
``frontend/src/api/contract/ledger.ts`` at 57b4df0 (OQ-24, OQ-26 item 8).

Pydantic checks syntax only; every business rule (dates, maturity, decimal
places, bounds, which fields a type takes) is the service's, so its pt-BR messages reach the
client. Decimals cross HTTP as strings. The create body is one flat model rather than a
discriminated union, so an error names the field the client knows (``execution_pu``, not
``PU.execution_pu``).
"""

from __future__ import annotations

import re
from datetime import date, time
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, StrictInt, WithJsonSchema

from di1.modules.ledger.domain.entries import EntryDraft, EntryType, LedgerEntryView
from di1.platform.http import DecimalString, RequestBody, UtcDatetime
from di1.shared.decimals import to_plain
from di1.shared.input_kind import InputKind

_WALL_TIME = re.compile(r"^[0-9]{2}:[0-9]{2}(:[0-9]{2})?$")


def _wall_time(value: object) -> time:
    if not isinstance(value, str) or not _WALL_TIME.fullmatch(value):
        raise ValueError("HH:MM or HH:MM:SS")
    return time.fromisoformat(value)


WallTime = Annotated[
    time,
    BeforeValidator(_wall_time),
    WithJsonSchema({"type": "string", "pattern": _WALL_TIME.pattern}),
]
"""São Paulo local time as ``HH:MM`` or ``HH:MM:SS``, without fractions (contract IsoTime)."""


class CreateLedgerEntryRequest(RequestBody):
    """``POST /ledger/entries``: a TRADE (contract, signed quantity, and the PU or the rate named
    by ``input_kind``) or a CASH entry (signed ``cash_amount`` and an optional ``description``,
    OQ-51)."""

    type: EntryType
    date: date
    time: WallTime
    asset_id: UUID | None = None
    signed_quantity: StrictInt | None = None
    input_kind: InputKind | None = None
    execution_pu: DecimalString | None = None
    execution_rate: DecimalString | None = None
    cash_amount: DecimalString | None = None
    description: str | None = Field(
        default=None, description="CASH only: trimmed, blank as null, at most 200 characters"
    )

    def to_draft(self) -> EntryDraft:
        return EntryDraft(
            type=self.type,
            entry_date=self.date,
            entry_time=self.time,
            asset_id=self.asset_id,
            signed_quantity=self.signed_quantity,
            input_kind=self.input_kind,
            execution_pu=self.execution_pu,
            execution_rate=self.execution_rate,
            cash_amount=self.cash_amount,
            description=self.description,
        )


class DeleteLedgerEntriesRequest(RequestBody):
    """``POST /ledger/entries/deletions``."""

    ids: list[UUID]


class _EntryResponse(BaseModel):
    id: UUID
    date: date
    time: str = Field(description="HH:MM:SS, São Paulo local time")
    seq: int
    cash_amount: str = Field(
        description="The signed cash effect: −signed_quantity × execution_pu for a trade "
        "(spec §7.3), the amount for a cash entry"
    )
    created_at: UtcDatetime


class TradeEntryResponse(_EntryResponse):
    type: Literal[EntryType.TRADE] = EntryType.TRADE
    asset_id: UUID
    asset_code: str
    instrument_type_code: str
    signed_quantity: int
    execution_pu: str
    execution_rate: str
    input_kind: InputKind

    @classmethod
    def of(cls, view: LedgerEntryView) -> Self:
        entry = view.entry
        # The schema's entries_trade_shape CHECK guarantees a trade's fields.
        assert entry.asset_id is not None and entry.signed_quantity is not None
        assert entry.execution_pu is not None and entry.execution_rate is not None
        assert entry.input_kind is not None
        assert view.asset_code is not None and view.instrument_type_code is not None
        return cls(
            id=entry.id,
            date=entry.entry_date,
            time=entry.entry_time.isoformat(timespec="seconds"),
            seq=entry.seq,
            cash_amount=to_plain(entry.cash_effect),
            created_at=entry.created_at,
            asset_id=entry.asset_id,
            asset_code=view.asset_code,
            instrument_type_code=view.instrument_type_code,
            signed_quantity=entry.signed_quantity,
            execution_pu=to_plain(entry.execution_pu),
            execution_rate=to_plain(entry.execution_rate),
            input_kind=entry.input_kind,
        )


class CashEntryResponse(_EntryResponse):
    type: Literal[EntryType.CASH] = EntryType.CASH
    description: str | None = Field(description="The aporte's or retirada's text, or null (OQ-51)")

    @classmethod
    def of(cls, view: LedgerEntryView) -> Self:
        entry = view.entry
        return cls(
            id=entry.id,
            date=entry.entry_date,
            time=entry.entry_time.isoformat(timespec="seconds"),
            seq=entry.seq,
            cash_amount=to_plain(entry.cash_effect),
            created_at=entry.created_at,
            description=entry.description,
        )


LedgerEntryResponse = Annotated[TradeEntryResponse | CashEntryResponse, Field(discriminator="type")]


def entry_response(view: LedgerEntryView) -> TradeEntryResponse | CashEntryResponse:
    if view.entry.type is EntryType.CASH:
        return CashEntryResponse.of(view)
    return TradeEntryResponse.of(view)


class LedgerEntryPageResponse(BaseModel):
    items: list[LedgerEntryResponse]
    next_cursor: str | None
