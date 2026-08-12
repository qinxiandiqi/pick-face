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

    Returns:
        :class:`ScanResult` with totals + per-row face records.
    """
    loop = asyncio.get_running_loop()
    rows, stats = await loop.run_in_executor(
        None,
        lambda: scan(scan_paths, db_rows=db_rows),
    )
    # Only ADD/MOD need detector work. UNCHANGED+DEL are bookkeeping.
    actionable = [r for r in rows if r.kind in (DiffKind.ADD, DiffKind.MOD)]
    total = len(actionable)
    result = ScanResult(total=total, processed=0, faces=0, errors=stats.errors)

    if total == 0:
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
        conn.commit()
    finally:
        conn.close()

    # Second pass (executor): per-file detect + embed + INSERT. We
    # open a fresh connection inside ``_process_one`` because the
    # executor runs on a different thread and sqlite3 forbids
    # cross-thread connection use.
    for _idx, row in enumerate(actionable, start=1):
        try:
            faces = await loop.run_in_executor(
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
        except (OSError, RuntimeError, ValueError):
            # Per docs/01 §1.2 AC-2: a single bad file must not stop
            # the scan; we record the error and move on.
            result.errors += 1
        if progress_cb is not None:
            await progress_cb(result.processed, total, result.faces, result.errors)
    return result


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
) -> list[FaceRecord]:
    """Synchronous per-image work; runs in the default executor.

    Opens its own sqlite3 connection because sqlite3 connections are
    thread-local and the executor may run on any thread.
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
        for face in out:
            conn.execute(
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
        conn.commit()
    finally:
        conn.close()
    return out


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
