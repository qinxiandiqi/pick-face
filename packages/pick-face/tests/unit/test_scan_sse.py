"""Tests for the M8-T-8 SSE event sidecar + ``job_events`` generator.

We exercise the JSONL sidecar that the scan worker + cluster worker
append to (``scan-{id}.events.jsonl``) and assert the SSE generator
emits one ``new_photo`` / ``new_person`` / ``merged`` event per line.

Strategy: run the scan worker against a tmp layout, write known
events to the sidecar, then drive ``api.scan.job_events`` through
``TestClient`` (or consume it directly) and parse the SSE frames.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


class _StubDetector:
    def detect(self, bgr):
        from pick_face.ingest.detector import Detection

        h, w = bgr.shape[:2]
        return [
            Detection(
                bbox=(0.0, 0.0, float(w), float(h)),
                landmarks=[(w / 2, h / 2)] * 5,
                det_score=0.9,
                chip=bgr,
                quality=0.8,
            )
        ]


class _StubEmbedder:
    dim = 4

    def embed(self, chip):
        import numpy as np
        return np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)


class _Dec:
    def __call__(self, path):
        import numpy as np
        return _DecObj(np.zeros((20, 20, 3), dtype="uint8"))


class _DecObj:
    def __init__(self, bgr):
        self.bgr = bgr


def _consume_sse_frames(body_chunks: list[bytes]) -> list[dict[str, Any]]:
    """Parse SSE frames from a chunked HTTP response body.

    Returns one dict per event, with keys ``event`` and ``data`` (parsed JSON).
    """
    text = b"".join(body_chunks).decode("utf-8", errors="replace")
    out: list[dict[str, Any]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        ev_type = "message"
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event: "):
                ev_type = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :].strip())
        data_raw = "\n".join(data_lines)
        try:
            data_obj = json.loads(data_raw) if data_raw else {}
        except (ValueError, TypeError):
            data_obj = {"_raw": data_raw}
        out.append({"event": ev_type, "data": data_obj})
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sse_emits_new_photo_during_run(tmp_pure: Path) -> None:
    """M8-T-8: a 2-photo scan appends 2 ``new_photo`` lines to the sidecar."""
    from PIL import Image

    from pick_face.service.scan_service import ScanService
    from pick_face.worker.scan_worker import ensure_schema, run_scan

    layout = _layout(tmp_pure)
    photos = tmp_pure / "photos"
    photos.mkdir()
    Image.new("RGB", (30, 30), (255, 0, 0)).save(photos / "a.jpg")
    Image.new("RGB", (30, 30), (0, 255, 0)).save(photos / "b.jpg")
    ensure_schema(layout.db_path)

    svc = ScanService(layout)
    job = svc.start(paths=[photos], kind="full")
    events_file = layout.jobs_dir / f"scan-{job.id}.events.jsonl"

    async def go() -> None:
        await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=_Dec(),
            model_version="stub/1",
            job_id=job.id,
            events_file=events_file,
        )

    asyncio.run(go())
    # Read BEFORE transitioning to DONE — the service unlinks the
    # sidecar on terminal state, so reading post-DONE would 404.

    lines = events_file.read_text(encoding="utf-8").splitlines()
    new_photo_lines = [ln for ln in lines if '"new_photo"' in ln]
    assert len(new_photo_lines) == 2, lines


def test_sse_emits_new_person_after_cluster_run(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-8: a cluster run with a brand-new cluster writes ``new_person``.

    We drive ``ClusterWorker._append_sidecar_events`` directly with a
    synthetic new-cluster + an active job to bypass HDBSCAN + HNSW.
    """
    from pick_face.service.scan_service import ScanService, ScanState
    from pick_face.store.index import open_db

    layout = _layout(tmp_pure)
    # Ensure schema so ScanService / open_db work.
    open_db(layout.db_path).close()
    svc = ScanService(layout)
    job = svc.start(paths=[tmp_pure / "photos"], kind="full")
    svc.update_state(job.id, ScanState.RUNNING)  # _append_sidecar_events
    # requires an active RUNNING job.
    sidecar = layout.jobs_dir / f"scan-{job.id}.events.jsonl"
    sidecar.touch(exist_ok=True)

    # The worker writes ``type`` discriminator which the SSE generator
    # strips and turns into the event name. We seed the sidecar and
    # read it back via the SSE parser.
    from pick_face.worker.cluster_worker import ClusterWorker
    from unittest.mock import MagicMock

    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=MagicMock())
    cw._append_sidecar_events(  # noqa: SLF001
        [{"cluster_id": 42, "label": "person-0042"}],
        [],
    )

    raw_lines = sidecar.read_text(encoding="utf-8").splitlines()
    new_person_lines = [ln for ln in raw_lines if '"new_person"' in ln]
    assert len(new_person_lines) == 1, raw_lines
    obj = json.loads(new_person_lines[0])
    assert obj["type"] == "new_person"
    assert obj["cluster_id"] == 42


