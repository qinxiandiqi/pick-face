"""APScheduler-based polling fallback — `docs/06 §3.1 M8-T-2`.

Watchdog (see :mod:`pick_face.service.file_watcher`) is unreliable on
Docker bind mounts, NFS, and certain FUSE filesystems. This module
provides a periodic poll that drives the existing
``ScanService.start(paths=None, kind='path_only')`` over ALL enabled
whitelist roots at a configurable interval (``incremental_interval_sec``,
default 300s).

The poll is idempotent: ``run_scan`` diffs via ``(size, mtime)`` and
UNCHANGED files are skipped. Worst case when both the watcher and the
poller fire for the same file is one redundant DB read.

The scheduler reads its interval from ``[scan] incremental_interval_sec``
in ``config.toml`` (already present in the M7 default template at
``config_service.py:170``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from pick_face.service.config_service import get_incremental_interval_sec
from pick_face.service.paths import AppLayout
from pick_face.service.scan_service import ScanService

log = logging.getLogger(__name__)

# Re-exported for tests; the canonical constant lives in
# ``pick_face.service.config_service`` so the scheduler + tests agree.
DEFAULT_INCREMENTAL_INTERVAL_SEC = 300


class PollingScheduler:
    """Periodic fallback that triggers ``path_only`` scans.

    Owns one ``AsyncIOScheduler`` instance with a single interval job.
    ``start()`` reads ``incremental_interval_sec`` from config and
    schedules the first tick at ``now + interval``; ``stop()`` waits
    for any in-flight tick to complete before tearing down.
    """

    def __init__(
        self,
        layout: AppLayout,
        *,
        interval_sec: int | None = None,
        runner: object | None = None,
    ) -> None:
        self._layout = layout
        # Negative or zero intervals fall back to default; this
        # mirrors ``ScanService``'s tolerance for misconfigurations.
        if interval_sec is None or interval_sec <= 0:
            interval_sec = self._read_interval_from_config()
        self._interval_sec = max(1, int(interval_sec))
        self._runner = runner  # duck-typed ``consider(job_id)``
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        """Schedule the interval job. Idempotent."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        # APScheduler 3.11 requires an *explicit* ``next_run_time``
        # for AsyncIOScheduler jobs — ``None`` defers to the
        # trigger's ``start_date`` (also ``None``) and the job never
        # fires. ``datetime.now() + interval`` gives the expected
        # "first tick at +interval" behavior.
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(seconds=self._interval_sec),
            id="polling-scheduler-tick",
            next_run_time=datetime.now() + timedelta(seconds=self._interval_sec),
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        log.info(
            "polling_scheduler: interval=%ds (fallback for FS that ignore watchdog)",
            self._interval_sec,
        )

    async def stop(self) -> None:
        """Shut down the scheduler; wait for the in-flight tick."""
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=True)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("polling_scheduler: shutdown error: %s", exc)
        self._scheduler = None
        log.info("polling_scheduler: stopped")

    def qsize(self) -> int:
        """Backlog surrogate: 1 if a tick is currently running, else 0.

        ``/api/ready`` surfaces this as the ``recluster`` bucket to
        keep the JSON shape uniform with ``file_watcher.qsize()``.
        APScheduler does not expose a native queue depth for
        interval jobs.
        """
        if self._scheduler is None:
            return 0
        job = self._scheduler.get_job("polling-scheduler-tick")
        return 0 if job is None or job.next_run_time is None else 1

    def status(self) -> str:
        """``active`` | ``inactive`` | ``disabled``.

        Always ``active`` once ``start()`` ran; ``inactive`` after
        ``stop()``; ``disabled`` is reserved for a future toggle.
        """
        if self._scheduler is None:
            return "inactive"
        return "active"

    # -- internals --------------------------------------------------------

    async def _tick(self) -> None:
        """Single poll: emit one ``path_only`` job over ALL enabled roots."""
        try:
            svc = ScanService(self._layout)
            # Skip if a scan is already RUNNING — the runner poll
            # will pick this up next cycle. Mirrors
            # ``ScanRunner._run`` precedence rules.
            if svc.active() is not None:
                return
            job = svc.start(paths=None, kind="path_only")
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("polling_scheduler: tick failed: %s", exc)
            return
        consider = getattr(self._runner, "consider", None)
        if callable(consider):
            try:
                consider(job.id)
            except RuntimeError:
                # Off-loop test invocation: ``ScanRunner._run`` will
                # still pick it up.
                pass

    def _read_interval_from_config(self) -> int:
        """Read ``[scan] incremental_interval_sec``; default 300s.

        Delegates to :func:`config_service.get_incremental_interval_sec`
        so the scheduler and the rest of the Web service share one
        canonical fallback value.
        """
        try:
            return get_incremental_interval_sec(self._layout)
        except Exception:  # pragma: no cover — defensive
            return DEFAULT_INCREMENTAL_INTERVAL_SEC


def set_runner(scheduler: PollingScheduler, runner: Callable[[str], None] | None) -> None:
    """Inject the runner after construction. Used by lifespan wiring."""
    scheduler._runner = runner  # noqa: SLF001 — internal contract


__all__ = [
    "DEFAULT_INCREMENTAL_INTERVAL_SEC",
    "PollingScheduler",
    "set_runner",
]