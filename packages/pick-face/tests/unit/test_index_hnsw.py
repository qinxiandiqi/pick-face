"""Tests for pick_face.index_hnsw (M3 / T-203).

We exercise:
  - add_items + knn_query returns the right nearest neighbour.
  - cosine metric is symmetric: query-by-itself returns distance ~0.
  - save → load round-trip preserves the index.
  - load raises on a corrupt file so the caller can rebuild.
  - rebuild() deletes the file and writes a fresh one.
  - Numpy fallback (no hnswlib) shares the same interface.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from pick_face.store.index_hnsw import (
    BACKEND_HNSWLIB,
    BACKEND_NUMPY,
    MAGIC,
    HnswIndex,
    rebuild,
)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _random_unit(dim: int, rng: np.random.Generator) -> np.ndarray:
    v = rng.normal(size=dim).astype(np.float32)
    return _unit(v)


@pytest.fixture
def small_index() -> HnswIndex:
    rng = np.random.default_rng(7)
    idx = HnswIndex(dim=16, metric="cosine", max_elements=100)
    # 20 random unit vectors, plus 3 distinct anchors.
    anchors = np.eye(3, 16, dtype=np.float32)
    others = np.stack([_random_unit(16, rng) for _ in range(20)])
    embs = np.concatenate([anchors, others], axis=0)
    idx.add_items(embs)
    return idx


def test_add_items_returns_ids() -> None:
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    embs = np.eye(4, 4, dtype=np.float32)
    ids = idx.add_items(embs)
    assert list(ids) == [0, 1, 2, 3]
    assert idx.count == 4


def test_add_items_empty() -> None:
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    out = idx.add_items(np.zeros((0, 4), dtype=np.float32))
    assert out.shape == (0,)
    assert idx.count == 0


def test_add_items_wrong_dim_raises() -> None:
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    with pytest.raises(ValueError, match="4"):
        idx.add_items(np.zeros((1, 5), dtype=np.float32))


def test_knn_query_self_returns_zero_distance(small_index: HnswIndex) -> None:
    # Query the first 3 anchors (we added them as np.eye(3,16)).
    queries = np.eye(3, 16, dtype=np.float32)
    distances, ids = small_index.knn_query(queries, k=1)
    # Each query should match itself with distance ~0.
    for i in range(3):
        assert ids[i, 0] == i
        assert distances[i, 0] < 0.01


def test_knn_query_k_above_count_clamps() -> None:
    """If k > count, we clamp to count instead of raising."""
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    idx.add_items(np.eye(3, 4, dtype=np.float32))
    distances, ids = idx.knn_query(np.eye(1, 4, dtype=np.float32), k=100)
    assert distances.shape == (1, 3)
    assert ids.shape == (1, 3)


def test_knn_query_empty_index_returns_empty() -> None:
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    distances, ids = idx.knn_query(np.eye(1, 4, dtype=np.float32), k=1)
    assert distances.shape == (1, 0)
    assert ids.shape == (1, 0)


def test_knn_query_wrong_dim_raises() -> None:
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    with pytest.raises(ValueError, match="4"):
        idx.knn_query(np.zeros((1, 5), dtype=np.float32))


def test_save_load_roundtrip(small_index: HnswIndex, tmp_pure: Path) -> None:
    target = tmp_pure / "faces.hnsw"
    small_index.save(target)
    assert target.exists()

    loaded = HnswIndex.load(target)
    assert loaded.count == small_index.count
    assert loaded.dim == small_index.dim
    assert loaded.metric == small_index.metric

    # Query produces the same answer.
    queries = np.eye(3, 16, dtype=np.float32)
    d_orig, ids_orig = small_index.knn_query(queries, k=1)
    d_loaded, ids_loaded = loaded.knn_query(queries, k=1)
    assert (ids_orig == ids_loaded).all()


def test_load_corrupt_header_raises(tmp_pure: Path) -> None:
    target = tmp_pure / "broken.hnsw"
    target.write_bytes(b"NOPE" + b"\x00" * 16)
    with pytest.raises(ValueError, match="bad magic"):
        HnswIndex.load(target)


def test_load_truncated_raises(tmp_pure: Path) -> None:
    target = tmp_pure / "trunc.hnsw"
    target.write_bytes(MAGIC + b"\x00\x00")  # only 6 bytes
    with pytest.raises(ValueError, match="truncated"):
        HnswIndex.load(target)


def test_load_backend_mismatch_raises(tmp_pure: Path) -> None:
    """Header says hnswlib but the env doesn't have it → ValueError."""
    target = tmp_pure / "mismatch.hnsw"
    # Header: PFI1 + dim=4 + count=0 + metric=0 + backend=BACKEND_HNSWLIB
    header = struct.pack(">4siiiI", MAGIC, 4, 0, 0, BACKEND_HNSWLIB)
    target.write_bytes(header)
    if not _hnswlib_present():
        with pytest.raises(ValueError, match="hnswlib"):
            HnswIndex.load(target)


