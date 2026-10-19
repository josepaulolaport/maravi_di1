"""Logging setup: the stdlib `logging` module, configured once at each process's startup.

backend/CLAUDE.md "Logging": every module logs through its own
``logger = logging.getLogger(__name__)``; only the entry points (the API's startup and each
worker's ``main``) call `configure_logging`. Records go to standard error, where Docker
collects them, each starting on a new line with an ISO-8601 UTC time, the level and the logger
name, then the message; a multi-line message or an exception's traceback continues on the
following lines. Secrets never reach a record: settings hold them as
`SecretStr`, and aio-pika masks the password in its connection URLs.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import TextIO

from di1.platform.config import LoggingSettings

_HANDLER_NAME = "di1"
"""Marks the handler this module adds, so a second call replaces it instead of adding one."""

_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(settings: LoggingSettings, *, stream: TextIO | None = None) -> None:
    """Send every record at ``settings.log_level`` or above to ``stream`` (standard error).

    Handlers added by others (a test runner, a server) are left in place; calling it again
    replaces only its own handler and the level.
    """
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    formatter.converter = time.gmtime
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)
        existing.close()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
