"""File-system watcher bridge — `docs/06 §3.1 M8-T-1`.

Wraps a watchdog :class:`watchdog.observers.Observer` thread and
funnels its events into an asyncio.Queue owned by the FastAPI event
loop. Two threads are involved:

1. Watchdog's observer thread invokes ``on_any_event`` for every FS
   event. We collect ``(path, last_event_time)`` tuples in a
   thread-safe dict.
2. A debounce coroutine on the asyncio loop pops paths whose
   ``now - last_event_time > debounce_sec`` and pushes them onto
   the consumer queue. This collapses a "copy 50 files" burst into
   a single scan job per file.

The consumer task calls :meth:`ScanService.start` with
``kind="path_only"`` and then :meth:`ScanRunner.consider` (if a
runner is wired in). Each ``path_only`` scan re-uses the existing
``run_scan`` diff, so a brand-new file falls into the ``ADD`` bucket
automatically.

On Docker bind mounts and NFS, watchdog may never deliver events;
the APScheduler polling fallback (``polling_scheduler.py``) is the
safety net for those environments.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from pick_face.ingest.scanner import DEFAULT_IMAGE_EXTS
from pick_face.service.config_service import ConfigService
from pick_face.service.paths import AppLayout
from pick_face.service.scan_service import ScanService

log = logging.getLogger(__name__)


class FileWatcher:
    """Watchdog → asyncio.Queue → ``ScanService.start(paths=[...], kind='path_only')``.

    Lifecycle: instantiate in lifespan, ``start()`` on startup,
    ``await stop()`` on shutdown. ``qsize()`` and ``status()`` feed
    ``/api/ready`` (M8-T-7).

    The watcher filters events to ``DEFAULT_IMAGE_EXTS`` so
    ``.crdownload`` / ``.tmp`` partial files do not trigger jobs.
    """

    def __init__(
        self,
        layout: AppLayout,
        *,
        loop: asyncio.AbstractEventLoop,
        debounce_sec: float = 5.0,
        runner: object | None = None,
    ) -> None:
        self._layout = layout
        self._loop = loop
        self._debounce_sec = float(debounce_sec)
        # The runner is duck-typed (``consider(job_id)``) so tests
        # can pass a stub. M8-T-4: the runner also fires
        # ``on_scan_complete`` callbacks; we do not call those here.
        self._runner = runner
        # Path → epoch of last event. Touched by watchdog thread.
        self._events: dict[Path, float] = {}
        self._events_lock = threading.Lock()
        self._observer: Observer | None = None
        self._debounce_task: asyncio.Task[None] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Path] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        # ``_enabled`` lets tests / lifespan hook toggle the watcher
        # without rebuilding the Observer (e.g. when no scan paths
        # are configured). When False the watcher reports
        # ``status() == "disabled"`` and emits no jobs.
        self._enabled = True

    # -- public API --------------------------------------------------------

    def start(self) -> None:
        """Schedule the Observer thread + the asyncio loop tasks.

        Idempotent: a second call while already running is a no-op.
        """
        if self._observer is not None:
            return
        roots = list(self._watch_roots())
        if not roots:
            log.info("file_watcher: no enabled scan roots; watcher disabled")
            self._enabled = False
            return
        handler = _Handler(self)
        self._observer = Observer()
        for root in roots:
            self._observer.schedule(handler, str(root), recursive=True)
        self._observer.start()
        self._stop_event.clear()
        self._debounce_task = self._loop.create_task(
            self._debounce_loop(), name="file-watcher-debounce"
        )
        self._consumer_task = self._loop.create_task(
            self._consumer_loop(), name="file-watcher-consumer"
        )
        log.info("file_watcher: watching %d roots", len(roots))

    async def stop(self) -> None:
        """Stop the Observer, drain the queue, cancel the loop tasks."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self._stop_event.set()
        for task in (self._debounce_task, self._consumer_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, OSError, RuntimeError):
                    pass
        self._debounce_task = None
        self._consumer_task = None
        log.info("file_watcher: stopped")

    def qsize(self) -> int:
        """Current backlog. Surfaced via ``/api/ready`` (M8-T-7)."""
        return self._queue.qsize()

    def status(self) -> str:
        """``active`` | ``inactive`` | ``disabled``.

        ``disabled`` means we never started (no scan roots). The
        /api/ready endpoint surfaces this so operators can spot a
        misconfigured deployment without tailing logs.
        """
        if not self._enabled:
            return "disabled"
        if self._observer is None:
            return "inactive"
        return "active"

    # -- internal hooks called by the watchdog thread ---------------------

    def _on_event(self, event: FileSystemEvent) -> None:
        """Called by watchdog thread; must be thread-safe + non-blocking."""
        if event.is_directory:
            return
        path = Path(getattr(event, "dest_path", None) or event.src_path)
        if path.suffix.lower() not in DEFAULT_IMAGE_EXTS:
            return
        with self._events_lock:
            self._events[path] = time.monotonic()
        # Wake the debounce loop immediately so we don't wait a full
        # tick for the next path to age out.
        self._loop.call_soon_threadsafe(self._kick_debounce)

    def _kick_debounce(self) -> None:
        if self._debounce_task is None or self._debounce_task.done():
            return
        # No-op: ``_debounce_loop`` polls at ``debounce_sec / 2``.
        # The call_soon_threadsafe is kept so test code can inject
        # wakeups deterministically.
        return

    # -- asyncio loop tasks -----------------------------------------------

    async def _debounce_loop(self) -> None:
        """Periodically move aged paths from the event dict to the queue."""
        try:
            while not self._stop_event.is_set():
                aged: list[Path] = []
                now = time.monotonic()
                with self._events_lock:
                    for path, last in list(self._events.items()):
                        if now - last >= self._debounce_sec:
                            aged.append(path)
                            del self._events[path]
                for path in aged:
                    await self._queue.put(path)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=max(0.5, self._debounce_sec / 2)
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise

    async def _consumer_loop(self) -> None:
        """Drain the queue: one ``ScanService.start`` + ``runner.consider`` per path."""
        try:
            while not self._stop_event.is_set():
                try:
                    path = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                try:
                    self._emit_job(path)
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("file_watcher: emit job failed for %s: %s", path, exc)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            raise

    def _emit_job(self, path: Path) -> None:
        """Create a QUEUED ``path_only`` job and hand it to the runner."""
        if not self._enabled:
            return
        svc = ScanService(self._layout)
        # If a scan is already RUNNING we still enqueue — the runner
        # picks it up via its 0.5s poll. This is safe because
        # ``run_scan`` diffs via (size, mtime).
        try:
            job = svc.start(paths=[path], kind="path_only")
        except Exception as exc:
            log.warning("file_watcher: ScanService.start failed: %s", exc)
            return
        consider = getattr(self._runner, "consider", None)
        if callable(consider):
            try:
                consider(job.id)
            except RuntimeError:
                # No running loop (test invocations without a real
                # FastAPI lifespan). The 0.5s poll in
                # ``ScanRunner._run`` will still pick it up.
                pass

    # -- helpers ----------------------------------------------------------

    def _watch_roots(self) -> Iterable[Path]:
        cfg = ConfigService(self._layout)
        return cfg.enabled_paths()


class _Handler(FileSystemEventHandler):
    """Adapter from watchdog callback to :meth:`FileWatcher._on_event`."""

    def __init__(self, watcher: FileWatcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        self._watcher._on_event(event)


# Sentinel default for ``runner`` parameter typing in tests where the
# watcher is constructed before the lifespan has wired the real
# ``ScanRunner``. Callers should pass ``None`` and call ``set_runner``
# later when ready.
def set_runner(watcher: FileWatcher, runner: Callable[[str], None] | None) -> None:
    """Inject the runner after construction. Used by lifespan wiring."""
    watcher._runner = runner  # noqa: SLF001 — internal contract


__all__ = ["FileWatcher", "set_runner"]