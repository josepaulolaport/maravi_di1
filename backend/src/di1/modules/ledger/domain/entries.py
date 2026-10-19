"""Ledger entries: one immutable record per trade or cash movement (spec §6; OQ-24).

- A TRADE carries the contract, the signed quantity and the execution PU and rate, one of them
  typed (``input_kind``) and the other calculated by Pricing. A CASH entry carries a signed
  amount: positive aporte, negative retirada, never 0.
- Both have a date and a required time (São Paulo) and one ``seq`` shared by both types; their
  order is ``(entry_date, entry_time, seq)`` (OQ-13, OQ-24).
- Nothing is dated after today (OQ-14); a trade may be dated up to its contract's maturity,
  inclusive, and on that date the PU is typed (OQ-1). Typed values with more decimal places than
  stored are rejected, never rounded (OQ-3). The value bounds are only the schema's CHECKs and
  column ranges (OQ-14).
- A trade's cash effect is not stored: −signed_quantity × execution_pu, computed on read (§7.3).
- Entries are never edited; a batch soft delete shares one ``deletion_batch_id`` and is all or
  nothing (OQ-24).

Error fields are the request's field names (``date``, ``time``, ``execution_pu``, ...), which the
client keys its messages on (frontend contract ``ledger.ts``).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from di1.shared.decimals import PU_PLACES, RATE_PLACES, financial_context, fits_places
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

CASH_PLACES = 2
"""Decimal places of a cash amount: ``cash_amount NUMERIC(20,2)`` (OQ-3, OQ-24)."""

_CASH_LIMIT = Decimal(10) ** (20 - CASH_PLACES)
"""``NUMERIC(20,2)`` holds absolute values below 10^18."""

_INTEGER_MIN, _INTEGER_MAX = -(2**31), 2**31 - 1
"""``signed_quantity INTEGER``."""

_ZERO = Decimal(0)


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
class KnownInstrument:
    """What validation needs to know about an existing contract."""

    maturity_date: date | None


@dataclass(frozen=True, slots=True)
class NewTrade:
    """A valid trade, before pricing: ``typed_value`` is the PU or the rate, as typed."""

    asset_id: UUID
    entry_date: date
    entry_time: time
    signed_quantity: int
    input_kind: InputKind
    typed_value: Decimal


@dataclass(frozen=True, slots=True)
class NewCashMovement:
    """A valid aporte (positive ``amount``) or retirada (negative)."""

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
    deleted_at: datetime | None = None

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order across both types (OQ-13, OQ-24)."""
        return (self.entry_date, self.entry_time, self.seq)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

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
            return _ZERO - self.signed_quantity * self.execution_pu


@dataclass(frozen=True, slots=True)
class DeletionPlan:
    """What a batch soft delete changes: the entries still active among those requested, and
    the date each chain is stale from (``None`` when the batch does not touch it, or when the
    other call already covers it)."""

    entry_ids: tuple[UUID, ...]
    trades_from: date | None
    cash_movements_from: date | None


def validate_trade(
    draft: EntryDraft, *, today: date, instrument: KnownInstrument | None
) -> NewTrade:
    """The trade a draft describes; ``instrument`` is ``None`` when ``draft.asset_id`` names no
    contract. Raises `DomainError` with every input error, then with the maturity error."""
    if draft.type is not EntryType.TRADE:
        raise ValueError(f"validate_trade expects a TRADE draft, got {draft.type}")
    errors = _date_errors(draft.entry_date, today)
    if draft.asset_id is None or instrument is None:
        errors.append(_invalid("Selecione um contrato.", "asset_id"))
    if (
        draft.signed_quantity is None
        or draft.signed_quantity == 0
        or not _INTEGER_MIN <= draft.signed_quantity <= _INTEGER_MAX
    ):
        errors.append(
            _invalid("A quantidade deve ser um inteiro diferente de zero.", "signed_quantity")
        )
    if draft.cash_amount is not None:
        errors.append(_invalid("Uma operação não tem valor de caixa.", "cash_amount"))
    typed_value, quote_errors = _typed_quote(draft)
    errors.extend(quote_errors)
    if errors:
        raise DomainError(*errors)

    assert draft.asset_id is not None and instrument is not None
    assert draft.signed_quantity is not None and draft.input_kind is not None
    assert typed_value is not None
    maturity = instrument.maturity_date
    if maturity is not None and draft.entry_date > maturity:
        raise DomainError(
            ErrorDetail(ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "date")
        )
    if draft.entry_date == maturity and draft.input_kind is InputKind.RATE:
        raise DomainError(_invalid("Na data de vencimento informe o PU.", "execution_rate"))
    return NewTrade(
        asset_id=draft.asset_id,
        entry_date=draft.entry_date,
        entry_time=draft.entry_time,
        signed_quantity=draft.signed_quantity,
        input_kind=draft.input_kind,
        typed_value=typed_value,
    )


