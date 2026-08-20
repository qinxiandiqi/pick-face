"""Scan worker — consume a ScanJob, run scanner+detector+embedder.

The worker is a pure async function: it takes a job, walks its scan
roots, calls the v2.x ``scanner.scan()`` for the diff, then for each
ADD/MOD file runs detector+embedder and writes faces into the
``face`` table (v2.x schema, see ``store/index.py``). Per-image
failures are recorded into ``progress.errors`` and the scan keeps
going — see ``docs/01 §1.2 AC-2``.

Why reuse v2.x scanner/detector/embedder directly? Because the v2.x
``scan()`` function already does (size, mtime, hash) diffing, content
hashing, and ext whitelisting — exactly what the Web service needs.
M6 doesn't change the algorithm; M6 changes the *transport*.

The worker is decoupled from HTTP and the SQLite session; the runner
(see :mod:`pick_face.worker.runner`) calls it inside an asyncio task
and persists progress via ``ScanService.update_progress``.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pick_face.ingest.detector import Detector
from pick_face.ingest.embedder import Embedder
from pick_face.ingest.scanner import (
    DEFAULT_IMAGE_EXTS,
    DiffKind,
    ScanRow,
    ScanStats,
    scan,
)
from pick_face.store.index import PRAGMAS, SCHEMA_V1_SQL, open_db

# ---------------------------------------------------------------------------
# Lightweight face record — matches v2.x `face` table layout so we can
# INSERT directly. We intentionally don't import the full store/index_hnsw
# machinery here (HNSW is M8 work); M6 just writes faces into SQLite.
# ---------------------------------------------------------------------------


@dataclass
class FaceRecord:
    """A single face row ready for INSERT into the ``face`` table.

    Mirrors ``store/index.py SCHEMA_V1_SQL`` column order.
    """

    bbox_x1: float
    bbox_y1: float
    bbox_x2: float
    bbox_y2: float
    det_score: float
    lmk_x0: float
    lmk_y0: float
    lmk_x1: float
    lmk_y1: float
    lmk_x2: float
    lmk_y2: float
    lmk_x3: float
    lmk_y3: float
    lmk_x4: float
    lmk_y4: float
    quality: float
    embedding: bytes
    model_version: str
    source_id: int


# ---------------------------------------------------------------------------
# Detection + embedding runner
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Outcome of one worker run; consumed by ScanService.update_progress."""

    total: int = 0
    processed: int = 0
    faces: int = 0
    errors: int = 0
    rows: list[tuple[ScanRow, list[FaceRecord]]] = field(default_factory=list)
    # M8-T-4 / M8-T-8: per-face row IDs returned to the runner so it
    # can notify the cluster worker + append ``new_photo`` events to
    # the scan's events sidecar. Empty for runs that processed zero
    # faces.
    face_ids: list[int] = field(default_factory=list)
    # M8-T-6: paths the scanner detected as ``DiffKind.DEL`` and the
    # worker marked ``status='missing'`` in SQLite. Callers (the
    # runner, integration tests) use this to verify soft-delete
    # bookkeeping without re-running the diff.
    soft_deleted_paths: list[str] = field(default_factory=list)


class ImageDecoder(Protocol):
    """Protocol for the image decoder; provided by the runner.

    v2.x's ``core.images.decode`` returns ``(bgr_for_detector, rgb_for_thumb)``.
    The worker only needs ``bgr``.
    """

    def __call__(self, path: Path) -> object: ...


