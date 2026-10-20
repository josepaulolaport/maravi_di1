"""The frontend's API types are generated from the committed OpenAPI schema (user, 2026-10-19).

The schema the app serves must equal ``frontend/src/api/generated/openapi.json``; after an HTTP
change, run ``npm run gen:api`` in ``frontend/`` and commit both generated files.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "backend" / "scripts" / "dump_openapi.py"
COMMITTED = REPO / "frontend" / "src" / "api" / "generated" / "openapi.json"


def test_the_committed_openapi_schema_is_the_apps() -> None:
    spec = importlib.util.spec_from_file_location("dump_openapi", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.schema_json() == COMMITTED.read_text(encoding="utf-8"), (
        "frontend/src/api/generated/openapi.json is out of date: run `npm run gen:api` in frontend/"
    )
