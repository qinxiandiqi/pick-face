"""Web service end-to-end smoke test (mark: web_smoke).

Drives the v3 Web service through the full first-run flow:

1. `pick-face-web init` — create the app root + default config.toml
2. `POST /api/config/paths` — whitelist a directory of synthetic JPEGs
3. `POST /api/scan/jobs` — enqueue an incremental scan
4. Wait for the scan to reach a terminal state (DONE/FAILED/CANCELLED)
5. `GET /api/persons` — confirm the read API works (may be empty if
   the synthetic fixture has no detectable faces)
6. `GET /api/photos/{id}/thumb` — confirm thumbnail generation works
7. `GET /api/health` + `GET /api/ready` — liveness/readiness

The test is **mark: web_smoke** and uses the same ``tmp_pure``
convention as unit tests — no real-face dataset, no model weights,
no network. It exercises the FastAPI surface via TestClient with
stub detector/embedder wiring, so it stays fast and offline.

The test deliberately avoids the multi-process uvicorn worker; the
in-process ScanRunner is what the SPA talks to in M6.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.web_smoke


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def _make_photo(p: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    from PIL import Image

    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 200), color).save(p, "JPEG")


class _StubDetector:
    """Return one 'face' per image, full bbox."""

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


def _wire_stubs(app) -> None:
    """Replace the default null runner with one that uses stub models."""
    from pick_face.worker.runner import ScanRunner

    layout = app.state.layout
    app.state.runner = ScanRunner(
        layout=layout,
        detector=_StubDetector(),
        embedder=_StubEmbedder(),
        model_version="stub/1",
    )
    app.state.runner.start()


@pytest.fixture()
def client(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from pick_face.api import app as app_mod

    layout = _layout(tmp_pure)
    monkeypatch.setattr(app_mod, "get_layout", lambda: layout)
    new_app = app_mod.create_app(layout=layout, static_dir=None)
    # Wire stub models before the lifespan's make_runner (which would
    # try to load real weights and fail in CI). We replace the runner
    # AFTER the original lifespan's make_runner has stashed its
    # default on app.state, but BEFORE the runner.start() call
    # schedules the polling task.
    original_lifespan = new_app.router.lifespan_context

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def stub_lifespan(app):
        # Manually drive the original lifespan body but interpose
        # between make_runner and runner.start().
        from pick_face.worker.runner import ScanRunner

        app.state.layout = layout
        # Build a stub runner explicitly; this is what we'll keep.
        stub = ScanRunner(
            layout=layout,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            model_version="stub/1",
        )
        app.state.runner = stub
        stub.start()
        try:
            yield
        finally:
            await stub.stop()

    new_app.router.lifespan_context = stub_lifespan
    with TestClient(new_app) as c:
        yield c


def test_init_writes_config_file(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 1: pick-face-web init creates the app root + default config."""
    from pick_face import web_cli

    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "app"))
    rc = web_cli.main(["init"])
    assert rc == 0
    assert (tmp_pure / "app" / "config" / "config.toml").exists()
    assert (tmp_pure / "app" / "data").is_dir()
    assert (tmp_pure / "app" / "cache").is_dir()


def test_config_paths_post_then_list(client, tmp_pure: Path) -> None:
    """Step 2: POST /api/config/paths then GET it back."""
    photos = tmp_pure / "photos"
    photos.mkdir()
    r = client.post("/api/config/paths", json={"path": str(photos), "notes": "smoke"})
    assert r.status_code == 201
    pid = r.json()["id"]

    r = client.get("/api/config/paths")
    assert r.status_code == 200
    listed = r.json()["paths"]
    assert len(listed) == 1
    assert listed[0]["id"] == pid

    r = client.get("/api/config/paths/enabled")
    assert str(photos.resolve()) in r.json()["paths"]


