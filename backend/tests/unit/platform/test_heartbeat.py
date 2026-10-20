"""The heartbeat file a worker process touches while its loop runs, and its freshness check
(compose.yaml health checks of ``worker`` and ``outbox-relay``)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from di1.platform.observability.heartbeat import Heartbeat, beat_until_stopped, is_fresh
from tests.support.waits import eventually


def test_a_beat_creates_the_file_then_refreshes_it(tmp_path: Path) -> None:
    path = tmp_path / "worker.heartbeat"
    heartbeat = Heartbeat(path)

    heartbeat.beat()
    os.utime(path, (1000.0, 1000.0))
    heartbeat.beat()

    assert path.stat().st_mtime > 1000.0


def test_clearing_removes_the_file_and_tolerates_none(tmp_path: Path) -> None:
    path = tmp_path / "worker.heartbeat"
    path.touch()
    heartbeat = Heartbeat(path)

    heartbeat.clear()
    heartbeat.clear()

    assert not path.exists()


def test_a_failed_beat_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    Heartbeat(tmp_path / "missing-directory" / "worker.heartbeat").beat()

    assert "heartbeat file could not be written" in caplog.text


@pytest.mark.parametrize(("age", "fresh"), [(0.0, True), (29.9, True), (30.1, False)])
def test_a_heartbeat_is_fresh_within_its_maximum_age(
    tmp_path: Path, age: float, fresh: bool
) -> None:
    path = tmp_path / "worker.heartbeat"
    path.touch()
    os.utime(path, (1000.0, 1000.0))

    assert is_fresh(path, max_age_seconds=30, now=1000.0 + age) is fresh


def test_a_missing_heartbeat_is_not_fresh(tmp_path: Path) -> None:
    assert not is_fresh(tmp_path / "never-written", max_age_seconds=30)


async def test_the_beat_task_beats_until_stopped(tmp_path: Path) -> None:
    path = tmp_path / "worker.heartbeat"
    stop = asyncio.Event()
    beating = asyncio.create_task(beat_until_stopped(Heartbeat(path), stop, interval_seconds=0.01))

    await eventually(path.exists)
    os.utime(path, (1000.0, 1000.0))
    await eventually(lambda: path.stat().st_mtime > 1000.0)
    stop.set()
    await asyncio.wait_for(beating, timeout=5)
