"""Tests for service.file_watcher — watchdog → asyncio.Queue → ScanService.

Covers M8-T-1 (`docs/06 §3.1`): the file watcher bridges watchdog FS
events into ``ScanService.start(paths=[p], kind='path_only')`` jobs and
debounces a burst of writes into a single job per file.

Test strategy: spin up a real asyncio loop + the real watchdog
Observer, then ``monkeypatch`` ``ScanService.start`` so we can assert
on the calls. Drop a single file for the happy-path test; for the
debounce / modify / queue / stop tests we inject synthetic
``FileSystemEvent`` objects directly to keep the suite deterministic
and fast.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout_with_root(tmp_pure: Path):
    """Build a fresh layout + whitelist a single root directory."""
    from pick_face.service.config_service import ConfigService
    from pick_face.service.paths import get_layout

    layout = get_layout(data_dir=tmp_pure / "app")
    root = tmp_pure / "watch"
    root.mkdir()
    ConfigService(layout).add_path(str(root))
    return layout, root


def _make_fake_start(calls: list[dict[str, Any]]):
    """Build a stand-in ``ScanService.start`` that records calls + returns
    a minimal :class:`ScanJob` so the watcher's downstream code doesn't crash.
    """
    from pick_face.service.scan_service import ScanJob, ScanState

    def fake_start(self, *, paths=None, kind: str = "incremental"):
        # self is the ScanService instance — we ignore it for assertions.
        _ = self
        job = ScanJob(
            id=f"job-{len(calls)}",
            state=ScanState.QUEUED,
            kind=kind,
            paths=[str(p) for p in paths] if paths else [],
        )
        calls.append({"paths": list(paths) if paths else None, "kind": kind})
        return job

    return fake_start


async def _run_watcher(
    layout,
    *,
    debounce_sec: float = 0.2,
    action: Callable[[], None] | None = None,
    wait_sec: float = 0.0,
) -> Any:
    """Start the watcher, optionally run ``action`` mid-flight, then stop."""
    from pick_face.service.file_watcher import FileWatcher

    loop = asyncio.get_running_loop()
    watcher = FileWatcher(layout, loop=loop, debounce_sec=debounce_sec)
    watcher.start()
    try:
        # Give the Observer thread a beat to attach before we inject events.
        await asyncio.sleep(0.15)
        if action is not None:
            action()
        if wait_sec > 0:
            await asyncio.sleep(wait_sec)
    finally:
        await watcher.stop()
    return watcher


def _make_event(path: Path, *, kind: str = "created", is_directory: bool = False):
    """Construct a watchdog FileSystemEvent matching the watcher's filter.

    Avoids requiring watchdog's ``FileSystemEvent`` constructor (which
    takes internal args); we just instantiate via the concrete subclass.
    """
    from watchdog.events import FileCreatedEvent, FileModifiedEvent

    cls = FileCreatedEvent if kind == "created" else FileModifiedEvent
    return cls(str(path))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_start_emits_path_only_job_on_created(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-1: dropping a JPEG into a watched dir triggers a path_only job.

    Uses the real watchdog Observer (creates a tiny JPEG in the
    whitelisted dir). ``monkeypatch`` replaces ``ScanService.start``
    so we can assert on the captured call list.
    """
    from PIL import Image

    layout, root = _layout_with_root(tmp_pure)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    target = root / "drop.jpg"

    async def go() -> None:
        await _run_watcher(
            layout,
            debounce_sec=0.3,
            action=lambda: Image.new("RGB", (32, 32), (1, 2, 3)).save(target, "JPEG"),
            wait_sec=0.8,
        )

    asyncio.run(go())
    # At least one path_only job fired for our dropped file.
    matching = [c for c in calls if c["kind"] == "path_only" and c["paths"]]
    assert matching, f"no path_only job fired; calls={calls}"
    job_paths = [Path(p) for p in matching[0]["paths"]]
    assert any(p.name == "drop.jpg" for p in job_paths)