def test_end_to_end_scan_then_query(client, tmp_pure: Path) -> None:
    """Full happy path: scan finishes, /api/persons responds, thumbnail serves.

    Drives the in-process ScanRunner synchronously by calling
    ``run_scan`` directly (the same coroutine the runner uses) instead
    of waiting for the polling task + asyncio.create_task indirection,
    which doesn't work reliably from a TestClient thread (the loop
    only ticks between requests).
    """
    # 1. Seed two photos
    photos = tmp_pure / "photos"
    photos.mkdir()
    _make_photo(photos / "a.jpg", color=(255, 0, 0))
    _make_photo(photos / "b.jpg", color=(0, 255, 0))

    # 2. Whitelist
    r = client.post("/api/config/paths", json={"path": str(photos)})
    assert r.status_code == 201

    # 3. Start scan
    r = client.post("/api/scan/jobs", json={"kind": "full"})
    assert r.status_code == 202
    job_id = r.json()["id"]

    # 4. Drive the scan synchronously via the same work function the
    #    runner uses. We don't go through the runner's polling task
    #    because that requires a running event loop, which TestClient
    #    only ticks between requests.
    from pick_face.worker.scan_worker import run_scan
    from pick_face.service.scan_service import ScanService, ScanProgress, ScanState
    from pick_face.core.images import decode

    layout = client.app.state.layout
    svc = ScanService(layout)
    svc.update_state(job_id, ScanState.RUNNING)

    result = asyncio.run(
        run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=decode,
            model_version="stub/1",
        )
    )
    svc.update_state(job_id, ScanState.DONE)
    svc.update_progress(
        job_id,
        ScanProgress(
            processed=result.processed,
            total=result.total,
            faces=result.faces,
            errors=result.errors,
        ),
    )

    # 5. Confirm job progress recorded both files + 1 face each
    r = client.get(f"/api/scan/jobs/{job_id}")
    progress = r.json()["progress"]
    assert progress["processed"] == 2
    assert progress["faces"] == 2
    assert progress["errors"] == 0

    # 6. The DB has 2 source rows + 2 face rows
    db = client.app.state.layout.db_path
    conn = sqlite3.connect(str(db))
    sources = conn.execute("SELECT COUNT(*) FROM source").fetchone()[0]
    faces = conn.execute("SELECT COUNT(*) FROM face").fetchone()[0]
    conn.close()
    assert sources == 2
    assert faces == 2

    # 7. /api/persons responds (empty because we didn't cluster — the
    #    stub detector doesn't run hnswlib)
    r = client.get("/api/persons")
    assert r.status_code == 200
    assert r.json()["count"] == 0

    # 8. Thumbnail endpoint serves a JPEG for the first photo
    first_id = 1
    r = client.get(f"/api/photos/{first_id}/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0

    # 9. /api/health + /api/ready still green
    r = client.get("/api/health")
    assert r.status_code == 200
    r = client.get("/api/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_scan_404_for_unknown_job(client) -> None:
    """Defensive: bogus job id yields 404, not 500."""
    r = client.get("/api/scan/jobs/no-such-uuid")
    assert r.status_code == 404


def test_photo_404_when_path_under_no_whitelist(
    client, tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A photo whose path is not under any whitelist returns 403, not 200.

    Confirms the defense-in-depth check in photo_service is reachable
    over the HTTP surface.
    """
    # Whitelist one dir
    allowed = tmp_pure / "allowed"
    allowed.mkdir()
    r = client.post("/api/config/paths", json={"path": str(allowed)})
    assert r.status_code == 201

    # Insert a source row pointing outside the whitelist
    layout = client.app.state.layout
    outside = tmp_pure / "outside"
    outside.mkdir()
    outside_p = outside / "p.jpg"
    _make_photo(outside_p)
    from pick_face.store.index import open_db

    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (str(outside_p), "p.jpg", 1, 1.0, "xxh3_64", "h", "active", 1.0, 1.0),
    )
    conn.commit()
    conn.close()
    photo_id = int(cur.lastrowid)

    r = client.get(f"/api/photos/{photo_id}")
    assert r.status_code == 403


def test_file_watcher_creates_job_on_real_filesystem_write(
    client, tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-1: a file write to a whitelisted dir eventually enqueues a scan.

    We bypass the watchdog observation queue by calling
    ``FileWatcher._emit_job`` directly (the same code path watchdog
    events go through after debounce). The test asserts the scan
    service receives a job with ``kind='path_only'`` for the file
    we just wrote.
    """
    from PIL import Image

    photos = tmp_pure / "photos"
    photos.mkdir()
    r = client.post("/api/config/paths", json={"path": str(photos)})
    assert r.status_code == 201

    new_file = photos / "fresh.jpg"
    Image.new("RGB", (40, 40), (10, 20, 30)).save(new_file)

    from pick_face.service.file_watcher import FileWatcher
    from pick_face.service.scan_service import ScanJob, ScanState

    captured: list[dict] = []

    def fake_start(self, *, paths=None, kind="incremental"):
        captured.append({"paths": list(paths) if paths else None, "kind": kind})
        return ScanJob(
            id=f"watch-{len(captured)}",
            state=ScanState.QUEUED,
            kind=kind,
            paths=[str(p) for p in paths] if paths else [],
        )

    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", fake_start
    )

    layout = client.app.state.layout
    # Use a no-op loop — we won't call start(); we drive _emit_job
    # directly which doesn't require a running observer.
    import asyncio

    loop = asyncio.new_event_loop()
    fw = FileWatcher(layout, loop=loop, debounce_sec=0.05)
    try:
        fw._emit_job(new_file)  # noqa: SLF001
        assert len(captured) == 1, captured
        assert captured[0]["kind"] == "path_only"
        assert any(str(new_file) == str(p) for p in (captured[0]["paths"] or []))
    finally:
        loop.close()


def test_polling_creates_periodic_jobs(
    client, tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-2: a polling tick enqueues a ``path_only`` scan job.

    Override ``incremental_interval_sec=1`` (via config) and let the
    PollingScheduler tick at least twice within 2.5s. Each tick
    enqueues a ``path_only`` job through ``ScanService.start``.
    """
    layout = _layout(tmp_pure)
    # Write a config with a 1s polling interval so the suite finishes
    # within the CI budget.
    cfg = layout.config_file
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[scan]\nincremental_interval_sec = 1\n", encoding="utf-8")

    from pick_face.service.scan_service import ScanJob, ScanState
    from pick_face.service.polling_scheduler import PollingScheduler

    captured: list[dict] = []

    def fake_start(self, *, paths=None, kind="incremental"):
        captured.append({"paths": list(paths) if paths else None, "kind": kind})
        return ScanJob(
            id=f"poll-{len(captured)}",
            state=ScanState.QUEUED,
            kind=kind,
            paths=[str(p) for p in paths] if paths else [],
        )

    monkeypatch.setattr(
        "pick_face.service.scan_service.ScanService.start", fake_start
    )

    async def go() -> None:
        sched = PollingScheduler(layout, interval_sec=1)
        sched.start()
        # Resume the APScheduler job — see test_polling_scheduler for
        # why production leaves it paused.
        sched._scheduler.resume_job("polling-scheduler-tick")  # noqa: SLF001
        try:
            await asyncio.sleep(2.5)
        finally:
            await sched.stop()

    asyncio.run(go())
    path_only = [c for c in captured if c["kind"] == "path_only"]
    assert len(path_only) >= 2, f"expected ≥ 2 polls, got {captured}"


def test_photo_delete_then_list_excludes(
    client, tmp_pure: Path
) -> None:
    """M8-T-6: after DELETE /api/photos/{id}, the meta route returns 404.

    End-to-end version of the unit test in
    ``tests/unit/test_soft_delete.py`` — exercises the HTTP path
    rather than the DB layer.
    """
    layout = client.app.state.layout
    img = tmp_pure / "del_smoke.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0stub")

    from pick_face.store.index import open_db

    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(img),
            "del_smoke.jpg",
            img.stat().st_size,
            1.0,
            "xxh3_64",
            "h",
            "active",
            1.0,
            1.0,
        ),
    )
    conn.commit()
    photo_id = int(cur.lastrowid)
    conn.close()

    r = client.delete(f"/api/photos/{photo_id}")
    assert r.status_code == 204
    r = client.get(f"/api/photos/{photo_id}/meta")
    assert r.status_code == 404


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "web_smoke: end-to-end smoke tests for the v3 Web service "
        "(FastAPI + ScanRunner + stub detector/embedder).",
    )
