"""Scan task orchestration — `docs/03 §3.2` + `docs/06 §1.1`.

A scan task is a single-pass job over one or more whitelisted roots.
The service layer holds the *registry* (one record per task,
persisted to ``scan_jobs/`` as JSON so it survives a crash) and the
*control surface* (start/pause/cancel). The actual file-walking +
embedding work lives in :mod:`pick_face.worker.scan_worker`, which
runs as an asyncio task reading jobs from an in-process queue.

Why a JSON registry and not SQLite? M6 scope: a single FastAPI
process owns all jobs. SQLite-backed cross-process job registry is
M8 work (`docs/06 §3.1 M8-T-7`).

M8 — sidecar ``scan-{id}.events.jsonl``: each running job gets a
JSONL sidecar alongside its JSON record. The scan runner appends
``new_photo`` events, and the cluster worker appends ``new_person``
/ ``merged`` events (`docs/06 §3.1 M8-T-8`). The SSE generator in
``api/scan.py`` tails the sidecar from offset 0 and yields events
to the SPA. The sidecar is created on ``start()`` and deleted on
terminal state transition so a stale file from a prior failed run
does not replay into a fresh consumer.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pick_face.core.errors import ConfigError

from .config_service import ConfigService
from .paths import AppLayout, get_layout


class ScanState(str, Enum):
    """Lifecycle of a scan task.

    State machine:

        queued ──▶ running ──▶ done
                       │
                       ├────▶ failed
                       ├────▶ cancelled
                       └────▶ paused ──▶ running (resume)
    """

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScanProgress:
    """Counters for an in-flight scan.

    These get serialized to ``scan_jobs/<uuid>.json`` so the SSE
    stream can pick up where it left off after a restart. Field
    names mirror ``docs/03 §2.2`` SSE schema.
    """

    processed: int = 0
    total: int = 0
    faces: int = 0
    errors: int = 0
    eta_sec: int | None = None


@dataclass
class ScanJob:
    """A single scan task record."""

    id: str
    state: ScanState
    kind: str  # 'full' | 'incremental' | 'path_only'
    paths: list[str]
    started_at: datetime | None = None
    ended_at: datetime | None = None
    progress: ScanProgress = field(default_factory=ScanProgress)
    error: str | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["started_at"] = self.started_at.isoformat() if self.started_at else None
        payload["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> ScanJob:
        data = json.loads(raw)
        data["state"] = ScanState(data["state"])
        data["started_at"] = (
            datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        )
        data["ended_at"] = (
            datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None
        )
        prog = data.pop("progress", {}) or {}
        return cls(
            id=data["id"],
            state=data["state"],
            kind=data.get("kind", "incremental"),
            paths=list(data.get("paths", [])),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            progress=ScanProgress(**prog),
            error=data.get("error"),
        )


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------


class ScanService:
    """Owns the on-disk registry of scan jobs.

    Every public method is synchronous and persists to JSON; the worker
    task reads jobs via ``active()`` and reports progress via
    ``update_progress()``.
    """

    def __init__(self, layout: AppLayout | None = None) -> None:
        self._layout = layout or get_layout()

    # -- queries -------------------------------------------------------------

    def list_jobs(self) -> list[ScanJob]:
        """Return every persisted job, newest first."""
        jobs: list[ScanJob] = []
        for path in self._iter_job_files():
            try:
                jobs.append(ScanJob.from_json(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                # Corrupt job file — skip rather than crash the API.
                # A separate CLI `prune` can clean these up.
                continue
        jobs.sort(key=lambda j: j.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return jobs

    def get(self, job_id: str) -> ScanJob | None:
        path = self._job_file(job_id)
        if not path.exists():
            return None
        try:
            return ScanJob.from_json(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None

    def active(self) -> ScanJob | None:
        """Return the currently RUNNING job, if any."""
        for job in self.list_jobs():
            if job.state == ScanState.RUNNING:
                return job
        return None

    # -- mutations ------------------------------------------------------------

    def start(
        self,
        paths: Iterable[Path] | None = None,
        kind: str = "incremental",
    ) -> ScanJob:
        """Create a new QUEUED job.

        Args:
            paths: explicit scan roots; if ``None``, all enabled whitelist
                paths are used.
            kind: one of ``full`` / ``incremental`` / ``path_only``.

        Raises:
            ConfigError: if there are no scan paths available.
        """
        if paths is None:
            cfg = ConfigService(self._layout)
            resolved = cfg.enabled_paths()
            if not resolved:
                raise ConfigError("no scan paths configured")
            paths = resolved
        else:
            paths = [Path(p).expanduser().resolve() for p in paths]
        job = ScanJob(
            id=str(uuid.uuid4()),
            state=ScanState.QUEUED,
            kind=kind,
            paths=[str(p) for p in paths],
        )
        self._write(job)
        # M8-T-8: create the empty events sidecar so the SSE generator
        # can start tailing from offset 0 even before any event lands.
        # `missing_ok=True` so two consecutive starts (or a restart)
        # don't error.
        self.events_file(job.id).touch(exist_ok=True)
        return job

    def update_state(self, job_id: str, state: ScanState, error: str | None = None) -> bool:
        """Transition the job to ``state``; optionally record an error message."""
        job = self.get(job_id)
        if job is None:
            return False
        job.state = state
        if state == ScanState.RUNNING and job.started_at is None:
            job.started_at = datetime.now(timezone.utc)
        if state in (ScanState.DONE, ScanState.FAILED, ScanState.CANCELLED):
            job.ended_at = datetime.now(timezone.utc)
        if error:
            job.error = error
        self._write(job)
        # M8-T-8: tear down the events sidecar when the job hits a
        # terminal state. The SSE generator polls every 0.5s and emits
        # `end` on its own when it sees the terminal state; we delete
        # the sidecar *after* the JSON write so a concurrent tail
        # that already observed the terminal state still has the file
        # to drain. SSE consumers tolerate FileNotFoundError as a
        # graceful end-of-stream signal.
        if state in (ScanState.DONE, ScanState.FAILED, ScanState.CANCELLED):
            self.events_file(job_id).unlink(missing_ok=True)
        return True

    def update_progress(self, job_id: str, progress: ScanProgress) -> bool:
        """Persist updated counters (called by the worker task)."""
        job = self.get(job_id)
        if job is None:
            return False
        job.progress = progress
        self._write(job)
        return True

    # -- file handling --------------------------------------------------------

    def _write(self, job: ScanJob) -> None:
        path = self._job_file(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(job.to_json(), encoding="utf-8")

    def _job_file(self, job_id: str) -> Path:
        return self._layout.jobs_dir / f"scan-{job_id}.json"

    def events_file(self, job_id: str) -> Path:
        """Path of the JSONL sidecar that the scan runner + cluster
        worker append to during a running job (`docs/06 §3.1 M8-T-8`).

        The sidecar lives next to ``scan-{id}.json`` so a stale file
        from a prior crashed run lives in the same dir and is easy to
        detect. The SSE generator in ``api/scan.py`` tails this file
        from offset 0 with poll cadence 0.5s.

        Created on ``start()``; deleted on terminal state transition.
        """
        return self._layout.jobs_dir / f"scan-{job_id}.events.jsonl"

    def _iter_job_files(self) -> Iterable[Path]:
        if not self._layout.jobs_dir.exists():
            return iter(())
        return sorted(self._layout.jobs_dir.glob("scan-*.json"))


__all__ = [
    "AppLayout",
    "ScanJob",
    "ScanProgress",
    "ScanService",
    "ScanState",
    "get_layout",
]
