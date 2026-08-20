"""In-process scan runner — owns the asyncio task that consumes jobs.

The runner reads ``ScanService.active()`` on a tick and starts a
``run_scan`` coroutine when one is QUEUED. It writes progress via
``ScanService.update_progress`` and final state via
``update_state``. M6 keeps this in-process; M8 may lift it to a
separate worker subprocess if cross-process coordination is needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pick_face.core.images import decode
from pick_face.ingest.detector import Detector
from pick_face.ingest.embedder import Embedder
from pick_face.service.paths import AppLayout, get_layout
from pick_face.service.scan_service import ScanJob, ScanProgress, ScanService, ScanState
from pick_face.worker.scan_worker import run_scan

log = logging.getLogger(__name__)


class ScanRunner:
    """Owns the asyncio task for scan execution.

    The runner is mounted on ``app.state.runner`` at startup. It is
    safe to call ``consider(job_id)`` from a request handler — the
    runner dedupes (won't start two coroutines for the same job) and
    silently ignores calls when no active job exists.
    """

    POLL_INTERVAL_SEC = 0.5

    def __init__(
        self,
        layout: AppLayout,
        detector: Detector | None = None,
        embedder: Embedder | None = None,
        model_version: str = "yunet-sface/1",
        on_scan_complete: Callable[[list[int]], None] | None = None,
    ) -> None:
        self._layout = layout
        self._detector = detector
        self._embedder = embedder
        self._model_version = model_version
        self._on_scan_complete = on_scan_complete
        self._inflight: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._t0: float = 0.0

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Spawn the polling task. Called from FastAPI startup hook."""
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="scan-runner")

    async def stop(self) -> None:
        """Signal the polling task to exit; awaits the task."""
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    # -- public API -------------------------------------------------------

    def consider(self, job_id: str) -> None:
        """No-op if the job is already inflight or terminal."""
        if job_id in self._inflight:
            return
        svc = ScanService(self._layout)
        job = svc.get(job_id)
        if job is None or job.state != ScanState.QUEUED:
            return
        self._inflight.add(job_id)
        asyncio.create_task(self._execute(job), name=f"scan-execute-{job_id}")

    # -- internals --------------------------------------------------------

    async def _run(self) -> None:
        """Poll the registry for QUEUED jobs and dispatch them."""
        while not self._stop.is_set():
            try:
                svc = ScanService(self._layout)
                job = svc.active()
                if job is not None and job.id not in self._inflight:
                    self.consider(job.id)
            except (OSError, ValueError) as exc:
                log.warning("scan-runner poll error: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.POLL_INTERVAL_SEC
                )
            except asyncio.TimeoutError:
                continue

    async def _execute(self, job: ScanJob) -> None:
        """Run the scan coroutine and persist progress + final state."""
        svc = ScanService(self._layout)
        svc.update_state(job.id, ScanState.RUNNING)
        self._t0 = time.monotonic()
        try:
            if self._detector is None or self._embedder is None:
                raise RuntimeError("detector/embedder not loaded into runner")
            scan_paths = [Path(p) for p in job.paths]

            async def progress_cb(
                processed: int, total: int, faces: int, errors: int
            ) -> None:
                eta: int | None = None
                if total > 0 and processed > 0:
                    elapsed = time.monotonic() - self._t0
                    rate = processed / max(1e-6, elapsed)
                    remaining = max(0, total - processed)
                    eta = int(remaining / max(1e-6, rate))
                svc.update_progress(
                    job.id,
                    ScanProgress(
                        processed=processed,
                        total=total,
                        faces=faces,
                        errors=errors,
                        eta_sec=eta,
                    ),
                )

            result = await run_scan(
                scan_paths=scan_paths,
                db_path=self._layout.db_path,
                detector=self._detector,
                embedder=self._embedder,
                decoder=decode,
                model_version=self._model_version,
                progress_cb=progress_cb,
                events_file=svc.events_file(job.id),
            )
            if result.errors > 0:
                log.info(
                    "scan %s completed with %d file errors",
                    job.id,
                    result.errors,
                )
            svc.update_state(job.id, ScanState.DONE)
            # M8-T-4: notify downstream consumers (cluster_worker)
            # that new face rows landed. The callback increments the
            # unclustered counter so the next incremental-check tick
            # can fire `_run_incremental`.
            new_face_ids = list(getattr(result, "face_ids", ()) or ())
            if self._on_scan_complete is not None and new_face_ids:
                try:
                    self._on_scan_complete(new_face_ids)
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("scan-runner: on_scan_complete error: %s", exc)
        except (OSError, RuntimeError, ValueError) as exc:
            log.exception("scan %s failed", job.id)
            svc.update_state(job.id, ScanState.FAILED, error=str(exc))
        finally:
            self._inflight.discard(job.id)


# -- factory ------------------------------------------------------------


def make_runner(layout: AppLayout | None = None) -> ScanRunner:
    """Construct a runner; detector/embedder are best-effort.

    M6 only wires the runner; the actual detector/embedder loading
    happens via the model pack entry-points. If no pack is on disk,
    the runner is constructed with ``detector=None`` and
    ``embedder=None`` — submitting a job in that state will fail-fast
    with a clear error (``detector/embedder not loaded into runner``).
    Tests typically pass a stub via ``ScanRunner(layout, det, emb)``.
    """
    from pick_face.platform.pack import discover_packs

    layout = layout or get_layout()
    detector: Detector | None = None
    embedder: Embedder | None = None
    try:
        packs = discover_packs()
        default_pack = next(iter(packs.values()), None)
        if default_pack is not None and default_pack.model_dir(layout).is_dir():
            detector = default_pack.build_detector(layout.model_dir())  # type: ignore[attr-defined]
            embedder = default_pack.build_embedder(layout.model_dir())
    except (ImportError, AttributeError, OSError):
        detector = None
        embedder = None
    return ScanRunner(
        layout=layout,
        detector=detector,
        embedder=embedder,
    )


__all__ = [
    "ScanRunner",
    "make_runner",
]


# Silence linters that complain about the unused Any import on
# platforms where the only reference is inside a string annotation.
_ = Any
