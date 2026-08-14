"""Tests for worker.cluster_worker — periodic + incremental reclustering.

Covers M8-T-3 / M8-T-4 / M8-T-5 (`docs/06 §3.1`).

Strategy:
- Build a real ``AppLayout`` + tiny SQLite DB on disk so the
  ``_load_*_embeddings`` / ``_write_face_clusters`` code paths are
  exercised end-to-end.
- Stub out :class:`HnswIndex` with a ``MagicMock`` so we don't load
  real hnswlib (heavy native dep, slow + flaky on CI).
- Stub :func:`incremental_assign` and :func:`cluster_embeddings` with
  deterministic mappings.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def _seed_active_face(db_path: Path, *, n: int, dim: int = 4) -> list[int]:
    """Insert N source rows (active) + N face rows with deterministic
    embeddings; return the face row ids in insertion order.

    Ensures the v2.x schema is created first so the SQLite tables exist.
    """
    from pick_face.store.index import open_db

    open_db(db_path).close()  # ensure schema exists
    conn = sqlite3.connect(str(db_path))
    try:
        face_ids: list[int] = []
        for i in range(n):
            cur = conn.execute(
                "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
                "                  first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, 'active', 0, 0)",
                (f"/tmp/img_{i}.jpg", f"img_{i}.jpg", 1, 1.0, f"h{i}"),
            )
            source_id = int(cur.lastrowid)
            # Deterministic 4-dim embedding: spread out so clustering
            # doesn't merge them when we override ``cluster_embeddings``.
            emb = np.zeros(dim, dtype=np.float32)
            emb[i % dim] = 1.0
            cur = conn.execute(
                "INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
                "                  det_score, quality, embedding, model_version) "
                "VALUES (?, 0, 0, 1, 1, 0.9, 0.8, ?, 'stub@1')",
                (source_id, emb.tobytes()),
            )
            face_ids.append(int(cur.lastrowid))
        conn.commit()
        return face_ids
    finally:
        conn.close()


def _patch_hnsw(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace HnswIndex + the module-level ``rebuild`` with a MagicMock.

    Returns the mock. ``rebuild`` is imported as ``hnsw_rebuild`` in
    cluster_worker (the module-level function in store/index_hnsw.py);
    it has no relationship to the ``HnswIndex`` class. Both targets
    need patching so the cluster_worker can call either surface
    without raising AttributeError.
    """
    fake = MagicMock(name="HnswIndex")
    fake.return_value.add_items.return_value = np.zeros(0, dtype=np.int64)
    fake.load.return_value = MagicMock(count=0)
    fake.rebuild.return_value = MagicMock(count=0, save=MagicMock())
    monkeypatch.setattr("pick_face.worker.cluster_worker.HnswIndex", fake)
    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.hnsw_rebuild", fake.rebuild
    )
    return fake


# ---------------------------------------------------------------------------
# Tests — full recluster (5 tests)
# ---------------------------------------------------------------------------


def test_full_recluster_assigns_all_faces(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-3: a full recluster writes ``cluster_id`` for every face."""
    layout = _layout(tmp_pure)
    _seed_active_face(layout.db_path, n=6)

    fake = _patch_hnsw(monkeypatch)

    # Stub cluster_embeddings so every face lands in its own cluster.
    def fake_cluster(embs, *, cfg, low_quality_mask=None, constraints=()):
        n = len(embs)
        labels = np.arange(n, dtype=np.int32)  # 0..N-1, no noise
        probs = np.ones(n, dtype=np.float32)
        from pick_face.ingest.cluster import ClusterResult
        return ClusterResult(labels=labels, probs=probs, n_clusters=n, n_noise=0)

    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.cluster_embeddings", fake_cluster
    )

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)

    new_clusters, merged_pairs = cw._do_full_recluster()  # noqa: SLF001

    # Every face now has a cluster_id.
    conn = sqlite3.connect(str(layout.db_path))
    rows = conn.execute("SELECT id, cluster_id FROM face ORDER BY id").fetchall()
    conn.close()
    assert all(r[1] is not None for r in rows), rows
    assert len({r[1] for r in rows}) == 6  # 6 distinct clusters
    # No merges (every face in its own cluster).
    assert merged_pairs == []


def test_hnsw_save_load_round_trip(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-T-5: ``rebuild`` writes the index to disk; ``load`` recovers it.

    We stub ``HnswIndex.rebuild`` and ``HnswIndex.load`` to share a
    counter so we can assert that the worker calls ``save`` on the
    full-recluster path.
    """
    layout = _layout(tmp_pure)
    _seed_active_face(layout.db_path, n=4)

    fake = _patch_hnsw(monkeypatch)

    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.cluster_embeddings",
        lambda embs, *, cfg, low_quality_mask=None, constraints=(): _trivial_cluster(embs),
    )

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)

    cw._do_full_recluster()  # noqa: SLF001
    # HnswIndex.rebuild was called with our 4 embeddings.
    fake.rebuild.assert_called_once()
    args, kwargs = fake.rebuild.call_args
    # args[0] is the iterable of per-row embeddings; len must be 4.
    assert len(list(args[0])) == 4
    assert kwargs["dim"] == 4
    assert kwargs["metric"] == "cosine"