def test_debounce_collapses_burst(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """50 modifies to the same path inside debounce_sec → 1 job."""
    from pick_face.service.file_watcher import FileWatcher

    layout, root = _layout_with_root(tmp_pure)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    target = root / "burst.jpg"
    target.write_bytes(b"\xff\xd8\xff\xe0stub")  # any non-empty file

    async def go() -> None:
        loop = asyncio.get_running_loop()
        watcher = FileWatcher(layout, loop=loop, debounce_sec=0.3)
        watcher.start()
        try:
            await asyncio.sleep(0.15)  # observer up
            # Inject 50 modify events back-to-back on the watcher's own
            # event handler thread. They all collapse into a single
            # "last touch at t=now" record.
            for _ in range(50):
                watcher._on_event(_make_event(target, kind="modified"))  # noqa: SLF001
            # Let the debounce loop age the path + the consumer drain
            # the queue (debounce ticks every ~debounce_sec, consumer
            # waits up to 1s per item — budget 1.5s end-to-end).
            await asyncio.sleep(1.5)
        finally:
            await watcher.stop()

    asyncio.run(go())
    # Exactly one path_only job for the burst — burst collapse is the AC.
    path_only_for_burst = [
        c for c in calls
        if c["kind"] == "path_only"
        and c["paths"]
        and any(Path(p).name == "burst.jpg" for p in c["paths"])
    ]
    assert len(path_only_for_burst) == 1, f"expected 1 collapsed job, got {calls}"


def test_modify_event_triggers_too(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M8-T-1: FileModifiedEvent on an existing path also produces a job.

    The watcher's ``_on_event`` should treat both create and modify
    events identically — there's no "is this a new file?" check; the
    downstream ``run_scan`` diff handles that via (size, mtime).
    """
    from pick_face.service.file_watcher import FileWatcher

    layout, root = _layout_with_root(tmp_pure)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    target = root / "modify.jpg"
    target.write_bytes(b"\xff\xd8\xff\xe0stub")

    async def go() -> None:
        loop = asyncio.get_running_loop()
        watcher = FileWatcher(layout, loop=loop, debounce_sec=0.2)
        watcher.start()
        try:
            await asyncio.sleep(0.15)
            # Two modifies spaced apart so each ages out independently;
            # expect ≥1 (often exactly 2, but the AC is "modify fires").
            watcher._on_event(_make_event(target, kind="modified"))  # noqa: SLF001
            await asyncio.sleep(0.5)
            watcher._on_event(_make_event(target, kind="modified"))  # noqa: SLF001
            await asyncio.sleep(0.6)
        finally:
            await watcher.stop()

    asyncio.run(go())
    modify_jobs = [
        c for c in calls
        if c["kind"] == "path_only" and any(Path(p).name == "modify.jpg" for p in (c["paths"] or []))
    ]
    assert len(modify_jobs) >= 1, calls


def test_qsize_and_status_reflect_state(tmp_pure: Path) -> None:
    """M8-T-7: ``status()`` transitions inactive → active → inactive;
    ``qsize()`` starts at 0 and tracks the queue."""
    layout, root = _layout_with_root(tmp_pure)

    async def go() -> None:
        from pick_face.service.file_watcher import FileWatcher

        loop = asyncio.get_running_loop()
        watcher = FileWatcher(layout, loop=loop, debounce_sec=0.2)
        # Before start: no observer → inactive (but _enabled is True).
        assert watcher.status() == "inactive"
        assert watcher.qsize() == 0

        watcher.start()
        try:
            await asyncio.sleep(0.1)
            assert watcher.status() == "active"
            assert watcher.qsize() == 0
        finally:
            await watcher.stop()
        # After stop: observer torn down → inactive.
        assert watcher.status() == "inactive"
        assert watcher.qsize() == 0

    asyncio.run(go())


def test_stop_drains_queue(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After ``stop()``, no further ``ScanService.start`` calls land.

    We queue several path events *before* calling stop, then ensure
    the consumer task drains them but no new ones fire from a stale
    debounce loop.
    """
    layout, root = _layout_with_root(tmp_pure)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", _make_fake_start(calls)
    )

    async def go() -> None:
        from pick_face.service.file_watcher import FileWatcher

        loop = asyncio.get_running_loop()
        watcher = FileWatcher(layout, loop=loop, debounce_sec=0.1)
        watcher.start()
        try:
            await asyncio.sleep(0.15)
            # Inject several distinct paths.
            for i in range(5):
                watcher._on_event(_make_event(root / f"f{i}.jpg", kind="created"))  # noqa: SLF001
            # Let them flush.
            await asyncio.sleep(0.6)
        finally:
            await watcher.stop()

        # Post-stop: trigger one more event to verify no jobs land.
        watcher._on_event(_make_event(root / "post.jpg", kind="created"))  # noqa: SLF001
        await asyncio.sleep(0.4)

    asyncio.run(go())
    # No job for post.jpg (events injected after stop).
    post_jobs = [
        c for c in calls
        if c["kind"] == "path_only" and any(Path(p).name == "post.jpg" for p in (c["paths"] or []))
    ]
    assert post_jobs == [], f"stopped watcher leaked jobs: {post_jobs}"
    # But the pre-stop events did land.
    pre_jobs = [
        c for c in calls
        if c["kind"] == "path_only" and any(Path(p).name.startswith("f") for p in (c["paths"] or []))
    ]
    assert len(pre_jobs) >= 1, calls


def test_status_disabled_when_no_whitelist(tmp_pure: Path) -> None:
    """When no scan roots are configured, ``status()`` returns 'disabled'.

    This is the SPA 'watcher offline' Badge state — the watcher
    silently disables itself when there's nothing to watch (test
    environments, pre-init deployments).
    """
    from pick_face.service.file_watcher import FileWatcher
    from pick_face.service.paths import get_layout

    layout = get_layout(data_dir=tmp_pure / "app")  # no scan_paths added

    async def go() -> None:
        loop = asyncio.get_running_loop()
        watcher = FileWatcher(layout, loop=loop, debounce_sec=0.1)
        watcher.start()
        # No watch_roots → disabled.
        assert watcher.status() == "disabled"

    asyncio.run(go())