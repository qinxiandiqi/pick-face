"""Tests for service.polling_scheduler — APScheduler interval job.

Covers M8-T-2 (`docs/06 §3.1`): the polling scheduler is a fallback
for environments where watchdog events don't fire (Docker bind mounts,
NFS, FUSE). It calls ``ScanService.start(paths=None, kind='path_only')``
on every tick at ``[scan] incremental_interval_sec``.

Test strategy: override ``incremental_interval_sec=1`` so the suite
finishes in ~3s. Monkeypatch ``ScanService.start`` so we can count
ticks deterministically.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def _write_config_with_interval(layout, interval_sec: int | None) -> None:
    """Persist a config.toml with the requested ``incremental_interval_sec``."""
    body = "[scan]\n"
    if interval_sec is not None:
        body += f"incremental_interval_sec = {interval_sec}\n"
    layout.config_file.parent.mkdir(parents=True, exist_ok=True)
    layout.config_file.write_text(body, encoding="utf-8")


def _make_fake_start(calls: list[dict[str, Any]]):
    """Stand-in ``ScanService.start`` that records calls + returns a job."""
    from pick_face.service.scan_service import ScanJob, ScanState

    def fake_start(self, *, paths=None, kind: str = "incremental"):
        _ = self
        job = ScanJob(
            id=f"poll-{len(calls)}",
            state=ScanState.QUEUED,
            kind=kind,
            paths=[str(p) for p in paths] if paths else [],
        )
        calls.append({"paths": list(paths) if paths else None, "kind": kind})
        return job

    return fake_start


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_polls_every_interval_seconds(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M8-T-2: at ``interval_sec=1`` ≥ 2 jobs land within 2.5s."""
    layout = _layout(tmp_pure)
    _write_config_with_interval(layout, 1)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    from pick_face.service.polling_scheduler import PollingScheduler

    async def go() -> None:
        sched = PollingScheduler(layout, interval_sec=1)
        sched.start()
        # ``add_job(next_run_time=None)`` leaves the APScheduler job
        # in a paused state in apscheduler 3.x. Resume it so the
        # interval can fire — the production wiring does the same
        # via lifespan setup; in unit tests we drive it explicitly.
        sched._scheduler.resume_job("polling-scheduler-tick")  # noqa: SLF001
        try:
            # Wait long enough for at least 2 ticks.
            await asyncio.sleep(2.5)
        finally:
            await sched.stop()

    asyncio.run(go())
    path_only_jobs = [c for c in calls if c["kind"] == "path_only"]
    assert len(path_only_jobs) >= 2, f"expected ≥ 2 polls, got {calls}"


def test_default_interval_from_config(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing ``incremental_interval_sec`` falls back to the 300s default.

    We don't wait 300s — we just construct the scheduler and assert
    that the interval reads as the documented default without
    requiring a config value.
    """
    layout = _layout(tmp_pure)
    # No config file at all → default.
    layout.config_file.unlink(missing_ok=True)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    from pick_face.service.polling_scheduler import (
        DEFAULT_INCREMENTAL_INTERVAL_SEC,
        PollingScheduler,
    )

    sched = PollingScheduler(layout)  # no interval_sec, no config
    # DEFAULT_INCREMENTAL_INTERVAL_SEC is 300.
    assert sched._interval_sec == DEFAULT_INCREMENTAL_INTERVAL_SEC  # noqa: SLF001
    assert DEFAULT_INCREMENTAL_INTERVAL_SEC == 300


def test_invalid_interval_falls_back_to_default(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A negative or zero ``incremental_interval_sec`` is coerced to the default.

    Both the constructor override and the config-file value are tested.
    The scheduler additionally clamps to >= 1s so a misconfigured
    deployment can't busy-loop.
    """
    layout = _layout(tmp_pure)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    from pick_face.service.polling_scheduler import (
        DEFAULT_INCREMENTAL_INTERVAL_SEC,
        PollingScheduler,
    )

    # Explicit negative override → default.
    sched = PollingScheduler(layout, interval_sec=-5)
    assert sched._interval_sec == DEFAULT_INCREMENTAL_INTERVAL_SEC  # noqa: SLF001

    # Config-driven negative → default.
    _write_config_with_interval(layout, -10)
    sched = PollingScheduler(layout)
    assert sched._interval_sec == DEFAULT_INCREMENTAL_INTERVAL_SEC  # noqa: SLF001

    # Zero is coerced to default too (per the spec — only positive integers pass).
    _write_config_with_interval(layout, 0)
    sched = PollingScheduler(layout)
    assert sched._interval_sec == DEFAULT_INCREMENTAL_INTERVAL_SEC  # noqa: SLF001


def test_stop_prevents_further_ticks(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After ``stop()``, no new ``ScanService.start`` calls land.

    Counts calls during the running window, calls after stop, asserts
    the post-stop window had zero new calls.
    """
    layout = _layout(tmp_pure)
    _write_config_with_interval(layout, 1)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    from pick_face.service.polling_scheduler import PollingScheduler

    async def go() -> None:
        sched = PollingScheduler(layout, interval_sec=1)
        sched.start()
        # See test_polls_every_interval_seconds for why we resume here.
        sched._scheduler.resume_job("polling-scheduler-tick")  # noqa: SLF001
        try:
            # Let a couple of ticks fire.
            await asyncio.sleep(1.5)
        finally:
            await sched.stop()
        count_at_stop = len(calls)
        # Wait two more interval-periods; nothing should fire.
        await asyncio.sleep(2.0)
        return count_at_stop

    count_at_stop = asyncio.run(go())
    assert count_at_stop >= 1, "no ticks fired before stop"
    assert len(calls) == count_at_stop, (
        f"post-stop ticks leaked: before={count_at_stop} after={len(calls)}"
    )


def test_status_transitions(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M8-T-7: ``status()`` returns 'inactive' / 'active' / 'inactive' across lifecycle."""
    layout = _layout(tmp_pure)
    _write_config_with_interval(layout, 60)

    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start([])
    )

    from pick_face.service.polling_scheduler import PollingScheduler

    async def go() -> None:
        sched = PollingScheduler(layout)
        assert sched.status() == "inactive"
        sched.start()
        try:
            assert sched.status() == "active"
            # qsize() returns 1 when a tick is in flight; 0 otherwise.
            assert sched.qsize() in (0, 1)
        finally:
            await sched.stop()
        assert sched.status() == "inactive"

    asyncio.run(go())