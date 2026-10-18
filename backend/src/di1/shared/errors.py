"""The business error catalogue, shared by every module (OQ-15; interfaces.md "Errors").

Domain and application code raise `DomainError` with one or more `ErrorDetail`s; it carries no
HTTP knowledge. The HTTP layer (``di1.composition.errors``) turns it into an RFC 9457
``application/problem+json`` response and owns the code → status mapping. The integrator extends
the catalogue additively.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    """A processing or query range whose start is after its end (OQ-11)."""
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    """Cancellation requested for a job that has already finished."""


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """One problem with a request: ``message`` is pt-BR and shown to the user; ``field`` names
    the offending input (``None`` when the problem is not about one field)."""

    code: ErrorCode
    message: str
    field: str | None = None


class DomainError(Exception):
    """A business rule refused the operation. Raised by domain and application code.

    ``detail`` (pt-BR) summarises the whole problem and defaults to the first message. The first
    detail's code decides the HTTP status, so raise details of one kind together.
    """

    errors: tuple[ErrorDetail, ...]
    detail: str

    def __init__(self, *errors: ErrorDetail, detail: str | None = None) -> None:
        if not errors:
            raise ValueError("a DomainError needs at least one ErrorDetail")
        self.errors = errors
        self.detail = detail if detail is not None else errors[0].message
        super().__init__(self.detail)

    @property
    def code(self) -> ErrorCode:
        """The code of the first detail."""
        return self.errors[0].code
