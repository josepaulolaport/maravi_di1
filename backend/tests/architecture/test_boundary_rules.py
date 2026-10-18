"""The import-boundary checker flags each forbidden import and accepts the allowed ones.

Rules: CLAUDE.md §3, backend/CLAUDE.md, plan §0-§1 and interfaces.md "Scope and structural
rules" / "DI composition". Each rule is proven on a small synthetic source tree, and every
assertion checks the exact set of rules reported, so a false positive is caught too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture.boundaries import find_violations


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Write `files` (path relative to the `di1` package → source) under `root/di1`."""
    package = root / "di1"
    for relative, source in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return package


def _rules(package: Path) -> set[str]:
    return {violation.split(":", 1)[0] for violation in find_violations(package)}


def _rules_for(tmp_path: Path, path: str, source: str) -> set[str]:
    return _rules(_tree(tmp_path, {path: source}))


APP = "modules/ledger/application/services/ledger.py"
DOMAIN = "modules/ledger/domain/rules.py"
INFRA = "modules/ledger/infrastructure/persistence/repositories.py"
HTTP = "modules/ledger/presentation/http/router.py"
PUBLIC = "modules/ledger/public.py"
WORKER = "workers/main.py"
CONSUMER = "modules/processing/presentation/messaging/handlers.py"


# ---------------------------------------------------------------- allowed imports


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    package = _tree(
        tmp_path,
        {
            DOMAIN: "import decimal\nfrom di1.shared import money\nfrom . import other\n",
            APP: (
                "from typing import TYPE_CHECKING\n"
                "from di1.modules.asset.public import AssetReader\n"
                "from di1.modules.asset import public\n"
                "import di1.modules.prices.public as prices_public\n"
                "from ...domain import rules\n"
                "from di1.platform.database import unit_of_work\n"
                "from di1.platform.messaging.outbox import OutboxWriter\n"
            ),
            "modules/ledger/infrastructure/persistence/models.py": "import sqlalchemy\n",
            "modules/prices/infrastructure/b3/client.py": "import decimal\n",
            "modules/processing/infrastructure/messaging/outbox.py": (
                "from di1.platform.messaging.outbox import OutboxWriter\n"
            ),
            CONSUMER: (
                "from di1.platform.messaging.consumer import Handler\n"
                "from di1.platform.messaging.envelope import Envelope\n"
                "from di1.platform.messaging.inbox import Inbox\n"
                "from ...application.services.processing import ProcessingService\n"
            ),
            HTTP: "from fastapi import APIRouter\n",
            "modules/ledger/presentation/http/schemas.py": "from pydantic import BaseModel\n",
            "modules/ledger/dependencies.py": "from fastapi import Depends\nimport sqlalchemy\n",
            PUBLIC: "from .domain.rules import Rule\nfrom .application.services import ledger\n",
            "modules/ledger/__init__.py": '"""Ledger."""\nfrom __future__ import annotations\n',
            "platform/messaging/connection.py": "import aio_pika\nimport sqlalchemy\n",
            "platform/config.py": "from pydantic_settings import BaseSettings\n",
            "composition/routers.py": "from fastapi import FastAPI\nfrom di1.workers import x\n",
            WORKER: (
                "from di1.composition import consumers\n"
                "from di1.composition.consumers import register\n"
                "from di1.platform.messaging import consumer\n"
                "from di1.modules.processing.public import ProcessingService\n"
            ),
            "main.py": "from di1.composition import routers\n",
        },
    )
    assert find_violations(package) == []


# ---------------------------------------------------------------- cross-module access


@pytest.mark.parametrize(
    "source",
    [
        "from di1.modules.asset.infrastructure.persistence import repositories\n",
        "from ....asset.domain import x\n",
        "from di1.modules import asset\n",
        "import di1.modules.asset\n",
        "from di1.modules.asset import infrastructure\n",
        "from di1.modules.asset import AssetReader\n",
        "import di1.modules.asset.domain as asset_domain\n",
        (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from di1.modules.asset import domain\n"
        ),
    ],
)
def test_other_modules_are_reached_only_through_public(tmp_path: Path, source: str) -> None:
    assert _rules_for(tmp_path, APP, source) == {"cross-module"}


def test_module_init_contains_no_imports(tmp_path: Path) -> None:
    assert _rules_for(tmp_path, "modules/asset/__init__.py", "from . import infrastructure\n") == {
        "module-init"
    }


