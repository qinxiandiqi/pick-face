"""Scan HTTP surface — `docs/03 §2.2` + `docs/06 §1.1`.

Routes:

- ``GET    /api/scan/jobs``               list all jobs (newest first)
- ``GET    /api/scan/jobs/active``        return the currently RUNNING job
- ``POST   /api/scan/jobs``               enqueue a new job
- ``GET    /api/scan/jobs/{id}``          single job
- ``PATCH  /api/scan/jobs/{id}``          pause / resume / cancel
- ``GET    /api/scan/jobs/{id}/events``   SSE progress stream

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

    Yields one ``event: progress`` per worker tick. The client closes
    the connection when the job reaches a terminal state.
    """
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    job = svc.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def gen():
        last_progress: ScanProgress | None = None
        while True:
            current = svc.get(job_id)
            if current is None:
                yield "event: closed\ndata: {}\n\n"
                return
            if current.progress != last_progress:
                payload = json.dumps(_serialize(current))
                yield f"event: progress\ndata: {payload}\n\n"
                last_progress = current.progress
            if current.state in (ScanState.DONE, ScanState.FAILED, ScanState.CANCELLED):
                yield "event: end\ndata: {}\n\n"
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


__all__ = ["router"]
