"""The business error catalogue, shared by every module (OQ-15; interfaces.md "Errors").

Domain and application code raise `DomainError` with one or more `ErrorDetail`s; it carries no
HTTP knowledge. The HTTP layer (``di1.composition.errors``) turns it into an RFC 9457
``application/problem+json`` response and owns the code → status mapping. The integrator extends
the catalogue additively.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from functools import partial


class ErrorCode(StrEnum):
    """A stable English code; the client keys its behaviour on it, never on the message."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    """Malformed or out-of-bounds input (schema CHECK rules, too many decimals: OQ-3, OQ-14)."""
    FUTURE_DATE = "FUTURE_DATE"
    """An entry or price dated after today in São Paulo (OQ-14)."""
    CONTRACT_MATURED = "CONTRACT_MATURED"
    """A trade or reference price dated after the instrument's maturity (OQ-1)."""
    NOT_FOUND = "NOT_FOUND"
    """The resource does not exist."""
    INVALID_RANGE = "INVALID_RANGE"
    """A processing or query range whose start is after its end (OQ-11), or longer than
    `MAX_RANGE_DATES`."""
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    """Cancellation requested for a job that has already finished."""


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """One problem with a request: ``message`` is pt-BR and shown to the user; ``field`` names
    the offending input (``None`` when the problem is not about one field)."""

    code: ErrorCode
    message: str
    field: str | None = None

    @classmethod
    def validation(cls, message: str, field: str | None = None) -> ErrorDetail:
        return cls(ErrorCode.VALIDATION_ERROR, message, field)


class DomainError(Exception):
    """A business rule refused the operation. Raised by domain and application code.

    All details must map to one HTTP status (all 422, say); mixing statuses is a programming
    error and answers 500. ``detail`` (pt-BR) summarises the whole problem: by default the
    message of a single detail, and ``None`` for several, which leaves the summary to the HTTP
    layer's generic text for the status.
    """

    errors: tuple[ErrorDetail, ...]
    detail: str | None

    def __init__(self, *errors: ErrorDetail, detail: str | None = None) -> None:
        if not errors:
            raise ValueError("a DomainError needs at least one ErrorDetail")
        self.errors = errors
        if detail is None and len(errors) == 1:
            detail = errors[0].message
        self.detail = detail
        super().__init__(detail if detail is not None else "; ".join(e.message for e in errors))

    def __reduce__(self) -> tuple[Callable[..., DomainError], tuple[ErrorDetail, ...]]:
        # Exception's default rebuilds from ``args`` (the summary string), which loses the details.
        return (partial(type(self), detail=self.detail), self.errors)

    @property
    def code(self) -> ErrorCode:
        """The code of the first detail, for logs and tests; the HTTP status uses every detail."""
        return self.errors[0].code


def invalid_range(field: str = "start_date") -> ErrorDetail:
    """A date range whose start is after its end (OQ-11)."""
    return ErrorDetail(
        ErrorCode.INVALID_RANGE, "A data inicial deve ser anterior ou igual à data final.", field
    )


def future_date(field: str) -> ErrorDetail:
    """A date after today in São Paulo (OQ-14)."""
    return ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", field)


def unknown_asset(field: str = "asset_id") -> ErrorDetail:
    """A body or query field naming no contract: a validation error, never ``NOT_FOUND``."""
    return ErrorDetail.validation("Selecione um contrato.", field)


def invalid_cursor() -> ErrorDetail:
    """A list cursor the API did not write (spec §12)."""
    return ErrorDetail.validation("Cursor inválido.", "cursor")


def limit_out_of_range(maximum: int) -> ErrorDetail:
    """A page size outside [1, ``maximum``] (spec §12)."""
    return ErrorDetail.validation(f"Use um limite entre 1 e {maximum}.", "limit")


MAX_RANGE_DATES = 3660
"""The most dates, both ends included (about ten years), a processing request or a P&L series
may span: a run of decades would hold the one worker for hours, and a series of decades builds
hundreds of thousands of points in memory."""


def range_too_long(start_date: date, end_date: date) -> ErrorDetail | None:
    """``INVALID_RANGE`` on ``end_date`` when [start, end] holds more than `MAX_RANGE_DATES`."""
    if (end_date - start_date).days + 1 <= MAX_RANGE_DATES:
        return None
    return ErrorDetail(
        ErrorCode.INVALID_RANGE,
        f"O período deve ter no máximo {MAX_RANGE_DATES:,} dias.".replace(",", "."),
        "end_date",
    )
