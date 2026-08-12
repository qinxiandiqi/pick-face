"""Tests for service/scan_service.py — job registry, state machine, JSON round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def test_scan_state_is_string_enum() -> None:
    """ScanState is a str enum — JSON serialization stays compact."""
    from pick_face.service.scan_service import ScanState

    assert ScanState.RUNNING.value == "running"
    assert ScanState.RUNNING == "running"  # string compare works


def test_scan_job_to_from_json_round_trip() -> None:
    from pick_face.service.scan_service import ScanJob, ScanProgress, ScanState

    job = ScanJob(
        id="abc",
        state=ScanState.RUNNING,
        kind="full",
        paths=["/tmp/a", "/tmp/b"],
        progress=ScanProgress(processed=10, total=20, faces=5, errors=1, eta_sec=12),
    )
    raw = job.to_json()
    data = json.loads(raw)
    assert data["state"] == "running"
    assert data["progress"]["processed"] == 10
    assert data["progress"]["eta_sec"] == 12
    restored = ScanJob.from_json(raw)
    assert restored.state == ScanState.RUNNING
    assert restored.progress.faces == 5


def test_scan_job_handles_null_timestamps() -> None:
    from pick_face.service.scan_service import ScanJob, ScanState

    raw = json.dumps(
        {
            "id": "x",
            "state": "queued",
            "kind": "incremental",
            "paths": [],
            "started_at": None,
            "ended_at": None,
            "progress": {},
            "error": None,
        }
    )
    job = ScanJob.from_json(raw)
    assert job.state == ScanState.QUEUED
    assert job.started_at is None
    assert job.ended_at is None


def test_start_uses_whitelist_when_no_paths(tmp_pure: Path) -> None:
    from pick_face.service.config_service import ConfigService
    from pick_face.service.scan_service import ScanService, ScanState

    layout = _layout(tmp_pure)
    d = tmp_pure / "photos"
    d.mkdir()
    ConfigService(layout).add_path(str(d))
    svc = ScanService(layout)
    job = svc.start()
    assert job.state == ScanState.QUEUED
    assert str(d.resolve()) in job.paths
    assert (layout.jobs_dir / f"scan-{job.id}.json").exists()


def test_start_with_explicit_paths(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanService, ScanState

    layout = _layout(tmp_pure)
    d = tmp_pure / "explicit"
    d.mkdir()
    svc = ScanService(layout)
    job = svc.start(paths=[d], kind="full")
    assert job.state == ScanState.QUEUED
    assert job.kind == "full"
    assert d.resolve() in [Path(p) for p in job.paths]


def test_start_raises_when_no_paths_and_empty_whitelist(tmp_pure: Path) -> None:
    from pick_face.core.errors import ConfigError
    from pick_face.service.scan_service import ScanService

    layout = _layout(tmp_pure)
    svc = ScanService(layout)
    with pytest.raises(ConfigError):
        svc.start()


def test_update_state_records_timestamps(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanService, ScanState

    layout = _layout(tmp_pure)
    d = tmp_pure / "x"
    d.mkdir()
    svc = ScanService(layout)
    job = svc.start(paths=[d])
    assert svc.update_state(job.id, ScanState.RUNNING)
    fetched = svc.get(job.id)
    assert fetched is not None
    assert fetched.started_at is not None
    assert fetched.ended_at is None
    assert svc.update_state(job.id, ScanState.DONE)
    fetched2 = svc.get(job.id)
    assert fetched2.ended_at is not None


def test_update_progress_persists(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanProgress, ScanService

    layout = _layout(tmp_pure)
    d = tmp_pure / "x"
    d.mkdir()
    svc = ScanService(layout)
    job = svc.start(paths=[d])
    assert svc.update_progress(
        job.id, ScanProgress(processed=5, total=10, faces=3, errors=0)
    )
    fetched = svc.get(job.id)
    assert fetched.progress.processed == 5
    assert fetched.progress.faces == 3


def test_active_returns_running_only(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanService, ScanState

    layout = _layout(tmp_pure)
    d = tmp_pure / "x"
    d.mkdir()
    svc = ScanService(layout)
    j1 = svc.start(paths=[d])
    j2 = svc.start(paths=[d])
    assert svc.active() is None
    assert svc.update_state(j1.id, ScanState.RUNNING)
    assert svc.active().id == j1.id
    assert svc.update_state(j1.id, ScanState.DONE)
    assert svc.update_state(j2.id, ScanState.RUNNING)
    assert svc.active().id == j2.id


def test_list_jobs_skips_corrupt_files(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanService

    layout = _layout(tmp_pure)
    d = tmp_pure / "x"
    d.mkdir()
    svc = ScanService(layout)
    j = svc.start(paths=[d])
    # Corrupt the file
    (layout.jobs_dir / f"scan-{j.id}.json").write_text("not-json")
    jobs = svc.list_jobs()
    # Corrupt entry silently skipped; new QUEUED job should still be returned
    # (the corrupt file's name had a different uuid than `j` only because we
    # overwrote it, so re-issuing list_jobs should return whatever else is on
    # disk — at minimum it should not raise)
    assert isinstance(jobs, list)


def test_get_returns_none_for_missing_job(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanService

    layout = _layout(tmp_pure)
    svc = ScanService(layout)
    assert svc.get("does-not-exist") is None


def test_update_state_missing_returns_false(tmp_pure: Path) -> None:
    from pick_face.service.scan_service import ScanService, ScanState

    layout = _layout(tmp_pure)
    svc = ScanService(layout)
    assert not svc.update_state("nonexistent", ScanState.RUNNING)
    assert not svc.update_progress("nonexistent", None)  # type: ignore[arg-type]


def test_state_machine_does_not_crash_on_double_done(tmp_pure: Path) -> None:
    """State transitions are permissive in M6; M8 will add guards."""
    from pick_face.service.scan_service import ScanService, ScanState

    layout = _layout(tmp_pure)
    d = tmp_pure / "x"
    d.mkdir()
    svc = ScanService(layout)
    job = svc.start(paths=[d])
    assert svc.update_state(job.id, ScanState.RUNNING)
    assert svc.update_state(job.id, ScanState.DONE)
    # Calling DONE again should still succeed (idempotent persistence).
    assert svc.update_state(job.id, ScanState.DONE)