async def run_scan(
    *,
    scan_paths: list[Path],
    db_path: Path,
    detector: Detector,
    embedder: Embedder,
    decoder: ImageDecoder,
    model_version: str,
    db_rows: dict[str, tuple[int, float, str]] | None = None,
    progress_cb=None,
    job_id: str | None = None,
    events_file: Path | None = None,
) -> ScanResult:
    """Execute one scan pass over ``scan_paths`` and persist faces.

    Args:
        scan_paths: list of resolved scan roots.
        db_path: SQLite database path (will be opened + schema-ensured).
        detector: v2.x Detector instance (already loaded).
        embedder: v2.x Embedder instance (already loaded).
        decoder: callable turning a Path → object with ``.bgr`` ndarray.
        model_version: stored on each face row for HNSW rebuild filtering.
        db_rows: optional pre-existing (size, mtime, hash) map for diff.
        progress_cb: optional async callable(processed, total, faces, errors).
        job_id: M8-T-8 — when set, ``new_photo`` events are appended to
            ``events_file`` (one JSON line per scanned photo that
            yielded ≥ 1 face).
        events_file: M8-T-8 — path to the JSONL sidecar; when ``None``
            the scan runs without emitting events (CLI mode).

    Returns:
        :class:`ScanResult` with totals + per-row face records +
        ``face_ids`` + ``soft_deleted_paths``.
    """
    loop = asyncio.get_running_loop()
    # M8-T-6: pre-load ``db_rows`` from the ``source`` table when the
    # caller doesn't supply one. Without this, the scanner has no
    # baseline against which to compute ``DiffKind.DEL`` — files
    # that vanished from disk since the last scan would never be
    # detected as missing. Production callers (the runner) pass
    # ``db_rows=None``; integration tests sometimes pass an explicit
    # map to keep the fixture deterministic.
    if db_rows is None:
        db_rows = await loop.run_in_executor(None, _load_db_rows, db_path)
    rows, stats = await loop.run_in_executor(
        None,
        lambda: scan(scan_paths, db_rows=db_rows),
    )
    # Only ADD/MOD need detector work. UNCHANGED+DEL are bookkeeping.
    actionable = [r for r in rows if r.kind in (DiffKind.ADD, DiffKind.MOD)]
    total = len(actionable)
    del_rows = [r for r in rows if r.kind == DiffKind.DEL]
    soft_deleted_paths = [str(r.abs_path) for r in del_rows]
    result = ScanResult(total=total, processed=0, faces=0, errors=stats.errors)

    if total == 0 and not del_rows:
        if progress_cb is not None:
            await progress_cb(0, 0, 0, stats.errors)
        return result

    # First pass (in the event-loop thread): ensure source rows exist
    # for every actionable path. We use ``INSERT OR IGNORE`` so
    # re-scans don't violate UNIQUE(path). We close this connection
    # before crossing into the executor (sqlite3 connections are
    # thread-local).
    conn = open_db(db_path)
    try:
        for row in actionable:
            conn.execute(
                """
                INSERT OR IGNORE INTO source
                    (path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen)
                VALUES (?, ?, ?, ?, 'xxh3_64', ?, 'active', ?, ?)
                """,
                (
                    str(row.abs_path),
                    str(row.rel_path),
                    row.size,
                    row.mtime,
                    row.hash or "",
                    row.mtime,
                    row.mtime,
                ),
            )
        # M8-T-6: DEL pass — files that vanished from disk since the
        # last scan get status='missing' so the Persons API excludes
        # their faces and the SPA waterfall doesn't show ghost
        # thumbnails.
        if del_rows:
            for row in del_rows:
                conn.execute(
                    "UPDATE source SET status = 'missing' WHERE path = ?",
                    (str(row.abs_path),),
                )
        conn.commit()
    finally:
        conn.close()

    # Second pass (executor): per-file detect + embed + INSERT. We
    # open a fresh connection inside ``_process_one`` because the
    # executor runs on a different thread and sqlite3 forbids
    # cross-thread connection use.
    for _idx, row in enumerate(actionable, start=1):
        try:
            faces, face_ids = await loop.run_in_executor(
                None,
                _process_one,
                row,
                detector,
                embedder,
                decoder,
                model_version,
                db_path,
            )
            result.processed += 1
            result.faces += len(faces)
            if faces:
                result.rows.append((row, faces))
                result.face_ids.extend(face_ids)
                # M8-T-8: sidecar append for `new_photo` events. We
                # reuse the source_id we already resolved inside
                # ``_process_one`` instead of re-querying the DB.
                if events_file is not None:
                    _append_new_photo_event(
                        events_file,
                        source_id=int(faces[0].source_id),
                        face_count=len(faces),
                    )
        except (OSError, RuntimeError, ValueError):
            # Per docs/01 §1.2 AC-2: a single bad file must not stop
            # the scan; we record the error and move on.
            result.errors += 1
        if progress_cb is not None:
            await progress_cb(result.processed, total, result.faces, result.errors)
    result.soft_deleted_paths = soft_deleted_paths
    return result


