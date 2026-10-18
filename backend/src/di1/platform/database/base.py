"""The declarative base shared by the modules' ORM models.

The models mirror `docs/schema.sql`, which the migrations apply as SQL: nothing is generated from
this metadata. The type map makes the schema's types the default: `Decimal` is unbounded
`NUMERIC` returned as `Decimal` (never float; CLAUDE.md §2), `datetime` is `TIMESTAMPTZ`, and
`uuid.UUID` is the native `UUID`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, Uuid
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    type_annotation_map: dict[Any, Any] = {  # noqa: RUF012
        Decimal: Numeric(asdecimal=True),
        datetime: DateTime(timezone=True),
        uuid.UUID: Uuid(as_uuid=True),
    }