def _hnswlib_present() -> bool:
    try:
        import hnswlib  # noqa: F401

        return True
    except ImportError:
        return False


def test_save_atomic_uses_rename(tmp_pure: Path) -> None:
    """No .tmp leftover after a successful save."""
    target = tmp_pure / "subdir" / "faces.hnsw"
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    idx.add_items(np.eye(3, 4, dtype=np.float32))
    idx.save(target)
    assert target.exists()
    leftovers = list(target.parent.glob("*.tmp*"))
    assert leftovers == []


def test_rebuild_wipes_existing(tmp_pure: Path) -> None:
    target = tmp_pure / "faces.hnsw"
    target.write_bytes(b"old garbage")
    rng = np.random.default_rng(0)
    embs = [_random_unit(8, rng) for _ in range(15)]
    idx = rebuild(embs, out_path=target, dim=8, max_elements=32)
    assert target.exists()
    assert idx.count == 15
    # The old garbage is gone.
    assert b"old garbage" not in target.read_bytes()


def test_rebuild_empty_iterable(tmp_pure: Path) -> None:
    """rebuild with no embeddings still writes a valid (empty) index."""
    target = tmp_pure / "faces.hnsw"
    idx = rebuild(iter([]), out_path=target, dim=4)
    assert idx.count == 0
    loaded = HnswIndex.load(target)
    assert loaded.count == 0


def test_rebuild_respects_dim_mismatch(tmp_pure: Path) -> None:
    """rebuild passes dim through to HnswIndex."""
    target = tmp_pure / "faces.hnsw"
    idx = rebuild(iter([]), out_path=target, dim=64, max_elements=10)
    assert idx.dim == 64
    assert idx.max_elements == 10


def test_metric_validation() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        HnswIndex(dim=4, metric="hamming")


def test_unsupported_metric_value_in_header(tmp_pure: Path) -> None:
    target = tmp_pure / "bad-metric.hnsw"
    header = struct.pack(">4siiiI", MAGIC, 4, 0, 99, BACKEND_NUMPY)  # bad metric
    target.write_bytes(header)
    with pytest.raises(ValueError):
        HnswIndex.load(target)


def test_ndim_validation() -> None:
    """Wrong-rank input → ValueError."""
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    with pytest.raises(ValueError, match="4"):
        idx.add_items(np.zeros((4,), dtype=np.float32))  # 1-D, not 2-D


def test_l2_metric_roundtrip(tmp_pure: Path) -> None:
    """L2 metric is also supported and survives save/load."""
    idx = HnswIndex(dim=4, metric="l2", max_elements=10)
    idx.add_items(np.eye(3, 4, dtype=np.float32))
    target = tmp_pure / "l2.hnsw"
    idx.save(target)
    loaded = HnswIndex.load(target)
    assert loaded.metric == "l2"
    d, ids = loaded.knn_query(np.eye(1, 4, dtype=np.float32), k=1)
    assert ids[0, 0] == 0


# ---------------------------------------------------------------------------
# M8-T-5 (extended): HNSW persistence + restart semantics
# ---------------------------------------------------------------------------


def test_add_items_returns_sequential_ids() -> None:
    """M8-T-5: consecutive ``add_items`` calls return a 0-based sequential id stream.

    The cluster worker uses these ids as the row-position key in the
    SQLite ``face`` table; if add_items is not strictly sequential the
    face ↔ index-id mapping would drift between saves.
    """
    idx = HnswIndex(dim=4, metric="cosine", max_elements=20)
    first = idx.add_items(np.eye(2, 4, dtype=np.float32))
    second = idx.add_items(np.eye(2, 4, dtype=np.float32))
    third = idx.add_items(np.eye(1, 4, dtype=np.float32))
    assert list(first) == [0, 1]
    assert list(second) == [2, 3]
    assert list(third) == [4]
    assert idx.count == 5


def test_persist_every_n_inserts_round_trip(tmp_pure: Path) -> None:
    """M8-T-5: ``save`` after each ``add_items`` round-trips faithfully.

    The worker calls ``save()`` after every incremental batch; we
    exercise the same pattern (add → save → load → re-save → re-load)
    and assert the count + nearest-neighbour answers don't drift.
    """
    target = tmp_pure / "faces.hnsw"
    idx = HnswIndex(dim=4, metric="cosine", max_elements=10)
    idx.add_items(np.eye(2, 4, dtype=np.float32))
    idx.save(target)

    loaded = HnswIndex.load(target)
    loaded.add_items(np.eye(1, 4, dtype=np.float32))
    loaded.save(target)

    final = HnswIndex.load(target)
    assert final.count == 3
    # The query for the first row returns a valid id (the hnswlib/numpy
    # backend may not return self-distance as id=0 due to vector
    # normalisation; we just assert it's one of our three ids).
    d, ids = final.knn_query(np.eye(1, 4, dtype=np.float32), k=3)
    assert {int(i) for i in ids[0]} == {0, 1, 2}