# ---------------------------------------------------------------- layers


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # external dependencies and other layers
        ("import sqlalchemy\n", {"domain-purity", "sql"}),
        ("from pydantic import BaseModel\n", {"domain-purity", "pydantic"}),
        ("from di1.platform.database import engine\n", {"domain-purity"}),
        ("from di1.modules.ledger.infrastructure import models\n", {"domain-purity"}),
        # filesystem, network, database, environment and concurrency modules
        ("import os\n", {"domain-purity"}),
        ("from pathlib import Path\n", {"domain-purity"}),
        ("import socket\n", {"domain-purity"}),
        ("from urllib import request\n", {"domain-purity"}),
        ("import sqlite3\n", {"domain-purity"}),
        ("import asyncio\n", {"domain-purity"}),
        ("import subprocess\n", {"domain-purity"}),
        ("import logging\n", {"domain-purity"}),
        ("import secrets\n", {"domain-purity"}),
        # side-effecting calls inside otherwise pure modules
        ("from datetime import datetime\nnow = datetime.now()\n", {"domain-purity"}),
        ("import datetime\ntoday = datetime.date.today()\n", {"domain-purity"}),
        ("from datetime import date as d\ntoday = d.today()\n", {"domain-purity"}),
        ("import time\nstarted = time.monotonic()\n", {"domain-purity"}),
        ("from time import time\nstarted = time()\n", {"domain-purity"}),
        ("import uuid\nnew_id = uuid.uuid4()\n", {"domain-purity"}),
        ("data = open('prices.csv').read()\n", {"domain-purity"}),
        ("print('debug')\n", {"domain-purity"}),
        # randomness generated internally (no explicit seed or injected generator)
        ("import random\nx = random.random()\n", {"domain-purity"}),
        ("from random import randint\nroll = randint(1, 6)\n", {"domain-purity"}),
        ("import random\nrandom.seed(42)\n", {"domain-purity"}),
        ("import random\nrng = random.Random()\n", {"domain-purity"}),
        ("from random import SystemRandom\nrng = SystemRandom(42)\n", {"domain-purity"}),
    ],
)
def test_domain_has_no_io_or_side_effects(tmp_path: Path, source: str, expected: set[str]) -> None:
    assert _rules_for(tmp_path, DOMAIN, source) == expected


def test_domain_may_use_pure_standard_library(tmp_path: Path) -> None:
    source = (
        "import time\n"
        "import uuid\n"
        "from dataclasses import dataclass\n"
        "from datetime import date, datetime, timedelta\n"
        "from decimal import ROUND_HALF_UP, Decimal, localcontext\n"
        "from enum import StrEnum\n"
        "maturity = date(2028, 1, 1) - timedelta(days=365)\n"
        "stamp = datetime.fromisoformat('2027-01-01T10:00:00')\n"
        "asset_id = uuid.UUID('6ad8f84a-7cb3-46d1-a737-0360bf1d754f')\n"
        "label = time.strftime('%Y', (2027, 1, 1, 0, 0, 0, 0, 1, 0))\n"
        "pu = Decimal('100000') / Decimal('1.1')\n"
    )
    assert _rules_for(tmp_path, DOMAIN, source) == set()


def test_domain_may_use_a_seeded_or_injected_random_generator(tmp_path: Path) -> None:
    source = (
        "import random\n"
        "from random import Random\n"
        "def simulate(paths: int, rng: random.Random) -> list[float]:\n"
        "    return [rng.gauss(0.0, 1.0) for _ in range(paths)]\n"
        "def reproducible(seed: int) -> float:\n"
        "    return Random(seed).random()\n"
        "fixed = random.Random(42)\n"
    )
    assert _rules_for(tmp_path, DOMAIN, source) == set()


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (APP, "from di1.modules.ledger.presentation.http.schemas import TradeIn\n"),
        (APP, "from ...infrastructure.persistence import repositories\n"),
        (INFRA, "from di1.modules.ledger.presentation.http import schemas\n"),
        (PUBLIC, "from .infrastructure.persistence.repositories import LedgerRepository\n"),
        (PUBLIC, "from .presentation.http.schemas import TradeIn\n"),
        (HTTP, "from ...infrastructure.persistence import repositories\n"),
        (CONSUMER, "from di1.modules.processing.infrastructure.persistence import repositories\n"),
    ],
)
def test_layers_point_inwards(tmp_path: Path, path: str, source: str) -> None:
    assert _rules_for(tmp_path, path, source) == {"layering"}


