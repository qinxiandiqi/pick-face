"""Scan HTTP surface — `docs/03 §2.2` + `docs/06 §1.1`.

Routes:

- ``GET    /api/scan/jobs``               list all jobs (newest first)
- ``GET    /api/scan/jobs/active``        return the currently RUNNING job
- ``POST   /api/scan/jobs``               enqueue a new job
- ``GET    /api/scan/jobs/{id}``          single job
- ``PATCH  /api/scan/jobs/{id}``          pause / resume / cancel
- ``GET    /api/scan/jobs/{id}/events``   per-job SSE progress stream
- ``GET    /api/scan/events``             global SSE stream of the active
                                          job (snapshot + on-change pushes);
                                          replaces polling ``/jobs/active``

The actual file-walking + embedding work lives in
:mod:`pick_face.worker.scan_worker`. The router hands off to the
runner module which owns the in-process asyncio task.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from pick_face.api.deps import get_scan_service
from pick_face.core.errors import ConfigError
from pick_face.service.scan_service import (
    ScanJob,
    ScanProgress,
    ScanService,
    ScanState,
)

router = APIRouter(prefix="/api/scan", tags=["scan"])


class StartScanRequest(BaseModel):
    paths: list[str] | None = Field(
        default=None,
        description="Optional scan roots; defaults to all enabled whitelist paths.",
    )
    kind: str = Field(
        default="incremental",
        pattern="^(full|incremental|path_only)$",
    )


class ScanTransitionRequest(BaseModel):
    target: str = Field(..., pattern="^(paused|cancelled|resumed)$")


def _serialize(job: ScanJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "state": job.state.value,
        "kind": job.kind,
        "paths": list(job.paths),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "progress": {
            "processed": job.progress.processed,
            "total": job.progress.total,
            "faces": job.progress.faces,
            "errors": job.progress.errors,
            "eta_sec": job.progress.eta_sec,
        },
        "error": job.error,
    }


@router.get("/jobs")
def list_jobs(
    svc: ScanService = Depends(get_scan_service),
) -> dict[str, list[dict[str, Any]]]:
    return {"jobs": [_serialize(j) for j in svc.list_jobs()]}


@router.get("/jobs/active")
def active_job(
    svc: ScanService = Depends(get_scan_service),
) -> dict[str, Any] | None:
    job = svc.active()
    return _serialize(job) if job is not None else None


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    svc: ScanService = Depends(get_scan_service),
) -> dict[str, Any]:
    job = svc.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _serialize(job)


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def start_job(
    body: StartScanRequest,
    request: Request,
    svc: ScanService = Depends(get_scan_service),
) -> dict[str, Any]:
    """Enqueue a new scan job; the runner picks it up on next tick."""
    from pathlib import Path

    try:
        paths = [Path(p) for p in body.paths] if body.paths else None
        job = svc.start(paths=paths, kind=body.kind)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Hand off to the runner. The runner is mounted on app.state.
    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        try:
            runner.consider(job.id)
        except RuntimeError:
            # ``consider`` calls ``asyncio.create_task`` which needs a
            # running loop. If the request handler ran in a worker
            # thread (TestClient sync mode), there's no loop — swallow
            # and let the next poll tick pick the job up.
            pass
    return _serialize(job)


@router.patch("/jobs/{job_id}")
def transition_job(
    job_id: str,
    body: ScanTransitionRequest,
    svc: ScanService = Depends(get_scan_service),
) -> dict[str, Any]:
    job = svc.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    target_state = {
        "paused": ScanState.PAUSED,
        "cancelled": ScanState.CANCELLED,
        "resumed": ScanState.QUEUED,
    }[body.target]
    if not svc.update_state(job_id, target_state):
        raise HTTPException(status_code=409, detail="state transition not allowed")
    updated = svc.get(job_id)
    assert updated is not None  # we just wrote it
    return _serialize(updated)


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    svc: ScanService = Depends(get_scan_service),
) -> Any:
    """Server-Sent Events stream of progress updates.

    Yields:

    - ``event: progress`` — one per ScanService progress tick (existing).
    - ``event: new_photo`` — M8-T-8, one per face-bearing image scanned.
    - ``event: new_person`` — M8-T-8, one per new ``cluster`` row.
    - ``event: merged`` — M8-T-8, one per cluster merge.
    - ``event: end`` — job reached a terminal state.

    The ``new_photo`` / ``new_person`` / ``merged`` events are tailed
    from the ``scan-{id}.events.jsonl`` sidecar that the runner +
    cluster worker append to. The sidecar is created on
    ``ScanService.start`` and deleted on terminal transition (so a
    stale file from a prior failed run doesn't replay).
    """
    import asyncio
    import json
    from pathlib import Path

    from fastapi.responses import StreamingResponse

    job = svc.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    sidecar: Path = svc.events_file(job_id)

    async def gen():
        last_progress: ScanProgress | None = None
        last_pos = 0
        while True:
            current = svc.get(job_id)
            if current is None:
                yield "event: closed\ndata: {}\n\n"
                return
            if current.progress != last_progress:
                payload = json.dumps(_serialize(current))
                yield f"event: progress\ndata: {payload}\n\n"
                last_progress = current.progress

            # M8-T-8: tail the sidecar for incremental events. We
            # only seek forward so a slow client can disconnect +
            # reconnect without replaying history. Seek past EOF
            # reads zero bytes so this is naturally idempotent.
            try:
                if sidecar.exists():
                    data = sidecar.read_bytes()
                    if len(data) > last_pos:
                        new = data[last_pos:]
                        # Decode leniently — a partial final line is
                        # discarded (the next tick will see it).
                        for line in new.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except (ValueError, TypeError):
                                continue
                            evt_type = obj.get("type") if isinstance(obj, dict) else None
                            if evt_type in {"new_photo", "new_person", "merged"}:
                                # Strip the internal ``type`` discriminator;
                                # the SSE event name carries it instead.
                                obj.pop("type", None)
                                yield f"event: {evt_type}\ndata: {json.dumps(obj)}\n\n"
                        last_pos = len(data)
            except OSError:
                # Sidecar may have been deleted on terminal transition.
                pass

            if current.state in (ScanState.DONE, ScanState.FAILED, ScanState.CANCELLED):
                # Drain any final lines that landed between our last
                # read and the terminal state — but cap to one tick
                # so a stuck sidecar doesn't hold the connection.
                try:
                    if sidecar.exists():
                        data = sidecar.read_bytes()
                        if len(data) > last_pos:
                            new = data[last_pos:]
                            for line in new.splitlines():
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    obj = json.loads(line)
                                except (ValueError, TypeError):
                                    continue
                                evt_type = obj.get("type") if isinstance(obj, dict) else None
                                if evt_type in {"new_photo", "new_person", "merged"}:
                                    obj.pop("type", None)
                                    yield f"event: {evt_type}\ndata: {json.dumps(obj)}\n\n"
                            last_pos = len(data)
                except OSError:
                    pass
                yield "event: end\ndata: {}\n\n"
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


# -----------------------------------------------------------------------------
# Global scan-events stream (push-based replacement for polling /jobs/active)
# -----------------------------------------------------------------------------
#
# The SPA's ScanProgressBanner used to call ``GET /api/scan/jobs/active``
# every 2 s via TanStack Query refetchInterval. That keeps the active-job
# arrow spinning but is wasteful: nothing pushes, every browser tick the
# SPA hammers the server. The global stream here turns that into a single
# SSE connection:
#
#   - on connect: emit ``event: snapshot`` with the current active job
#     (or ``null``), so the banner can render its initial state without
#     a separate GET.
#   - poll ``svc.active()`` every 0.5 s (same cadence the per-job stream
#     uses) and emit ``event: job_update`` whenever either the active
#     job *identity* or its *progress* changes. The progress payload is
#     a full ``ScanJob`` snapshot — the banner only needs the progress
#     counters + state, but carrying the full record keeps the schema
#     identical to ``ScanJobSchema`` on the wire.
#   - 15 s heartbeat ``event: ping`` so proxy idle-timers (uvicorn
#     behind nginx / corporate proxies) don't drop the connection.
#
# We do NOT emit per-job ``new_photo`` / ``new_person`` / ``merged`` here
# — those are still served by ``/jobs/{id}/events`` and consumed by
# ``usePersonsLiveInvalidator``. Keeping the per-job stream for the
# fine-grained cluster events avoids bloating the global stream with
# thousands of incremental records during a long scan.
# -----------------------------------------------------------------------------


def _active_snapshot(svc: ScanService) -> tuple[str, str | None, str | None]:
    """Return a content fingerprint of the active job for change detection.

    Returns ``(job_id, state, progress_repr)`` where ``progress_repr`` is
    a stable string form of the progress counters (the SSE loop only
    needs to know "did anything change?"). A ``None`` active job is
    encoded as ``("", "", None)``.
    """
    job = svc.active()
    if job is None:
        return ("", "", None)
    progress = job.progress
    return (
        job.id,
        job.state.value,
        f"{progress.processed}/{progress.total}/{progress.faces}/{progress.errors}",
    )


@router.get("/events")
async def global_events(
    request: Request,
    svc: ScanService = Depends(get_scan_service),
) -> Any:
    """Server-Sent Events stream of the currently active scan job.

    Emits:

    - ``event: snapshot``   — current active job (or ``null``) on connect.
    - ``event: job_update`` — active job changed (state, progress, or a
                              different job became active). Payload is the
                              full ``ScanJob`` JSON, identical to the
                              shape returned by ``GET /jobs/{id}``.
    - ``event: ping``       — heartbeat every 15 s so intermediate proxies
                              do not drop the connection.

    On client disconnect the generator returns and the stream closes.
    """
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    async def gen():
        last_id, last_state, last_progress = _active_snapshot(svc)
        current = svc.active()
        yield (
            "event: snapshot\ndata: "
            + json.dumps(_serialize(current) if current is not None else None)
            + "\n\n"
        )

        ticks_since_ping = 0
        while True:
            await asyncio.sleep(0.5)
            ticks_since_ping += 1

            current = svc.active()
            cur_id, cur_state, cur_progress = _active_snapshot(svc)

            if cur_id != last_id or cur_state != last_state or cur_progress != last_progress:
                payload = json.dumps(_serialize(current) if current is not None else None)
                yield f"event: job_update\ndata: {payload}\n\n"
                last_id, last_state, last_progress = cur_id, cur_state, cur_progress

            if ticks_since_ping >= 30:  # 30 × 0.5 s = 15 s
                yield "event: ping\ndata: {}\n\n"
                ticks_since_ping = 0

            if await request.is_disconnected():
                return

    return StreamingResponse(gen(), media_type="text/event-stream")


__all__ = ["router"]
