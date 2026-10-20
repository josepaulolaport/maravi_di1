"""Write the HTTP app's OpenAPI schema as JSON to stdout, with no server, database or broker.

The frontend's API types are generated from it (`npm run gen:api`; user decision, 2026-10-19):

    uv run python scripts/dump_openapi.py > ../frontend/src/api/generated/openapi.json

`create_app` reads no environment until the app starts, and `openapi()` does not start it.
"""

from __future__ import annotations

import json
import sys
import warnings

from di1.main import create_app


def schema_json() -> str:
    """The `/api` schema as committed: sorted keys, two-space indent, final newline.

    `/health` is left out: it is the container probe, not the app's API, and it registers GET
    and HEAD under one operationId, which the TypeScript generator refuses.
    """
    with warnings.catch_warnings():
        # FastAPI warns about /health's duplicate operationId; that path is dropped below.
        warnings.simplefilter("ignore")
        schema = create_app().openapi()
    schema["paths"] = {
        path: item for path, item in schema["paths"].items() if path.startswith("/api/")
    }
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    sys.stdout.write(schema_json())