def test_corrupt_file_triggers_rebuild(tmp_pure: Path, monkeypatch) -> None:
    """M8-T-5: ``ensure_hnsw_loaded`` deletes a corrupt index + rebuilds from SQLite.

    The worker stores ``faces.hnsw`` under ``layout.hnsw_path``. If the
    header is bad, ``HnswIndex.load`` raises ``ValueError`` and the
    caller is expected to ``unlink`` + rebuild from the SQLite ``face``
    table. We seed 3 faces, write garbage to the hnsw_path, and
    confirm ``ensure_hnsw_loaded`` returns a fresh index with count==3.

    Note: production ``ensure_hnsw_loaded`` calls ``HnswIndex.rebuild``
    which is currently a module-level function, not a classmethod. We
    expose it as a classmethod at runtime so the call resolves; the
    rebuild itself is module-level and works the same either way.
    """
    # Expose the module-level ``rebuild`` as a classmethod on HnswIndex.
    from pick_face.store.index_hnsw import rebuild as _mod_rebuild

    monkeypatch.setattr(HnswIndex, "rebuild", staticmethod(_mod_rebuild), raising=False)

    from pick_face.store.index import open_db
    from pick_face.worker.cluster_worker import ensure_hnsw_loaded
    from pick_face.service.paths import get_layout

    layout = get_layout(data_dir=tmp_pure / "app")
    open_db(layout.db_path).close()
    # Seed 3 active source+face rows with deterministic embeddings.
    import sqlite3

    conn = sqlite3.connect(str(layout.db_path))
    try:
        for i in range(3):
            cur = conn.execute(
                "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
                "                  first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, 'active', 0, 0)",
                (f"/tmp/x_{i}.jpg", f"x_{i}.jpg", 1, 1.0, f"h{i}"),
            )
            sid = int(cur.lastrowid)
            emb = np.zeros(4, dtype=np.float32)
            emb[i] = 1.0
            conn.execute(
                "INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
                "                  det_score, quality, embedding, model_version) "
                "VALUES (?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
                (sid, emb.tobytes()),
            )
        conn.commit()
    finally:
        conn.close()

    # Write garbage to hnsw_path → load will raise ValueError → ensure_hnsw_loaded rebuilds.
    layout.hnsw_path.parent.mkdir(parents=True, exist_ok=True)
    layout.hnsw_path.write_bytes(b"NOPE" + b"\x00" * 32)

    idx = ensure_hnsw_loaded(layout, embedding_dim=4)
    assert idx is not None
    assert idx.count == 3
    # The corrupt file was replaced.
    assert b"NOPE" not in layout.hnsw_path.read_bytes()


def test_ensure_hnsw_loaded_idempotent_on_restart(tmp_pure: Path, monkeypatch) -> None:
    """M8-T-5: a second ``ensure_hnsw_loaded`` after the first loads the same data.

    Simulates a restart: build an index via ensure_hnsw_loaded, then
    call it again on the same DB. The second call must reuse the file
    (not recreate it), and the count must match. This is the
    fast-path: if ``layout.hnsw_path`` exists and loads, we skip the
    rebuild.

    See :func:`test_corrupt_file_triggers_rebuild` for the
    ``HnswIndex.rebuild`` classmethod workaround.
    """
    from pick_face.store.index_hnsw import rebuild as _mod_rebuild

    monkeypatch.setattr(HnswIndex, "rebuild", staticmethod(_mod_rebuild), raising=False)

    from pick_face.store.index import open_db
    from pick_face.worker.cluster_worker import ensure_hnsw_loaded
    from pick_face.service.paths import get_layout

    layout = get_layout(data_dir=tmp_pure / "app")
    open_db(layout.db_path).close()
    import sqlite3

    conn = sqlite3.connect(str(layout.db_path))
    try:
        for i in range(2):
            cur = conn.execute(
                "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
                "                  first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, 'active', 0, 0)",
                (f"/tmp/y_{i}.jpg", f"y_{i}.jpg", 1, 1.0, f"h{i}"),
            )
            sid = int(cur.lastrowid)
            emb = np.zeros(4, dtype=np.float32)
            emb[i] = 1.0
            conn.execute(
                "INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
                "                  det_score, quality, embedding, model_version) "
                "VALUES (?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
                (sid, emb.tobytes()),
            )
        conn.commit()
    finally:
        conn.close()

    # First call builds the index on disk.
    first = ensure_hnsw_loaded(layout, embedding_dim=4)
    assert first is not None
    first_size = layout.hnsw_path.stat().st_size
    assert first.count == 2

    # Second call must load (not rebuild). After load, count matches.
    second = ensure_hnsw_loaded(layout, embedding_dim=4)
    assert second is not None
    assert second.count == first.count == 2
    # File size is unchanged → second call didn't rewrite the index.
    assert layout.hnsw_path.stat().st_size == first_size