def validate_cash_movement(draft: EntryDraft, *, today: date) -> NewCashMovement:
    """The aporte or retirada a draft describes. Raises `DomainError` with every input error."""
    if draft.type is not EntryType.CASH:
        raise ValueError(f"validate_cash_movement expects a CASH draft, got {draft.type}")
    errors = _date_errors(draft.entry_date, today)
    not_cash = "Uma movimentação de caixa não tem este campo."
    for field, value in (
        ("asset_id", draft.asset_id),
        ("signed_quantity", draft.signed_quantity),
        ("input_kind", draft.input_kind),
        ("execution_pu", draft.execution_pu),
        ("execution_rate", draft.execution_rate),
    ):
        if value is not None:
            errors.append(_invalid(not_cash, field))
    amount = draft.cash_amount
    if amount is None:
        errors.append(_invalid("Informe o valor.", "cash_amount"))
    elif not fits_places(amount, CASH_PLACES):
        errors.append(_places_error(CASH_PLACES, "cash_amount"))
    elif amount.is_zero():
        errors.append(_invalid("O valor deve ser diferente de zero.", "cash_amount"))
    elif abs(amount) >= _CASH_LIMIT:
        errors.append(_invalid("O valor excede o limite permitido.", "cash_amount"))
    if errors:
        raise DomainError(*errors)
    assert amount is not None
    return NewCashMovement(entry_date=draft.entry_date, entry_time=draft.entry_time, amount=amount)


def plan_deletion(requested_ids: Collection[UUID], found: Sequence[LedgerEntry]) -> DeletionPlan:
    """The batch soft delete of ``requested_ids``, given the entries found for them (deleted or
    not). All or nothing: an id that names no entry raises ``NOT_FOUND`` and nothing is deleted.
    An entry already deleted keeps its deletion and invalidates nothing (idempotent).

    Each chain is invalidated from its earliest date (OQ-24): positions from the earliest trade
    (``trades_changed`` marks cash too); cash from the earliest entry of either type, so a
    separate ``cash_movements_changed`` is needed only for cash dated before every trade. Then
    the cash dates from the earliest trade on are marked by both calls: with the invalidator's
    two methods that repeat cannot be avoided, and marking STALE twice changes nothing.
    """
    if not requested_ids:
        raise DomainError(_invalid("Selecione ao menos um lançamento.", "ids"))
    by_id = {entry.id: entry for entry in found}
    if any(entry_id not in by_id for entry_id in requested_ids):
        raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Lançamento não encontrado."))

    active = [by_id[entry_id] for entry_id in dict.fromkeys(requested_ids)]
    active = [entry for entry in active if not entry.is_deleted]
    trade_dates = [e.entry_date for e in active if e.type is EntryType.TRADE]
    cash_dates = [e.entry_date for e in active if e.type is EntryType.CASH]
    trades_from = min(trade_dates, default=None)
    cash_from = min(cash_dates, default=None)
    if cash_from is not None and trades_from is not None and cash_from >= trades_from:
        cash_from = None
    return DeletionPlan(
        entry_ids=tuple(entry.id for entry in active),
        trades_from=trades_from,
        cash_movements_from=cash_from,
    )


def _typed_quote(draft: EntryDraft) -> tuple[Decimal | None, list[ErrorDetail]]:
    kind = draft.input_kind
    if kind is None:
        return None, [_invalid("Informe o PU ou a taxa.", "input_kind")]
    if kind is InputKind.PU:
        typed, typed_field, other, other_field = (
            draft.execution_pu,
            "execution_pu",
            draft.execution_rate,
            "execution_rate",
        )
    else:
        typed, typed_field, other, other_field = (
            draft.execution_rate,
            "execution_rate",
            draft.execution_pu,
            "execution_pu",
        )
    errors: list[ErrorDetail] = []
    if other is not None:
        errors.append(_invalid("Informe apenas o PU ou a taxa, não os dois.", other_field))
    if typed is None:
        missing = "Informe o PU." if kind is InputKind.PU else "Informe a taxa."
        errors.append(_invalid(missing, typed_field))
        return None, errors
    places = PU_PLACES if kind is InputKind.PU else RATE_PLACES
    if not typed.is_finite():
        errors.append(_invalid("Informe um número válido.", typed_field))
    elif not fits_places(typed, places):
        errors.append(_places_error(places, typed_field))
    elif kind is InputKind.PU and typed <= 0:
        errors.append(_invalid("O PU deve ser maior que zero.", typed_field))
    elif kind is InputKind.RATE and typed <= -1:
        errors.append(_invalid("A taxa deve ser maior que −100%.", typed_field))
    return (typed if not errors else None), errors


def _date_errors(entry_date: date, today: date) -> list[ErrorDetail]:
    if entry_date > today:
        return [ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "date")]
    return []


def _places_error(places: int, field: str) -> ErrorDetail:
    return _invalid(f"Use no máximo {places} casas decimais.", field)


def _invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)
