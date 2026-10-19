"""HTTP shapes of ``/ledger/entries``: the frozen frontend contract
``frontend/src/api/contract/ledger.ts`` at 57b4df0 (OQ-24, OQ-26 item 8).

Pydantic checks syntax only; every business rule (dates, maturity, decimal places, bounds, which
fields a type takes) is the service's, so its pt-BR messages reach the client. Decimals cross
HTTP as strings. The create body is one flat model rather than a discriminated union, so an
error names the field the client knows (``execution_pu``, not ``PU.execution_pu``).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, WithJsonSchema

from di1.modules.ledger.application.services.ledger_service import LedgerEntryView
from di1.modules.ledger.domain.entries import EntryDraft, EntryType
from di1.shared.clock import SAO_PAULO
from di1.shared.decimals import to_plain
from di1.shared.input_kind import InputKind

_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
_WALL_TIME = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")


def _decimal_string(value: object) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("a decimal number as a string")
    return Decimal(value)


def _wall_time(value: object) -> time:
    if not isinstance(value, str) or not _WALL_TIME.fullmatch(value):
        raise ValueError("HH:MM or HH:MM:SS")
    return time.fromisoformat(value)


DecimalString = Annotated[
    Decimal,
    BeforeValidator(_decimal_string),
    WithJsonSchema({"type": "string", "pattern": _DECIMAL.pattern}),
]
"""A plain decimal number sent as a string (``"89006.4625467350"``); trailing zeros are kept,
since they were typed (OQ-3). A JSON number is refused: it may already have lost precision."""

WallTime = Annotated[
    time,
    BeforeValidator(_wall_time),
    WithJsonSchema({"type": "string", "pattern": _WALL_TIME.pattern}),
]
"""São Paulo local time as ``HH:MM`` or ``HH:MM:SS``, without fractions (contract IsoTime)."""


class CreateLedgerEntryBody(BaseModel):
    """``POST /ledger/entries``: a TRADE (contract, signed quantity, and the PU or the rate named
    by ``input_kind``) or a CASH entry (signed ``cash_amount``)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["TRADE", "CASH"]
    date: date
    time: WallTime
    asset_id: UUID | None = None
    signed_quantity: StrictInt | None = None
    input_kind: Literal["PU", "RATE"] | None = None
    execution_pu: DecimalString | None = None
    execution_rate: DecimalString | None = None
    cash_amount: DecimalString | None = None

    def to_draft(self) -> EntryDraft:
        return EntryDraft(
            type=EntryType(self.type),
            entry_date=self.date,
            entry_time=self.time,
            asset_id=self.asset_id,
            signed_quantity=self.signed_quantity,
            input_kind=InputKind(self.input_kind) if self.input_kind is not None else None,
            execution_pu=self.execution_pu,
            execution_rate=self.execution_rate,
            cash_amount=self.cash_amount,
        )


class DeleteLedgerEntriesBody(BaseModel):
    """``POST /ledger/entries/deletions``."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID]


class _EntryBase(BaseModel):
    id: UUID
    date: date
    time: str = Field(description="HH:MM:SS, São Paulo local time")
    seq: int
    cash_amount: str = Field(
        description="The signed cash effect: −signed_quantity × execution_pu for a trade "
        "(spec §7.3), the amount for a cash entry"
    )
    created_at: datetime


class TradeEntryResponse(_EntryBase):
    type: Literal["TRADE"] = "TRADE"
    asset_id: UUID
    asset_code: str
    instrument_type_code: str
    signed_quantity: int
    execution_pu: str
    execution_rate: str
    input_kind: Literal["PU", "RATE"]


class CashEntryResponse(_EntryBase):
    type: Literal["CASH"] = "CASH"


LedgerEntryResponse = Annotated[TradeEntryResponse | CashEntryResponse, Field(discriminator="type")]


class LedgerEntryPageResponse(BaseModel):
    items: list[LedgerEntryResponse]
    next_cursor: str | None


def entry_response(view: LedgerEntryView) -> TradeEntryResponse | CashEntryResponse:
    entry = view.entry
    common = {
        "id": entry.id,
        "date": entry.entry_date,
        "time": entry.entry_time.isoformat(timespec="seconds"),
        "seq": entry.seq,
        "cash_amount": to_plain(entry.cash_effect),
        "created_at": entry.created_at.astimezone(SAO_PAULO),
    }
    if entry.type is EntryType.CASH:
        return CashEntryResponse(**common)  # type: ignore[arg-type]
    assert entry.asset_id is not None and entry.signed_quantity is not None
    assert entry.execution_pu is not None and entry.execution_rate is not None
    assert entry.input_kind is not None
    assert view.asset_code is not None and view.instrument_type_code is not None
    return TradeEntryResponse(
        **common,  # type: ignore[arg-type]
        asset_id=entry.asset_id,
        asset_code=view.asset_code,
        instrument_type_code=view.instrument_type_code,
        signed_quantity=entry.signed_quantity,
        execution_pu=to_plain(entry.execution_pu),
        execution_rate=to_plain(entry.execution_rate),
        input_kind=entry.input_kind.value,
    )
