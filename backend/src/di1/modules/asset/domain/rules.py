"""Asset registration rules (spec §3; schema.sql ``asset.*``; schema.md "Application invariants").

Each check returns the problems it found as `ErrorDetail`s (empty when valid), so a service can
report every problem of a request at once. Lengths and formats are the schema's columns and CHECKs;
the hierarchy rules are the ones the schema cannot express across tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from di1.shared.errors import ErrorCode, ErrorDetail

FUTURE = "FUTURE"
"""The instrument type whose products carry an ``asset.futures`` specification."""

INSTRUMENT_TYPE_CODE_LENGTH = 32
ASSET_CLASS_CODE_LENGTH = 64
PRODUCT_CODE_LENGTH = 32
INSTRUMENT_CODE_LENGTH = 128
INSTRUMENT_TYPE_NAME_LENGTH = 100
ASSET_CLASS_NAME_LENGTH = 150
PRODUCT_NAME_LENGTH = 200
SETTLEMENT_METHOD_LENGTH = 32
SMALLINT_MAX = 32767
"""The largest instrument type or asset class id (``SMALLINT`` identities)."""

_CATALOGUE_CODE = re.compile(r"[A-Z][A-Z0-9_]*")
_PRODUCT_CODE = re.compile(r"[A-Za-z0-9_./-]+")

Errors = tuple[ErrorDetail, ...]


@dataclass(frozen=True, slots=True)
class FuturesTerms:
    """The shared specification of a futures product (``asset.futures``). The multiplier is stored
    but never applied (OQ-2)."""

    face_value: Decimal
    contract_multiplier: Decimal
    settlement_method: str
    settlement_description: str | None


def _invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)


def has_nul(text: str) -> bool:
    """PostgreSQL text cannot hold the NUL character: such input is malformed (OQ-15)."""
    return "\x00" in text


def _nul(field: str) -> ErrorDetail:
    return _invalid("O texto não pode conter o caractere nulo.", field)


def normalize_instrument_code(typed: str) -> tuple[str, Errors]:
    """The stored code: trimmed and upper-cased (OQ-33 item 1), with its problems."""
    code = typed.strip().upper()
    if not code:
        return code, (_invalid("Informe o código do contrato.", "code"),)
    if has_nul(code):
        return code, (_nul("code"),)
    if len(code) > INSTRUMENT_CODE_LENGTH:
        message = f"O código do contrato deve ter no máximo {INSTRUMENT_CODE_LENGTH} caracteres."
        return code, (_invalid(message, "code"),)
    return code, ()


def validate_catalogue_code(code: str, *, max_length: int) -> Errors:
    """An instrument type or asset class code: upper snake case (``FUTURE``)."""
    if not _CATALOGUE_CODE.fullmatch(code) or len(code) > max_length:
        message = (
            "O código deve começar por uma letra maiúscula e conter apenas letras maiúsculas, "
            f"dígitos e '_', com no máximo {max_length} caracteres."
        )
        return (_invalid(message, "code"),)
    return ()


def normalize_product_code(typed: str) -> tuple[str, Errors]:
    """The stored product code (``DI1``): trimmed and upper-cased (OQ-33 item 1), then letters,
    digits and ``_ . / -`` only, within its column."""
    trimmed = typed.strip()
    code = trimmed.upper()
    # The characters are checked before upper-casing: some non-ASCII letters upper-case into
    # ASCII ("ﬁ" → "FI"), which the schema's character set would otherwise let through.
    if not _PRODUCT_CODE.fullmatch(trimmed) or len(code) > PRODUCT_CODE_LENGTH:
        message = (
            "O código do produto deve conter apenas letras, dígitos e '_ . / -', "
            f"com no máximo {PRODUCT_CODE_LENGTH} caracteres."
        )
        return code, (_invalid(message, "code"),)
    return code, ()


def _btrim_empty(text: str) -> bool:
    """What the schema's ``length(btrim(x)) > 0`` CHECKs refuse: ``btrim`` trims spaces only."""
    return not text.strip(" ")


def validate_name(name: str, *, max_length: int, non_blank: bool = False) -> Errors:
    """A name within its column; ``non_blank`` where the schema has a ``btrim`` CHECK."""
    if non_blank and _btrim_empty(name):
        return (_invalid("Informe o nome.", "name"),)
    if has_nul(name):
        return (_nul("name"),)
    if len(name) > max_length:
        return (_invalid(f"O nome deve ter no máximo {max_length} caracteres.", "name"),)
    return ()


def validate_futures_for_type(instrument_type: str, futures: FuturesTerms | None) -> Errors:
    """A FUTURE product has exactly one futures specification; no other product has one."""
    if instrument_type != FUTURE:
        if futures is not None:
            message = "Somente produtos do tipo futuro têm especificação de futuros."
            return (_invalid(message, "futures"),)
        return ()
    if futures is None:
        return (_invalid("Informe a especificação do contrato futuro.", "futures"),)
    errors: list[ErrorDetail] = []
    # NUMERIC accepts 'Infinity', which passes the > 0 CHECKs but prices nothing.
    if not _positive(futures.face_value):
        errors.append(_invalid("O valor de face deve ser maior que zero.", "futures.face_value"))
    if not _positive(futures.contract_multiplier):
        errors.append(
            _invalid("O multiplicador deve ser maior que zero.", "futures.contract_multiplier")
        )
    method = futures.settlement_method
    if _btrim_empty(method) or len(method) > SETTLEMENT_METHOD_LENGTH:
        message = (
            f"Informe a forma de liquidação, com no máximo {SETTLEMENT_METHOD_LENGTH} caracteres."
        )
        errors.append(_invalid(message, "futures.settlement_method"))
    elif has_nul(method):
        errors.append(_nul("futures.settlement_method"))
    if futures.settlement_description is not None and has_nul(futures.settlement_description):
        errors.append(_nul("futures.settlement_description"))
    return tuple(errors)


def _positive(value: Decimal) -> bool:
    return value.is_finite() and value > 0


def validate_maturity(instrument_type: str, maturity_date: date | None) -> Errors:
    """A futures contract has its own maturity (spec §3); other types do not require one."""
    if instrument_type == FUTURE and maturity_date is None:
        return (_invalid("Informe o vencimento.", "maturity_date"),)
    return ()