def _append_new_photo_event(events_file: Path, *, source_id: int, face_count: int) -> None:
    """Best-effort append of a ``new_photo`` line to the sidecar.

    Silently drops on OS errors — the sidecar is a UX hint, not a
    durability-critical ledger. The face rows are already persisted
    in SQLite by the time we get here.
    """
    if not source_id or face_count <= 0:
        return
    try:
        with events_file.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"type": "new_photo", "photo_id": int(source_id), "face_count": int(face_count)}
                )
                + "\n"
            )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _process_one(
    row: ScanRow,
    detector: Detector,
    embedder: Embedder,
    decoder: ImageDecoder,
    model_version: str,
    db_path: Path,
) -> tuple[list[FaceRecord], list[int]]:
    """Synchronous per-image work; runs in the default executor.

    Opens its own sqlite3 connection because sqlite3 connections are
    thread-local and the executor may run on any thread.

    Returns ``(faces, face_ids)`` where ``face_ids[i]`` is the SQLite
    rowid of the inserted face matching ``faces[i]``. Both lists are
    empty when no faces were detected.
    """
    decoded = decoder(row.abs_path)
    bgr = getattr(decoded, "bgr", None)
    if bgr is None:
        raise ValueError(f"decoder returned no .bgr for {row.abs_path}")
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            "SELECT id FROM source WHERE path = ?",
            (str(row.abs_path),),
        )
        source_id_row = cur.fetchone()
        if source_id_row is None:
            raise RuntimeError(f"source row missing for {row.abs_path}")
        source_id = int(source_id_row[0])

        detections = detector.detect(bgr)
        out: list[FaceRecord] = []
        for det in detections:
            try:
                emb = embedder.embed(det.chip)
            except (ValueError, RuntimeError):
                continue
            # Pad / truncate landmarks to 5 points; defensive against packs
            # returning fewer / more landmarks.
            lmk = list(det.landmarks) if hasattr(det, "landmarks") else []
            flat: list[float] = []
            for i in range(5):
                if i < len(lmk):
                    x, y = lmk[i]
                    flat.extend([float(x), float(y)])
                else:
                    flat.extend([0.0, 0.0])
            out.append(
                FaceRecord(
                    bbox_x1=float(det.bbox[0]),
                    bbox_y1=float(det.bbox[1]),
                    bbox_x2=float(det.bbox[2]),
                    bbox_y2=float(det.bbox[3]),
                    det_score=float(det.det_score),
                    lmk_x0=flat[0],
                    lmk_y0=flat[1],
                    lmk_x1=flat[2],
                    lmk_y1=flat[3],
                    lmk_x2=flat[4],
                    lmk_y2=flat[5],
                    lmk_x3=flat[6],
                    lmk_y3=flat[7],
                    lmk_x4=flat[8],
                    lmk_y4=flat[9],
                    quality=float(getattr(det, "quality", 0.5)),
                    embedding=emb.astype("float32").tobytes(),
                    model_version=model_version,
                    source_id=source_id,
                )
            )
        face_ids: list[int] = []
        for face in out:
            cur = conn.execute(
                """
                INSERT INTO face (
                    source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, det_score,
                    lmk_x0, lmk_y0, lmk_x1, lmk_y1, lmk_x2, lmk_y2,
                    lmk_x3, lmk_y3, lmk_x4, lmk_y4, quality,
                    embedding, model_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    face.source_id,
                    face.bbox_x1,
                    face.bbox_y1,
                    face.bbox_x2,
                    face.bbox_y2,
                    face.det_score,
                    face.lmk_x0,
                    face.lmk_y0,
                    face.lmk_x1,
                    face.lmk_y1,
                    face.lmk_x2,
                    face.lmk_y2,
                    face.lmk_x3,
                    face.lmk_y3,
                    face.lmk_x4,
                    face.lmk_y4,
                    face.quality,
                    face.embedding,
                    face.model_version,
                ),
            )
            face_ids.append(int(cur.lastrowid))
        conn.commit()
    finally:
        conn.close()
    return out, face_ids


def ensure_schema(db_path: Path) -> None:
    """Open + ensure the v2.x schema. Public so the CLI / runner can prime."""
    conn = open_db(db_path)
    try:
        _ensure_schema(conn)
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Re-execute the v2.x schema statements (idempotent)."""
    for stmt in SCHEMA_V1_SQL:
        conn.execute(stmt)
    # Schema migrations table is part of SCHEMA_V1_SQL.
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
        (1, _now()),
    )
    conn.commit()


def _now() -> float:
    """Wall-clock seconds; mirrors store/index._now()."""
    import time

    return time.time()


def _load_db_rows(db_path: Path) -> dict[str, tuple[int, float, str]]:
    """Read all known ``source`` rows into the (size, mtime, hash) shape
    that :func:`ingest.scanner.scan` expects.

    Hash column may be empty for v2.x inserts that pre-date the
    xxh3 hash column — we substitute an empty string so the scanner
    still emits a sane diff (it uses hash only as a tie-breaker when
    size+mtime collide).
    """
    conn = open_db(db_path)
    try:
        cur = conn.execute("SELECT path, size, mtime, hash FROM source")
        out: dict[str, tuple[int, float, str]] = {}
        for path, size, mtime, h in cur.fetchall():
            out[str(path)] = (int(size), float(mtime), str(h or ""))
        return out
    finally:
        conn.close()


__all__ = [
    "DEFAULT_IMAGE_EXTS",
    "FaceRecord",
    "ImageDecoder",
    "PRAGMAS",
    "ScanResult",
    "ScanStats",
    "ensure_schema",
    "run_scan",
]
