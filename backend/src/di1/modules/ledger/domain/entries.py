"""Ledger entries: one immutable record per trade or cash movement (spec §6; OQ-24).

- A TRADE carries the contract, the signed quantity and the execution PU and rate, one of them
  typed (``input_kind``) and the other calculated by Pricing. A CASH entry carries a signed
  amount: positive aporte, negative retirada, never 0, and an optional description (challenge
  §4.2; OQ-51): trimmed, ``None`` when blank, at most 200 characters, rejected rather than cut. A
  trade has no description.
- Both have a date and a required time (São Paulo) and one ``seq`` shared by both types; their
  order is ``(entry_date, entry_time, seq)`` (OQ-13, OQ-24).
- Nothing is dated after today (OQ-14). The typed PU or rate, its decimals, its bounds and the
  maturity rules (OQ-1, OQ-3, OQ-14) are Pricing's one quote validation, which the caller passes
  in as a `QuoteRule` (``pricing.public.QuoteValidator``): domain code imports no other module.
  The other value bounds are only the schema's CHECKs and column ranges (OQ-14).
- A trade's cash effect is not stored: −signed_quantity × execution_pu, computed on read (§7.3).
- Entries are never edited. A batch delete removes entries of either type for good, all or
  nothing (OQ-24; user decision 2026-10-19: no soft delete).

Error fields are the request's field names (``date``, ``time``, ``execution_pu``, ...), which the
client keys its messages on (frontend contract ``ledger.ts``).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from di1.shared.decimals import financial_context, fits_places
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind
from di1.shared.quotes import QuoteRule

CASH_PLACES = 2
"""Decimal places of a cash amount: ``cash_amount NUMERIC(20,2)`` (OQ-3, OQ-24)."""

_CASH_LIMIT = Decimal(10) ** (20 - CASH_PLACES)
"""``NUMERIC(20,2)`` holds absolute values below 10^18."""

_INTEGER_MIN, _INTEGER_MAX = -(2**31), 2**31 - 1
"""``signed_quantity INTEGER``."""

_ZERO = Decimal(0)

DESCRIPTION_MAX_LENGTH = 200
"""``description VARCHAR(200)``: characters, as PostgreSQL counts them (OQ-51)."""


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
    description: str | None = None


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One row of ``ledger.entries``. The trade fields are set only on a TRADE and
    ``cash_amount`` only on a CASH entry (schema ``entries_trade_shape``/``entries_cash_shape``);
    ``description`` is a CASH entry's, if any (``entries_description_cash_only``, OQ-51).
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
    description: str | None = None

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
            return _ZERO - self.signed_quantity * self.execution_pu


def validate_trade(
    draft: EntryDraft,
    *,
    today: date,
    known: bool,
    maturity_date: date | None,
    validate_quote: QuoteRule,
) -> Decimal:
    """The typed quote of a valid TRADE draft, or `DomainError` with every problem found.
    ``known`` is whether ``draft.asset_id`` names a contract."""
    if draft.type is not EntryType.TRADE:
        raise ValueError(f"validate_trade expects a TRADE draft, got {draft.type}")
    errors = _date_errors(draft.entry_date, today) + _time_errors(draft.entry_time)
    if draft.asset_id is None or not known:
        errors.append(ErrorDetail.validation("Selecione um contrato.", "asset_id"))
    if (
        draft.signed_quantity is None
        or draft.signed_quantity == 0
        or not _INTEGER_MIN <= draft.signed_quantity <= _INTEGER_MAX
    ):
        errors.append(
            ErrorDetail.validation(
                "A quantidade deve ser um inteiro diferente de zero.", "signed_quantity"
            )
        )
    if draft.cash_amount is not None:
        errors.append(ErrorDetail.validation("Uma operação não tem valor de caixa.", "cash_amount"))
    if (draft.description or "").strip():  # blank is absent, as on a cash entry (OQ-51)
        errors.append(ErrorDetail.validation("Uma operação não tem descrição.", "description"))
    typed_value = None
    if draft.input_kind is None:
        errors.append(ErrorDetail.validation("Informe o PU ou a taxa.", "input_kind"))
    else:
        typed_value, quote_errors = validate_quote(
            draft.input_kind,
            pu=draft.execution_pu,
            rate=draft.execution_rate,
            reference_date=draft.entry_date,
            maturity_date=maturity_date if known else None,
        )
        errors.extend(quote_errors)
    if errors:
        raise DomainError(*errors)

    assert typed_value is not None
    return typed_value


def validate_cash_movement(draft: EntryDraft, *, today: date) -> Decimal:
    """The aporte or retirada a draft describes. Raises `DomainError` with every input error."""
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
        errors.append(_places_error(CASH_PLACES, "cash_amount"))
    elif amount.is_zero():
        errors.append(ErrorDetail.validation("O valor deve ser diferente de zero.", "cash_amount"))
    elif abs(amount) >= _CASH_LIMIT:
        errors.append(ErrorDetail.validation("O valor excede o limite permitido.", "cash_amount"))
    description = cash_description(draft)
    if description is not None and "\x00" in description:
        # PostgreSQL text cannot hold NUL (OQ-15): malformed input, as in Asset.
        errors.append(
            ErrorDetail.validation("O texto não pode conter o caractere nulo.", "description")
        )
    elif description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        errors.append(
            ErrorDetail.validation(
                f"A descrição deve ter no máximo {DESCRIPTION_MAX_LENGTH} caracteres.",
                "description",
            )
        )
    if errors:
        raise DomainError(*errors)
    assert amount is not None
    return amount


def cash_description(draft: EntryDraft) -> str | None:
    """The description a CASH draft stores (OQ-51): trimmed, ``None`` when blank, and composed
    (NFC), so the list's SQL search folds its accents as `EntrySearch` does.
    `validate_cash_movement` checks its length."""
    return unicodedata.normalize("NFC", (draft.description or "").strip()) or None


def entries_to_delete(
    requested_ids: Collection[UUID], existing_ids: Collection[UUID]
) -> tuple[UUID, ...]:
    """The entries a batch delete removes, each once, given which of ``requested_ids`` exist.
    All or nothing (OQ-24): an id that names no entry, including one already deleted, raises
    ``NOT_FOUND`` and nothing is deleted. Deletion is for good (user, 2026-10-19)."""
    if not requested_ids:
        raise DomainError(ErrorDetail.validation("Selecione ao menos um lançamento.", "ids"))
    if any(entry_id not in existing_ids for entry_id in requested_ids):
        raise DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Lançamento não encontrado."))
    return tuple(dict.fromkeys(requested_ids))


def _date_errors(entry_date: date, today: date) -> list[ErrorDetail]:
    if entry_date > today:
        return [ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "date")]
    return []


def _time_errors(entry_time: time) -> list[ErrorDetail]:
    # São Paulo wall time in whole seconds: the keyset cursor carries HH:MM:SS (OQ-26 item 1),
    # so a stored fraction or offset would make pages skip or repeat entries.
    if entry_time.microsecond or entry_time.tzinfo is not None:
        return [ErrorDetail.validation("Informe a hora em horas, minutos e segundos.", "time")]
    return []


def _places_error(places: int, field: str) -> ErrorDetail:
    return ErrorDetail.validation(f"Use no máximo {places} casas decimais.", field)
