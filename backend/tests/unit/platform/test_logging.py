"""Logging is configured once per process, with the stdlib only, from ``LOG_LEVEL``.

backend/CLAUDE.md "Logging" (stdlib `logging`, configuration set once at process startup, each
module logs through its own ``logging.getLogger(__name__)``, no prints and no secrets).
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Iterator

import pytest

from di1.platform.observability.logging_setup import configure_logging

LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (?P<level>[A-Z]+) (?P<name>\S+) (?P<msg>.*)$"
)


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def _configure(level: str = "INFO") -> io.StringIO:
    stream = io.StringIO()
    configure_logging(level, stream=stream)  # type: ignore[arg-type]
    return stream


def test_a_module_logger_writes_one_line_with_time_level_and_name() -> None:
    stream = _configure()

    logging.getLogger("di1.modules.example").info("saved %s", "trade")

    [line] = stream.getvalue().splitlines()
    match = LINE.match(line)
    assert match is not None, line
    assert match.group("level", "name", "msg") == ("INFO", "di1.modules.example", "saved trade")


def test_messages_below_the_level_are_dropped() -> None:
    stream = _configure("WARNING")

    logging.getLogger("di1.x").info("hidden")
    logging.getLogger("di1.x").warning("shown")

    assert [LINE.match(line).group("msg") for line in stream.getvalue().splitlines()] == [  # type: ignore[union-attr]
        "shown"
    ]


def test_configuring_twice_keeps_one_handler_and_the_new_level() -> None:
    _configure("INFO")
    stream = _configure("ERROR")

    logging.getLogger("di1.x").warning("hidden")
    logging.getLogger("di1.x").error("shown")

    assert stream.getvalue().count("\n") == 1
    assert logging.getLogger().level == logging.ERROR


def test_handlers_it_did_not_add_are_kept() -> None:
    """A test runner's or a server's own handlers stay in place."""
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)

    _configure()

    assert other in logging.getLogger().handlers


def test_loggers_created_before_the_configuration_still_log() -> None:
    early = logging.getLogger("di1.created.at.import")

    stream = _configure()
    early.info("still here")

    assert "still here" in stream.getvalue()


def test_an_exception_is_logged_with_its_traceback() -> None:
    stream = _configure()

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("di1.x").exception("failed")

    output = stream.getvalue()
    assert "ERROR di1.x failed" in output
    assert "Traceback (most recent call last)" in output
    assert "RuntimeError: boom" in output
