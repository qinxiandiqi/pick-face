"""Tests for worker/scan_worker.py — async run_scan with v2.x schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def test_ensure_schema_idempotent(tmp_pure: Path) -> None:
    from pick_face.worker.scan_worker import ensure_schema

    db_path = _layout(tmp_pure).db_path
    ensure_schema(db_path)
    # Second call must not raise (idempotent).
    ensure_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    for required in ("source", "face", "cluster", "schema_version"):
        assert required in tables


class _StubDetector:
    """Detector stub: returns one face per image at the full image bbox."""

    def detect(self, bgr):  # noqa: ANN001 — numpy array
        from pick_face.ingest.detector import Detection

        h, w = bgr.shape[:2]
        chip = bgr
        return [
            Detection(
                bbox=(0.0, 0.0, float(w), float(h)),
                landmarks=[(w / 2, h / 2)] * 5,
                det_score=0.9,
                chip=chip,
                quality=0.8,
            )
        ]


class _StubEmbedder:
    """Embedder stub: deterministic 4-dim vector from a seed."""

    dim = 4

    def embed(self, chip):  # noqa: ANN001 — numpy array
        import numpy as np

        return np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)


def test_run_scan_writes_faces_to_v2x_schema(tmp_pure: Path) -> None:
    """End-to-end: write a JPEG, run the worker, assert a face row appears."""
    from PIL import Image

    from pick_face.ingest.scanner import DEFAULT_IMAGE_EXTS
    from pick_face.worker.scan_worker import ensure_schema, run_scan

    layout = _layout(tmp_pure)
    photos = tmp_pure / "photos"
    photos.mkdir()
    img = photos / "a.jpg"
    Image.new("RGB", (100, 100), (255, 0, 0)).save(img)
    ensure_schema(layout.db_path)

    class _Dec:
        def __call__(self, path):
            import numpy as np
            return _DecObj(np.zeros((100, 100, 3), dtype="uint8"))

    class _DecObj:
        def __init__(self, bgr):
            self.bgr = bgr

    async def go() -> None:
        return await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=_Dec(),
            model_version="stub/1",
        )

    import asyncio

    result = asyncio.run(go())
    assert result.processed == 1
    assert result.faces == 1
    assert result.errors == 0

    conn = sqlite3.connect(str(layout.db_path))
    face_count = conn.execute("SELECT COUNT(*) FROM face").fetchone()[0]
    source_count = conn.execute("SELECT COUNT(*) FROM source").fetchone()[0]
    conn.close()
    assert face_count == 1
    assert source_count == 1
    _ = DEFAULT_IMAGE_EXTS  # silence unused-import linter


def test_run_scan_per_file_errors_dont_stop_scan(tmp_pure: Path) -> None:
    """docs/01 §1.2 AC-2: a single bad file must not stop the scan."""
    from PIL import Image

    from pick_face.worker.scan_worker import ensure_schema, run_scan

    layout = _layout(tmp_pure)
    photos = tmp_pure / "photos"
    photos.mkdir()
    Image.new("RGB", (100, 100), (255, 0, 0)).save(photos / "a.jpg")
    Image.new("RGB", (100, 100), (0, 255, 0)).save(photos / "b.jpg")
    ensure_schema(layout.db_path)

    class _FlakyDetector:
        def __init__(self):
            self.calls = 0

        def detect(self, bgr):
            self.calls += 1
            if self.calls == 1:
                raise OSError("simulated bad image")
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

    class _Dec:
        def __call__(self, path):
            import numpy as np
            return _DecObj(np.zeros((100, 100, 3), dtype="uint8"))

    class _DecObj:
        def __init__(self, bgr):
            self.bgr = bgr

    async def go() -> None:
        return await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_FlakyDetector(),
            embedder=_StubEmbedder(),
            decoder=_Dec(),
            model_version="stub/1",
        )

    import asyncio

    result = asyncio.run(go())
    # 2 files processed, 1 had an error, 1 face written
    assert result.processed == 1
    assert result.faces == 1
    assert result.errors == 1


def test_progress_callback_receives_updates(tmp_pure: Path) -> None:
    from PIL import Image

    from pick_face.worker.scan_worker import ensure_schema, run_scan

    layout = _layout(tmp_pure)
    photos = tmp_pure / "photos"
    photos.mkdir()
    Image.new("RGB", (100, 100), (255, 0, 0)).save(photos / "a.jpg")
    ensure_schema(layout.db_path)

    class _Dec:
        def __call__(self, path):
            import numpy as np
            return _DecObj(np.zeros((100, 100, 3), dtype="uint8"))

    class _DecObj:
        def __init__(self, bgr):
            self.bgr = bgr

    updates: list[tuple[int, int, int, int]] = []

    async def cb(p, t, f, e):
        updates.append((p, t, f, e))

    async def go() -> None:
        return await run_scan(
            scan_paths=[photos],
            db_path=layout.db_path,
            detector=_StubDetector(),
            embedder=_StubEmbedder(),
            decoder=_Dec(),
            model_version="stub/1",
            progress_cb=cb,
        )

    import asyncio

    asyncio.run(go())
    assert updates
    last = updates[-1]
    assert last[0] == 1  # processed
    assert last[1] == 1  # total
    assert last[2] == 1  # faces
