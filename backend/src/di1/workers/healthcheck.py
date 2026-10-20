"""The health check of the worker processes (compose.yaml ``worker`` and ``outbox-relay``)::

    python -m di1.workers.healthcheck

Exits 0 when the file named by ``HEARTBEAT_FILE`` was touched within
``HEARTBEAT_MAX_AGE_SECONDS`` (`di1.platform.config.Settings`), 1 otherwise, with the reason on
stderr. It reads only that file: it opens no connection, so it is cheap to run every
few seconds and cannot itself disturb the database or the broker.
"""

from __future__ import annotations

import sys

from di1.platform.config import Settings
from di1.platform.observability.heartbeat import is_fresh


def check() -> int:
    try:
        settings = Settings()
    except ValueError as error:  # pydantic's ValidationError, which never echoes its input
        sys.stderr.write(f"unhealthy: invalid settings: {error}\n")
        return 1
    if settings.heartbeat_file is None:
        sys.stderr.write("unhealthy: HEARTBEAT_FILE is not set\n")
        return 1
    if not is_fresh(settings.heartbeat_file, max_age_seconds=settings.heartbeat_max_age_seconds):
        sys.stderr.write(
            f"unhealthy: {settings.heartbeat_file} is missing or older than"
            f" {settings.heartbeat_max_age_seconds:g} s\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(check())