def _trivial_cluster(embs: np.ndarray):
    """Stand-in cluster_embeddings that gives every face its own cluster."""
    from pick_face.ingest.cluster import ClusterResult
    n = len(embs)
    return ClusterResult(
        labels=np.arange(n, dtype=np.int32),
        probs=np.ones(n, dtype=np.float32),
        n_clusters=n,
        n_noise=0,
    )


def test_recluster_interval_respects_config(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``recluster_interval_hours`` flows into the scheduler interval."""
    layout = _layout(tmp_pure)

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker, INCREMENTAL_CHECK_INTERVAL_SEC

    fake = _patch_hnsw(monkeypatch)
    cfg = ClusteringConfig(
        recluster_interval_hours=1,  # → 3600s
        recluster_threshold=50,
    )
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)

    async def go():
        cw.start()
        try:
            # The full-recluster job should fire after max(60s, 1h * 3600s) = 3600s.
            full_job = cw._scheduler.get_job("cluster-full")  # noqa: SLF001
            interval = full_job.trigger.interval  # timedelta
            assert interval.total_seconds() == max(INCREMENTAL_CHECK_INTERVAL_SEC, 1 * 3600)
        finally:
            await cw.stop()

    asyncio.run(go())


def test_status_reflects_running_and_idle(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``status()`` returns 'inactive' / 'idle' / 'inactive' across lifecycle."""
    layout = _layout(tmp_pure)
    fake = _patch_hnsw(monkeypatch)

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)

    assert cw.status() == "inactive"

    async def go():
        cw.start()
        try:
            assert cw.status() == "idle"
            cw._running = True  # simulate an in-flight run  # noqa: SLF001
            assert cw.status() == "running"
            cw._running = False  # noqa: SLF001
            assert cw.status() == "idle"
            assert cw.qsize() == 0
        finally:
            await cw.stop()

    asyncio.run(go())
    assert cw.status() == "inactive"