# ---------------------------------------------------------------- frameworks and libraries


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (APP, {"fastapi"}),
        (DOMAIN, {"domain-purity", "fastapi"}),
        (INFRA, {"fastapi"}),
        (PUBLIC, {"fastapi"}),
        ("platform/database/session.py", {"fastapi"}),
        (WORKER, {"fastapi"}),
    ],
)
def test_fastapi_only_in_http_adapters_providers_and_composition(
    tmp_path: Path, path: str, expected: set[str]
) -> None:
    assert _rules_for(tmp_path, path, "from fastapi import Depends\n") == expected


@pytest.mark.parametrize("path", [APP, HTTP, PUBLIC])
def test_sql_only_in_infrastructure_platform_and_wiring(tmp_path: Path, path: str) -> None:
    assert _rules_for(tmp_path, path, "from sqlalchemy import select\n") == {"sql"}


@pytest.mark.parametrize("path", [APP, PUBLIC, INFRA, "shared/dto.py"])
def test_pydantic_only_in_presentation_and_platform(tmp_path: Path, path: str) -> None:
    assert _rules_for(tmp_path, path, "from pydantic import BaseModel\n") == {"pydantic"}


@pytest.mark.parametrize(
    "source",
    [
        "import aio_pika\n",
        "from di1.platform.messaging.publisher import Publisher\n",
        "from di1.platform.messaging import connection\n",
        "from di1.platform.messaging.topology import declare\n",
    ],
)
def test_business_code_uses_only_outbox_and_inbox_messaging(tmp_path: Path, source: str) -> None:
    assert _rules_for(tmp_path, INFRA, source) == {"messaging"}


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (APP, "from di1.platform.messaging.consumer import Handler\n"),
        (INFRA, "from di1.platform.messaging.consumer import Handler\n"),
        (CONSUMER, "import aio_pika\n"),
        (CONSUMER, "from di1.platform.messaging.publisher import Publisher\n"),
    ],
)
def test_only_presentation_messaging_consumes_and_never_touches_the_broker(
    tmp_path: Path, path: str, source: str
) -> None:
    assert _rules_for(tmp_path, path, source) == {"messaging"}


@pytest.mark.parametrize("path", ["platform/config.py", "shared/money.py"])
def test_platform_and_contracts_do_not_depend_on_modules(tmp_path: Path, path: str) -> None:
    source = "from di1.modules.ledger.public import LedgerReader\n"
    assert _rules_for(tmp_path, path, source) == {"shared-independent"}


# ---------------------------------------------------------------- entry points and workers


def test_only_entry_points_import_composition(tmp_path: Path) -> None:
    package = _tree(tmp_path, {HTTP: "from di1.composition import routers\n"})
    assert find_violations(package) == [
        "entry-point: modules/ledger/presentation/http/router.py imports di1.composition"
    ]


@pytest.mark.parametrize("path", [APP, "platform/messaging/consumer.py"])
def test_workers_are_not_imported_by_business_or_platform_code(tmp_path: Path, path: str) -> None:
    assert _rules_for(tmp_path, path, "from di1.workers import dispatcher\n") == {"entry-point"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from di1.main import app\n", {"entry-point"}),
        ("from di1.composition.routers import api_router\n", {"entry-point"}),
        ("from di1.composition.dependencies import get_uow\n", {"entry-point"}),
        ("from di1.modules.ledger.dependencies import provide\n", {"cross-module"}),
        (
            "from di1.modules.processing.infrastructure.persistence.repositories import R\n",
            {"cross-module"},
        ),
    ],
)
def test_workers_use_plain_factories_and_public_contracts(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    assert _rules_for(tmp_path, WORKER, source) == expected


# ---------------------------------------------------------------- bypasses and layout


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nimportlib.import_module('di1.modules.asset.domain')\n",
        "from importlib import import_module\nimport_module('sqlalchemy')\n",
        "__import__('sqlalchemy')\n",
    ],
)
def test_dynamic_imports_are_forbidden(tmp_path: Path, source: str) -> None:
    assert _rules_for(tmp_path, APP, source) == {"dynamic-import"}


@pytest.mark.parametrize(
    "path",
    [
        "helpers.py",
        "modules/ledger/services/ledger.py",
        "modules/ledger/utils.py",
        "modules/ledger/presentation/cli/main.py",
        "modules/ledger/application/helpers/x.py",
    ],
)
def test_files_outside_the_plan_layout_are_reported(tmp_path: Path, path: str) -> None:
    package = _tree(tmp_path, {path: "import decimal\n"})
    assert find_violations(package) == [f"layout: {path} is outside the plan §1 layout"]
