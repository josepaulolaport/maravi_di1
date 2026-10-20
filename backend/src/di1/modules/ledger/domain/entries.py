"""Ledger entries: one immutable record per trade or cash movement (spec §6; OQ-24).

- A TRADE carries the contract, the signed quantity and the execution PU and rate, one of them
  typed (``input_kind``) and the other calculated by Pricing. A CASH entry carries a signed
  amount: positive aporte, negative retirada, never 0.
- Both have a date and a required time (São Paulo) and one ``seq`` shared by both types; their
  order is ``(entry_date, entry_time, seq)`` (OQ-13, OQ-24).
- Nothing is dated after today (OQ-14). The typed PU or rate, its decimals, its bounds and the
  maturity rules (OQ-1, OQ-3, OQ-14) are Pricing's one quote validation, which the service runs
  next to these rules (``pricing.public.validate_quote``): domain code imports no other module.
  The other value bounds are only the schema's CHECKs and column ranges (OQ-14); the ``INTEGER``
  range of the quantity is the HTTP schema's.
- Each validator returns every problem it finds, empty when the draft is valid; the service
  raises them together and then writes a typed `NewTrade` or `NewCashMovement`.
- A trade's cash effect is not stored: −signed_quantity × execution_pu, computed on read (§7.3).
- Entries are never edited. A batch delete removes entries of either type for good, all or
  nothing (OQ-24; user decision 2026-10-19: no soft delete).

Error fields are the request's field names (``date``, ``time``, ``execution_pu``, ...), which the
client keys its messages on (frontend contract ``ledger.ts``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from di1.shared.decimals import ZERO, financial_context, fits_places
from di1.shared.errors import ErrorCode, ErrorDetail, future_date, unknown_asset
from di1.shared.input_kind import InputKind

CASH_PLACES = 2
"""Decimal places of a cash amount: ``cash_amount NUMERIC(20,2)`` (OQ-3, OQ-24)."""

_CASH_LIMIT = Decimal(10) ** (20 - CASH_PLACES)
"""``NUMERIC(20,2)`` holds absolute values below 10^18."""


class EntryType(StrEnum):
    """Schema ``entries_type_check``."""

    TRADE = "TRADE"
    CASH = "CASH"


@dataclass(frozen=True, slots=True)
class EntryDraft:
    """A new entry as requested, before validation: what the user typed, every field optional
    except the type, the date and the time."""

    type: EntryType
    entry_date: date
    entry_time: time
    asset_id: UUID | None = None
    signed_quantity: int | None = None
    input_kind: InputKind | None = None
    execution_pu: Decimal | None = None
    execution_rate: Decimal | None = None
    cash_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class NewTrade:
    """A validated and priced trade, as it is written: the typed value as typed, the other as
    Pricing calculated it."""

    entry_date: date
    entry_time: time
    asset_id: UUID
    signed_quantity: int
    input_kind: InputKind
    execution_pu: Decimal
    execution_rate: Decimal


@dataclass(frozen=True, slots=True)
class NewCashMovement:
    """A validated aporte (positive) or retirada (negative), as it is written."""

    entry_date: date
    entry_time: time
    amount: Decimal


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One row of ``ledger.entries``. The trade fields are set only on a TRADE and
    ``cash_amount`` only on a CASH entry (schema ``entries_trade_shape``/``entries_cash_shape``).
    """

    id: UUID
    type: EntryType
    entry_date: date
    entry_time: time
    seq: int
    created_at: datetime
    asset_id: UUID | None
    signed_quantity: int | None
    execution_pu: Decimal | None
    execution_rate: Decimal | None
    input_kind: InputKind | None
    cash_amount: Decimal | None

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order across both types (OQ-13, OQ-24)."""
        return (self.entry_date, self.entry_time, self.seq)

    @property
    def cash_effect(self) -> Decimal:
        """The signed cash the entry moves: −signed_quantity × execution_pu for a trade (§7.3),
        exact; the signed amount for a cash entry (§6.2)."""
        if self.type is EntryType.CASH:
            assert self.cash_amount is not None
            return self.cash_amount
        assert self.signed_quantity is not None and self.execution_pu is not None
        with financial_context():
            # 0 − q × PU rather than −(q × PU): never a negative zero.
            return ZERO - self.signed_quantity * self.execution_pu


@dataclass(frozen=True, slots=True)
class LedgerEntryView:
    """An entry as the Lançamentos screen shows it: a trade with its contract's code and
    instrument type (``None`` for a cash entry)."""

    entry: LedgerEntry
    asset_code: str | None
    instrument_type_code: str | None


def validate_trade(draft: EntryDraft, *, today: date, known: bool) -> tuple[ErrorDetail, ...]:
    """Every problem of a TRADE draft but its typed quote, which is Pricing's rule. ``known`` is
    whether ``draft.asset_id`` names a contract."""
    if draft.type is not EntryType.TRADE:
        raise ValueError(f"validate_trade expects a TRADE draft, got {draft.type}")
    errors = _date_errors(draft.entry_date, today) + _time_errors(draft.entry_time)
    if draft.asset_id is None or not known:
        errors.append(unknown_asset())
    if not draft.signed_quantity:
        errors.append(
            ErrorDetail.validation(
                "A quantidade deve ser um inteiro diferente de zero.", "signed_quantity"
            )
        )
    if draft.cash_amount is not None:
        errors.append(ErrorDetail.validation("Uma operação não tem valor de caixa.", "cash_amount"))
    if draft.input_kind is None:
        errors.append(ErrorDetail.validation("Informe o PU ou a taxa.", "input_kind"))
    return tuple(errors)


def validate_cash_movement(draft: EntryDraft, *, today: date) -> tuple[ErrorDetail, ...]:
    """Every problem of a CASH draft: an aporte (positive) or a retirada (negative)."""
    if draft.type is not EntryType.CASH:
        raise ValueError(f"validate_cash_movement expects a CASH draft, got {draft.type}")
    errors = _date_errors(draft.entry_date, today) + _time_errors(draft.entry_time)
    not_cash = "Uma movimentação de caixa não tem este campo."
    for field, value in (
        ("asset_id", draft.asset_id),
        ("signed_quantity", draft.signed_quantity),
        ("input_kind", draft.input_kind),
        ("execution_pu", draft.execution_pu),
        ("execution_rate", draft.execution_rate),
    ):
        if value is not None:
            errors.append(ErrorDetail.validation(not_cash, field))
    amount = draft.cash_amount
    if amount is None:
        errors.append(ErrorDetail.validation("Informe o valor.", "cash_amount"))
    elif not fits_places(amount, CASH_PLACES):
        errors.append(
            ErrorDetail.validation(f"Use no máximo {CASH_PLACES} casas decimais.", "cash_amount")
        )
    elif amount.is_zero():
        errors.append(ErrorDetail.validation("O valor deve ser diferente de zero.", "cash_amount"))
    elif abs(amount) >= _CASH_LIMIT:
        errors.append(ErrorDetail.validation("O valor excede o limite permitido.", "cash_amount"))
    return tuple(errors)


def validate_deletion(
    requested_ids: Collection[UUID], existing_ids: Collection[UUID]
) -> tuple[ErrorDetail, ...]:
    """A batch delete names at least one entry, and only entries that exist: all or nothing
    (OQ-24), so an id that names no entry, including one already deleted, is ``NOT_FOUND`` and
    nothing is deleted. Deletion is for good (user, 2026-10-19)."""
    if not requested_ids:
        return (ErrorDetail.validation("Selecione ao menos um lançamento.", "ids"),)
    if any(entry_id not in existing_ids for entry_id in requested_ids):
        return (ErrorDetail(ErrorCode.NOT_FOUND, "Lançamento não encontrado."),)
    return ()


def _date_errors(entry_date: date, today: date) -> list[ErrorDetail]:
    return [future_date("date")] if entry_date > today else []


def _time_errors(entry_time: time) -> list[ErrorDetail]:
    # São Paulo wall time in whole seconds: the keyset cursor carries HH:MM:SS (OQ-26 item 1),
    # so a stored fraction or offset would make pages skip or repeat entries.
    if entry_time.microsecond or entry_time.tzinfo is not None:
        return [ErrorDetail.validation("Informe a hora em horas, minutos e segundos.", "time")]
    return []