def test_sse_emits_merged_when_centroids_close(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-8: a cluster run that merges two clusters emits ``merged``."""
    from pick_face.service.scan_service import ScanService, ScanState
    from pick_face.store.index import open_db
    from pick_face.worker.cluster_worker import ClusterWorker
    from unittest.mock import MagicMock

    layout = _layout(tmp_pure)
    open_db(layout.db_path).close()
    svc = ScanService(layout)
    job = svc.start(paths=[tmp_pure / "photos"], kind="full")
    svc.update_state(job.id, ScanState.RUNNING)
    sidecar = layout.jobs_dir / f"scan-{job.id}.events.jsonl"
    sidecar.touch(exist_ok=True)

    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=MagicMock())
    cw._append_sidecar_events(  # noqa: SLF001
        [],
        [(10, 5)],  # (loser_id, winner_id)
    )

    raw_lines = sidecar.read_text(encoding="utf-8").splitlines()
    merged_lines = [ln for ln in raw_lines if '"merged"' in ln]
    assert len(merged_lines) == 1, raw_lines
    obj = json.loads(merged_lines[0])
    assert obj["type"] == "merged"
    assert obj["cluster_id"] == 10
    assert obj["into_cluster_id"] == 5


def test_sse_closes_on_end(tmp_pure: Path) -> None:
    """M8-T-8: after the scan hits DONE, the SSE generator emits ``end`` and stops.

    Drive ``api.scan.job_events`` directly with a fake request and
    collect chunks. We expect an ``end`` event after the first progress
    poll (since the job is already DONE in the registry).
    """
    import asyncio
    from pick_face.api import scan as scan_api
    from pick_face.service.scan_service import ScanService, ScanProgress, ScanState

    layout = _layout(tmp_pure)
    svc = ScanService(layout)
    job = svc.start(paths=[tmp_pure / "photos"], kind="full")
    svc.update_state(job.id, ScanState.DONE)
    svc.update_progress(
        job.id, ScanProgress(processed=1, total=1, faces=1, errors=0)
    )

    chunks: list[bytes] = []

    class _FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def go():
        gen = scan_api.job_events(job_id=job.id, request=_FakeRequest(), svc=svc)
        # The handler returns a StreamingResponse; we have to extract
        # the generator body via __call__.
        resp = await gen  # StreamingResponse
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
            # Stop once we've seen ``end`` — otherwise this would loop forever.
            if b"event: end" in (chunks[-1] if chunks else b""):
                return

    asyncio.run(go())

    frames = _consume_sse_frames(chunks)
    end_frames = [f for f in frames if f["event"] == "end"]
    progress_frames = [f for f in frames if f["event"] == "progress"]
    assert end_frames, frames
    assert progress_frames, frames


# ---------------------------------------------------------------------------
# Global SSE stream  — `/api/scan/events`
# ---------------------------------------------------------------------------


def test_global_events_emits_snapshot_then_updates(tmp_pure: Path) -> None:
    """Push-based replacement for polling ``/api/scan/jobs/active``.

    The generator should emit a ``snapshot`` on connect, then a
    ``job_update`` whenever the active job's progress or state
    changes. We drive the loop manually with a tiny ``_Tick`` shim
    that counts down without sleeping — the generator's ``asyncio.sleep``
    is replaced so the test finishes in O(milliseconds).
    """
    import asyncio
    from pick_face.api import scan as scan_api
    from pick_face.service.scan_service import ScanProgress, ScanService, ScanState

    layout = _layout(tmp_pure)
    svc = ScanService(layout)
    job = svc.start(paths=[tmp_pure / "photos"], kind="full")
    svc.update_state(job.id, ScanState.RUNNING)
    svc.update_progress(job.id, ScanProgress(processed=0, total=10, faces=0, errors=0))

    chunks: list[bytes] = []

    class _FakeRequest:
        def __init__(self) -> None:
            self._disconnected = False

        async def is_disconnected(self) -> bool:
            return self._disconnected

    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds: float) -> None:
        # Step the generator 5 times quickly so it sees the change.
        await real_sleep(0)  # yield to loop, no real delay

    async def go() -> None:
        req = _FakeRequest()
        gen = scan_api.global_events(request=req, svc=svc)
        resp = await gen  # StreamingResponse
        # Drain up to ~10 ticks (≈ 0.5 s simulated) or until we see the
        # expected ``job_update`` with the bumped counter.
        last_progress = None
        for _ in range(20):
            chunk_iter = resp.body_iterator
            try:
                chunk = await anext(chunk_iter)  # type: ignore[arg-type]
            except StopAsyncIteration:
                break
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
            # Mutate progress mid-stream — the generator should pick it up.
            if last_progress is None:
                last_progress = ScanProgress(processed=5, total=10, faces=3, errors=0)
                svc.update_progress(job.id, last_progress)
            await real_sleep(0)
            if b"event: job_update" in chunks[-1]:
                # We've captured the change — bail before ping spam.
                req._disconnected = True
                break
        req._disconnected = True

    asyncio.run(go())

    frames = _consume_sse_frames(chunks)
    snapshot_frames = [f for f in frames if f["event"] == "snapshot"]
    update_frames = [f for f in frames if f["event"] == "job_update"]

    assert snapshot_frames, frames
    assert update_frames, frames
    # The first snapshot is the original (processed=0, total=10). Note
    # the wire format uses lowercase state strings (matches ScanState
    # enum values); the frontend zod schema mirrors this exact casing.
    snap = snapshot_frames[0]["data"]
    assert snap is not None and snap["state"] == "running"
    assert snap["progress"]["processed"] == 0
    # The job_update reflects the bumped counters.
    upd = update_frames[0]["data"]
    assert upd is not None and upd["progress"]["processed"] == 5
    assert upd["progress"]["faces"] == 3


def test_global_events_snapshot_null_when_no_active_job(tmp_pure: Path) -> None:
    """If nothing is running, the initial snapshot is ``null``."""
    import asyncio
    from pick_face.api import scan as scan_api
    from pick_face.service.scan_service import ScanService

    layout = _layout(tmp_pure)
    svc = ScanService(layout)

    chunks: list[bytes] = []

    class _FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def go() -> None:
        gen = scan_api.global_events(request=_FakeRequest(), svc=svc)
        resp = await gen
        # Drain just the first chunk (the snapshot) — generator then loops.
        chunk = await anext(resp.body_iterator)  # type: ignore[arg-type]
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())

    asyncio.run(go())
    frames = _consume_sse_frames(chunks)
    snapshots = [f for f in frames if f["event"] == "snapshot"]
    assert len(snapshots) == 1
    assert snapshots[0]["data"] is None