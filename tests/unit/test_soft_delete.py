"""Tests for soft-delete behaviour (M8-T-6).

Soft-delete has two flavours in M8:

1. ``run_scan`` DEL pass: a file present in the DB then deleted on
   disk gets ``status='missing'`` on the next scan (``scan_worker.py``).
2. ``DELETE /api/photos/{id}`` HTTP route: a user-driven soft-delete
   sets ``status='removed'`` and subsequent metadata reads return 404.

Both states are excluded from :class:`PersonService` aggregations so
the SPA doesn't show "ghost" photos.
"""

from __future__ import annotations

import asyncio
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


def _seed_source(conn: sqlite3.Connection, *, path: str, status: str = "active") -> int:
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
        "                  first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
        (path, path.rsplit("/", 1)[-1], 1, 1.0, "h", status),
    )
    return int(cur.lastrowid)


class _StubDetector:
    """One face per image, full bbox."""

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


class _Decoder:
    def __call__(self, path):
        import numpy as np
        return _DecObj(np.zeros((10, 10, 3), dtype="uint8"))


class _DecObj:
    def __init__(self, bgr):
        self.bgr = bgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _source_db_rows(db_path: Path) -> dict[str, tuple[int, float, str]]:
    """Read the existing ``source`` table into the ``db_rows`` map shape
    expected by ``run_scan`` / ``scanner.scan``.

    Needed because ``run_scan`` only sees DEL rows when the caller
    pre-loads this map (matches the v2.x CLI flow).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        out: dict[str, tuple[int, float, str]] = {}
        for path, size, mtime, h in conn.execute(
            "SELECT path, size, mtime, hash FROM source"
        ).fetchall():
            out[str(Path(path).resolve())] = (int(size), float(mtime), str(h))
        return out
    finally:
        conn.close()


@pytest.fixture()
def client(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch):
    """A FastAPI TestClient pointed at a fresh temp layout.

    Same shape as the ``client`` fixture in ``tests/unit/test_api_routes.py``
    — duplicated here so this module stays self-contained.
    """
    from fastapi.testclient import TestClient

    from pick_face.api import app as app_mod
    from pick_face.service import paths as paths_mod

    layout = _layout(tmp_pure)
    monkeypatch.setattr(app_mod, "get_layout", lambda: layout)
    monkeypatch.setattr(paths_mod, "get_layout", lambda: layout)
    new_app = app_mod.create_app(layout=layout, static_dir=None)
    with TestClient(new_app) as c:
        yield c
    monkeypatch.undo()
    app_mod.app = app_mod.create_app(layout=layout, static_dir=None)


def test_scan_marks_missing_files(tmp_pure: Path) -> None:
    """M8-T-6: a file removed from disk between scans gets ``status='missing'``.

    First scan writes the source row as ``active``. We delete the file
    on disk, run a second scan with ``db_rows`` pre-loaded so the
    scanner's DEL pass fires, and assert the row's status flipped to
    ``missing``.
    """
    from PIL import Image

    from pick_face.worker.scan_worker import ensure_schema, run_scan

    layout = _layout(tmp_pure)
    photos = tmp_pure / "photos"
    photos.mkdir()
    img = photos / "a.jpg"
    Image.new("RGB", (50, 50), (1, 2, 3)).save(img)
    ensure_schema(layout.db_path)

    async def run_once(db_rows=None) -> Any:
        return await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=_Decoder(),
            model_version="stub/1",
            db_rows=db_rows,
        )

    # First scan: file present → status='active'.
    asyncio.run(run_once())
    conn = sqlite3.connect(str(layout.db_path))
    status_first = conn.execute(
        "SELECT status FROM source WHERE path = ?", (str(img),)
    ).fetchone()[0]
    assert status_first == "active"

    # Remove the file from disk.
    img.unlink()

    # Second scan: file vanished → DEL row in stats + status flip.
    result = asyncio.run(run_once(db_rows=_source_db_rows(layout.db_path)))
    assert str(img) in result.soft_deleted_paths

    status_second = conn.execute(
        "SELECT status FROM source WHERE path = ?", (str(img),)
    ).fetchone()[0]
    conn.close()
    assert status_second == "missing"


def test_api_delete_sets_status_removed(client, tmp_pure: Path) -> None:
    """M8-T-6: ``DELETE /api/photos/{id}`` returns 204 and the meta endpoint 404s."""
    from pick_face.store.index import open_db

    layout = client.app.state.layout
    img_path = tmp_pure / "del.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0stub")

    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
        "                  first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, 'active', 0, 0)",
        (str(img_path), "del.jpg", img_path.stat().st_size, 1.0, "h"),
    )
    photo_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    # DELETE → 204.
    r = client.delete(f"/api/photos/{photo_id}")
    assert r.status_code == 204, r.text

    # Subsequent /meta → 404 (status='removed' filtered out).
    r = client.get(f"/api/photos/{photo_id}/meta")
    assert r.status_code == 404

    # DB row still exists with status='removed' (so M9 review UI can undo).
    conn = open_db(layout.db_path)
    row = conn.execute(
        "SELECT status FROM source WHERE id = ?", (photo_id,)
    ).fetchone()
    conn.close()
    assert row is not None and row[0] == "removed"


def test_person_excludes_removed_photos(tmp_pure: Path) -> None:
    """A face whose photo was user-removed is excluded from ``list_persons``.

    The cluster row stays (face_count reflects only active sources);
    the SPA waterfall won't surface ghost thumbnails.
    """
    from pick_face.store.index import open_db
    from pick_face.service.person_service import PersonService

    layout = _layout(tmp_pure)
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO cluster(id, label, size, created_at, updated_at) "
        "VALUES (1, 'person-0001', 0, 0, 0)"
    )
    cluster_id = int(cur.lastrowid)
    # 1 active face + 1 removed face → face_count should be 1.
    sid1 = _seed_source(conn, path="/tmp/a.jpg")
    sid2 = _seed_source(conn, path="/tmp/b.jpg", status="removed")
    conn.execute(
        "INSERT INTO face(source_id, cluster_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  det_score, quality, embedding, model_version) "
        "VALUES (?, ?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
        (sid1, cluster_id, b"\x00" * 16),
    )
    conn.execute(
        "INSERT INTO face(source_id, cluster_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  det_score, quality, embedding, model_version) "
        "VALUES (?, ?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
        (sid2, cluster_id, b"\x00" * 16),
    )
    conn.commit()
    conn.close()

    persons = PersonService(layout).list_persons()
    assert len(persons) == 1
    assert persons[0].face_count == 1
    assert persons[0].photo_count == 1


def test_person_excludes_missing_photos(tmp_pure: Path) -> None:
    """A face whose source photo vanished from disk is excluded from face_count.

    Same shape as :func:`test_person_excludes_removed_photos` but with
    ``status='missing'`` to verify the filter applies to *both*
    soft-delete states.
    """
    from pick_face.store.index import open_db
    from pick_face.service.person_service import PersonService

    layout = _layout(tmp_pure)
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO cluster(id, label, size, created_at, updated_at) "
        "VALUES (2, 'person-0002', 0, 0, 0)"
    )
    cluster_id = int(cur.lastrowid)
    sid_active = _seed_source(conn, path="/tmp/x.jpg", status="active")
    sid_missing = _seed_source(conn, path="/tmp/y.jpg", status="missing")
    conn.execute(
        "INSERT INTO face(source_id, cluster_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  det_score, quality, embedding, model_version) "
        "VALUES (?, ?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
        (sid_active, cluster_id, b"\x00" * 16),
    )
    conn.execute(
        "INSERT INTO face(source_id, cluster_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  det_score, quality, embedding, model_version) "
        "VALUES (?, ?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
        (sid_missing, cluster_id, b"\x00" * 16),
    )
    conn.commit()
    conn.close()

    persons = PersonService(layout).list_persons()
    assert len(persons) == 1
    assert persons[0].face_count == 1
    assert persons[0].photo_count == 1


def test_scan_worker_reports_del_count(tmp_pure: Path) -> None:
    """M8-T-6: ``ScanResult.soft_deleted_paths`` is populated with the DEL row path.

    Seed two photos, delete one before the scan, run; assert exactly
    one entry in ``soft_deleted_paths`` matches the deleted file.
    """
    from PIL import Image

    from pick_face.worker.scan_worker import ensure_schema, run_scan

    layout = _layout(tmp_pure)
    photos = tmp_pure / "photos"
    photos.mkdir()
    keep = photos / "keep.jpg"
    drop = photos / "drop.jpg"
    Image.new("RGB", (30, 30), (10, 10, 10)).save(keep)
    Image.new("RGB", (30, 30), (20, 20, 20)).save(drop)
    ensure_schema(layout.db_path)

    async def seed():
        # First scan: both files → active.
        await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=_Decoder(),
            model_version="stub/1",
        )

    asyncio.run(seed())

    # Remove one file from disk.
    drop.unlink()

    async def rescan():
        return await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=_Decoder(),
            model_version="stub/1",
            db_rows=_source_db_rows(layout.db_path),
        )

    result = asyncio.run(rescan())
    assert len(result.soft_deleted_paths) == 1
    assert str(drop) in result.soft_deleted_paths