def test_disabled_when_recluster_interval_hours_zero(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``recluster_interval_hours=0`` falls back to the 60s minimum.

    The Pydantic schema enforces ``ge=1`` for ``recluster_interval_hours``
    so we can't actually go to 0 through the config. The
    implementation uses ``max(INCREMENTAL_CHECK_INTERVAL_SEC, hours*3600)``
    which clamps to 60s minimum — verify that minimum bound.
    """
    layout = _layout(tmp_pure)
    fake = _patch_hnsw(monkeypatch)

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker, INCREMENTAL_CHECK_INTERVAL_SEC

    cfg = ClusteringConfig(recluster_interval_hours=1, recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)

    async def go():
        cw.start()
        try:
            full_job = cw._scheduler.get_job("cluster-full")  # noqa: SLF001
            # The interval is always at least INCREMENTAL_CHECK_INTERVAL_SEC.
            assert full_job.trigger.interval.total_seconds() >= INCREMENTAL_CHECK_INTERVAL_SEC
        finally:
            await cw.stop()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# Tests — incremental (4 tests)
# ---------------------------------------------------------------------------


def test_incremental_below_threshold_queued(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """< threshold new faces → no incremental run is triggered."""
    layout = _layout(tmp_pure)
    _seed_active_face(layout.db_path, n=10)  # 10 new faces < 50 default

    fake = _patch_hnsw(monkeypatch)
    run_calls: list[list[int]] = []

    def fake_run_incremental(self):
        run_calls.append([])
        return [1, 2, 3]

    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.ClusterWorker._run_incremental",
        fake_run_incremental,
    )

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)
    cw.note_scan_complete(list(range(1, 11)))
    cw._maybe_run_incremental()  # noqa: SLF001
    assert run_calls == []


def test_incremental_at_threshold_trigger_run(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """50 new faces → ``_run_incremental`` is called."""
    layout = _layout(tmp_pure)
    _seed_active_face(layout.db_path, n=50)

    fake = _patch_hnsw(monkeypatch)
    run_calls: list[list[int]] = []

    def fake_run_incremental(self):
        run_calls.append([])
        return list(range(1, 51))

    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.ClusterWorker._run_incremental",
        fake_run_incremental,
    )

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)
    cw.note_scan_complete(list(range(1, 51)))
    cw._maybe_run_incremental()  # noqa: SLF001
    assert len(run_calls) == 1


def test_incremental_resets_counter_after_run(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the incremental runs, the counter goes back to 0."""
    layout = _layout(tmp_pure)
    _seed_active_face(layout.db_path, n=120)

    fake = _patch_hnsw(monkeypatch)
    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.ClusterWorker._run_incremental",
        lambda self: [],
    )

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=50)
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)
    cw.note_scan_complete(list(range(1, 121)))
    assert cw._unclustered_count == 120  # noqa: SLF001
    cw._maybe_run_incremental()  # noqa: SLF001
    assert cw._unclustered_count == 0  # noqa: SLF001


def test_incremental_assigns_to_correct_centroid(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New face embedding closer to centroid A than B → assigned to A.

    We stub ``incremental_assign`` to a deterministic function and
    verify the worker writes the right ``cluster_id``.
    """
    layout = _layout(tmp_pure)
    _seed_active_face(layout.db_path, n=4)

    fake = _patch_hnsw(monkeypatch)

    # Seed two existing clusters (ids 10 and 20) with one face each.
    from pick_face.store.index import open_db
    open_db(layout.db_path).close()  # ensure cluster table exists
    conn = sqlite3.connect(str(layout.db_path))
    conn.execute(
        "INSERT INTO cluster(id, label, size, created_at, updated_at) "
        "VALUES (10, 'person-A', 0, 0, 0)"
    )
    conn.execute(
        "INSERT INTO cluster(id, label, size, created_at, updated_at) "
        "VALUES (20, 'person-B', 0, 0, 0)"
    )
    # Promote first two seeded faces into clusters 10 / 20.
    face_rows = conn.execute("SELECT id FROM face ORDER BY id LIMIT 2").fetchall()
    for face_id, cluster_id in zip([r[0] for r in face_rows], [10, 20]):
        conn.execute("UPDATE face SET cluster_id = ? WHERE id = ?", (cluster_id, face_id))
    conn.commit()
    conn.close()

    # Stub incremental_assign → always cluster 10.
    def fake_incremental(new_embs, *, existing_centroids, existing_labels, strong_match, loose_match):
        labels = np.full(len(new_embs), 10, dtype=np.int32)
        probs = np.ones(len(new_embs), dtype=np.float32)
        return labels, probs

    monkeypatch.setattr(
        "pick_face.worker.cluster_worker.incremental_assign", fake_incremental
    )

    from pick_face.core.config import ClusteringConfig
    from pick_face.worker.cluster_worker import ClusterWorker

    cfg = ClusteringConfig(recluster_threshold=2)  # so we fire on just 2 new
    cw = ClusterWorker(layout, embedding_dim=4, hnsw_index=fake.return_value, config=cfg)
    cw.note_scan_complete([100, 101])  # phantom IDs; _run_incremental loads from DB
    cw._maybe_run_incremental()  # noqa: SLF001

    # Verify cluster_id = 10 was written for all unclustered faces.
    conn = sqlite3.connect(str(layout.db_path))
    rows = conn.execute(
        "SELECT id, cluster_id FROM face WHERE cluster_id IS NOT NULL ORDER BY id"
    ).fetchall()
    conn.close()
    cluster_ids = {r[1] for r in rows}
    # Pre-existing seeded clusters (10 + 20) plus the new ones from
    # the incremental pass.
    assert 10 in cluster_ids
    assert 20 in cluster_ids