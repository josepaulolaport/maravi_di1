"""Asset registration rules (spec §3; schema.sql ``asset.*``; schema.md "Application invariants").

Each check returns the problems it found as `ErrorDetail`s (empty when valid), so the service can
report every problem of a request at once. Lengths and formats are the schema's columns and CHECKs;
the hierarchy rules are the ones the schema cannot express across tables.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from di1.modules.asset.domain.model import FuturesTerms
from di1.shared.errors import ErrorDetail

FUTURE = "FUTURE"
"""The instrument type whose products carry an ``asset.futures`` specification."""

PRODUCT_CODE_LENGTH = 32
INSTRUMENT_CODE_LENGTH = 128
PRODUCT_NAME_LENGTH = 200
SETTLEMENT_METHOD_LENGTH = 32
SMALLINT_MAX = 32767
"""The largest instrument type or asset class id (``SMALLINT`` identities)."""

_PRODUCT_CODE = re.compile(r"[A-Za-z0-9_./-]+")


def has_nul(text: str) -> bool:
    """PostgreSQL text cannot hold the NUL character: such input is malformed (OQ-15)."""
    return "\x00" in text


def _nul(field: str) -> ErrorDetail:
    return ErrorDetail.validation("O texto não pode conter o caractere nulo.", field)


def normalize_code(typed: str) -> str:
    """A product or instrument code as stored: trimmed and upper-cased (OQ-33 item 1)."""
    return typed.strip().upper()


def validate_instrument_code(code: str) -> tuple[ErrorDetail, ...]:
    """A normalized instrument code (`normalize_code`): present, without NUL, within its column."""
    if not code:
        return (ErrorDetail.validation("Informe o código do contrato.", "code"),)
    if has_nul(code):
        return (_nul("code"),)
    if len(code) > INSTRUMENT_CODE_LENGTH:
        message = f"O código do contrato deve ter no máximo {INSTRUMENT_CODE_LENGTH} caracteres."
        return (ErrorDetail.validation(message, "code"),)
    return ()


def validate_product_code(typed: str) -> tuple[ErrorDetail, ...]:
    """A product code as typed (``DI1``): letters, digits and ``_ . / -`` only, within its column
    once normalized."""
    trimmed = typed.strip()
    # The characters are checked before upper-casing: some non-ASCII letters upper-case into
    # ASCII ("ﬁ" → "FI"), which the schema's character set would otherwise let through.
    if not _PRODUCT_CODE.fullmatch(trimmed) or len(trimmed.upper()) > PRODUCT_CODE_LENGTH:
        message = (
            "O código do produto deve conter apenas letras, dígitos e '_ . / -', "
            f"com no máximo {PRODUCT_CODE_LENGTH} caracteres."
        )
        return (ErrorDetail.validation(message, "code"),)
    return ()


def _btrim_empty(text: str) -> bool:
    """What the schema's ``length(btrim(x)) > 0`` CHECKs refuse: ``btrim`` trims spaces only."""
    return not text.strip(" ")


def validate_name(
    name: str, *, max_length: int, non_blank: bool = False
) -> tuple[ErrorDetail, ...]:
    """A name within its column; ``non_blank`` where the schema has a ``btrim`` CHECK."""
    if non_blank and _btrim_empty(name):
        return (ErrorDetail.validation("Informe o nome.", "name"),)
    if has_nul(name):
        return (_nul("name"),)
    if len(name) > max_length:
        return (
            ErrorDetail.validation(f"O nome deve ter no máximo {max_length} caracteres.", "name"),
        )
    return ()


def validate_futures_for_type(
    instrument_type: str, futures: FuturesTerms | None
) -> tuple[ErrorDetail, ...]:
    """A FUTURE product has exactly one futures specification; no other product has one."""
    if instrument_type != FUTURE:
        if futures is not None:
            message = "Somente produtos do tipo futuro têm especificação de futuros."
            return (ErrorDetail.validation(message, "futures"),)
        return ()
    if futures is None:
        return (ErrorDetail.validation("Informe a especificação do contrato futuro.", "futures"),)
    errors: list[ErrorDetail] = []
    # NUMERIC accepts 'Infinity', which passes the > 0 CHECKs but prices nothing.
    if not _positive(futures.face_value):
        errors.append(
            ErrorDetail.validation("O valor de face deve ser maior que zero.", "futures.face_value")
        )
    if not _positive(futures.contract_multiplier):
        errors.append(
            ErrorDetail.validation(
                "O multiplicador deve ser maior que zero.", "futures.contract_multiplier"
            )
        )
    method = futures.settlement_method
    if _btrim_empty(method) or len(method) > SETTLEMENT_METHOD_LENGTH:
        message = (
            f"Informe a forma de liquidação, com no máximo {SETTLEMENT_METHOD_LENGTH} caracteres."
        )
        errors.append(ErrorDetail.validation(message, "futures.settlement_method"))
    elif has_nul(method):
        errors.append(_nul("futures.settlement_method"))
    if futures.settlement_description is not None and has_nul(futures.settlement_description):
        errors.append(_nul("futures.settlement_description"))
    return tuple(errors)


def _positive(value: Decimal) -> bool:
    return value.is_finite() and value > 0


def validate_maturity(instrument_type: str, maturity_date: date | None) -> tuple[ErrorDetail, ...]:
    """A futures contract has its own maturity (spec §3); other types do not require one."""
    if instrument_type == FUTURE and maturity_date is None:
        return (ErrorDetail.validation("Informe o vencimento.", "maturity_date"),)
    return ()
