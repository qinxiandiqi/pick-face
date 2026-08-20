"""Cluster worker — periodic + incremental reclustering.

Implements ``docs/06 §3.1 M8-T-3 / M8-T-4 / M8-T-5``.

Two triggers fire work on this worker:

* **Periodic full recluster** (``M8-T-3``): on
  ``ClusteringConfig.recluster_interval_hours`` (default 24h), runs
  :func:`ingest.cluster.cluster_embeddings` on the entire face set
  to keep cluster IDs stable across merges / splits. Emits
  ``new_person`` and ``merged`` SSE events for any cluster-row
  deltas.
* **Incremental trigger** (``M8-T-4``): a counter
  ``self._unclustered_count`` is incremented after each scan
  finishes (``ScanRunner._execute`` calls
  :meth:`note_scan_complete` with the new face IDs). When the
  counter crosses ``ClusteringConfig.recluster_threshold`` (default
  50), :func:`ingest.cluster.incremental_assign` is used to slot the
  new faces into existing clusters without touching existing
  centroids. HNSW gets the new faces incrementally
  (``HnswIndex.add_items`` + ``save``).

HNSW persistence (``M8-T-5``): the worker holds the in-process
``HnswIndex`` for the lifetime of the FastAPI process; ``save()``
is called at the end of every cluster run. Crash-recovery is
handled in the lifespan: :func:`ensure_hnsw_loaded` reloads the
index or rebuilds it from SQLite if the file is corrupt.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from pick_face.core.config import ClusteringConfig
from pick_face.ingest.cluster import (
    cluster_embeddings,
    incremental_assign,
)
from pick_face.service.config_service import load_config
from pick_face.service.paths import AppLayout
from pick_face.service.scan_service import ScanService, ScanState
from pick_face.store.index import DEFAULT_SOURCE_STATUS, open_db
from pick_face.store.index_hnsw import HnswIndex, rebuild as hnsw_rebuild

log = logging.getLogger(__name__)

# Polling interval for the incremental-trigger check. The full
# recluster runs at ``recluster_interval_hours``; the incremental
# check is cheap (a single SELECT + counter comparison) so we poll
# it every minute by default.
INCREMENTAL_CHECK_INTERVAL_SEC = 60


def _now() -> float:
    return time.time()


def _decode_embeddings(rows: list[tuple[int, int, bytes, int | None, float | None]]) -> tuple[
    np.ndarray, list[int], list[int]
]:
    """Decode ``(face_id, source_id, blob, cluster_id, prob)`` rows.

    Returns ``(embeddings, face_ids, cluster_ids)`` where
    ``cluster_ids[i] = -1`` when ``cluster_id IS NULL``.
    """
    if not rows:
        return (
            np.zeros((0, 0), dtype=np.float32),
            [],
            [],
        )
    # First row's blob tells us the embedding dim.
    dim = len(rows[0][2]) // 4
    embs = np.empty((len(rows), dim), dtype=np.float32)
    face_ids: list[int] = []
    cluster_ids: list[int] = []
    for i, (face_id, _src, blob, cluster_id, _prob) in enumerate(rows):
        embs[i] = np.frombuffer(blob, dtype=np.float32)
        face_ids.append(int(face_id))
        cluster_ids.append(-1 if cluster_id is None else int(cluster_id))
    return embs, face_ids, cluster_ids


class ClusterWorker:
    """Owns periodic + incremental recluster triggers.

    Lifecycle: construct in lifespan, ``start()`` on startup,
    ``async stop()`` on shutdown. ``qsize()`` and ``status()`` feed
    ``/api/ready`` (M8-T-7).
    """

    def __init__(
        self,
        layout: AppLayout,
        *,
        embedding_dim: int,
        hnsw_index: HnswIndex | None = None,
        config: ClusteringConfig | None = None,
    ) -> None:
        self._layout = layout
        self._embedding_dim = int(embedding_dim)
        self._hnsw = hnsw_index
        self._config = config or _load_clustering_config(layout)
        self._scheduler: AsyncIOScheduler | None = None
        self._unclustered_count = 0
        self._running = False

    # -- public API --------------------------------------------------------

    def start(self) -> None:
        """Schedule both triggers. Idempotent."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        # Full recluster: recluster_interval_hours (default 24h).
        full_sec = max(
            INCREMENTAL_CHECK_INTERVAL_SEC,
            int(self._config.recluster_interval_hours) * 3600,
        )
        self._scheduler.add_job(
            self._run_full,
            trigger=IntervalTrigger(seconds=full_sec),
            id="cluster-full",
            next_run_time=None,
            max_instances=1,
            coalesce=True,
        )
        # Incremental trigger: poll every INCREMENTAL_CHECK_INTERVAL_SEC.
        self._scheduler.add_job(
            self._maybe_run_incremental,
            trigger=IntervalTrigger(seconds=INCREMENTAL_CHECK_INTERVAL_SEC),
            id="cluster-incremental-check",
            next_run_time=None,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        log.info(
            "cluster_worker: full every %ds, incremental check every %ds, threshold=%d",
            full_sec,
            INCREMENTAL_CHECK_INTERVAL_SEC,
            self._config.recluster_threshold,
        )

    async def stop(self) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=True)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("cluster_worker: shutdown error: %s", exc)
        self._scheduler = None

    def qsize(self) -> int:
        """1 when a cluster run is in flight, else 0."""
        return 1 if self._running else 0

    def status(self) -> str:
        """``idle`` | ``running`` | ``disabled`` | ``inactive``."""
        if self._scheduler is None:
            return "inactive"
        if self._running:
            return "running"
        return "idle"

    def note_scan_complete(self, new_face_ids: list[int]) -> None:
        """Called by ``ScanRunner._execute`` after a scan ``DONE``.

        Increments the unclustered counter so the next
        incremental-check tick fires when the threshold is crossed.
        """
        if new_face_ids:
            self._unclustered_count += len(new_face_ids)
            log.debug(
                "cluster_worker: unclustered_count=%d (+%d)",
                self._unclustered_count,
                len(new_face_ids),
            )

    # -- scheduler callbacks ----------------------------------------------

    def _maybe_run_incremental(self) -> None:
        """Run an incremental pass if the threshold is crossed."""
        if self._unclustered_count < self._config.recluster_threshold:
            return
        try:
            new_face_ids = self._run_incremental()
        except Exception as exc:  # pragma: no cover — defensive
            log.exception("cluster_worker: incremental failed: %s", exc)
            return
        self._unclustered_count = 0
        log.info("cluster_worker: incremental assigned %d faces", len(new_face_ids))

    def _run_full(self) -> None:
        """Periodic full recluster."""
        try:
            self._running = True
            new_clusters, merged_pairs = self._do_full_recluster()
        except Exception as exc:  # pragma: no cover — defensive
            log.exception("cluster_worker: full recluster failed: %s", exc)
            return
        finally:
            self._running = False
        log.info(
            "cluster_worker: full recluster produced %d new clusters, %d merges",
            len(new_clusters),
            len(merged_pairs),
        )
        # Sidecar append (M8-T-8) — best effort; missing sidecar just
        # means no SSE consumer is attached right now.
        self._append_sidecar_events(new_clusters, merged_pairs)

    # -- full recluster ----------------------------------------------------

    def _do_full_recluster(self) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
        """Run HDBSCAN over all active faces; persist results.

        Returns:
            (new_clusters, merged_pairs) — for SSE event emission.
            ``new_clusters``: ``[{cluster_id, label}]``
            ``merged_pairs``:   ``[(loser_id, winner_id)]``
        """
        embs, face_ids, old_cluster_ids = self._load_all_active_face_embeddings()
        if len(face_ids) == 0:
            return [], []

        result = cluster_embeddings(embs, cfg=self._config)

        # Map compact 0..K-1 labels → DB cluster IDs (preserving
        # existing IDs where possible). Compact label -1 means noise
        # and is excluded from cluster creation.
        (
            new_cluster_ids,
            new_clusters,
            merged_pairs,
        ) = self._persist_labels(
            face_ids=face_ids,
            old_cluster_ids=old_cluster_ids,
            labels=result.labels,
            probs=result.probs,
        )

        # Update HNSW: full rebuild keeps it in sync with DB.
        self._rebuild_hnsw(embs, face_ids)

        return new_clusters, merged_pairs

    def _persist_labels(
        self,
        *,
        face_ids: list[int],
        old_cluster_ids: list[int],
        labels: np.ndarray,
        probs: np.ndarray,
    ) -> tuple[list[int], list[dict[str, Any]], list[tuple[int, int]]]:
        """Write cluster labels back to SQLite.

        Strategy:
            1. For each compact label k >= 0, find the existing
               cluster_id with the most faces in compact k (majority
               vote). That existing cluster_id becomes the canonical
               id for compact k.
            2. Compact k with no majority → INSERT a fresh cluster row
               and emit a ``new_person`` event.
            3. Old cluster_ids that disappear (compact 0 took all
               their faces) are kept as cluster rows but with zero
               faces — they show as empty albums in the SPA.
            4. Per-face: UPDATE face.cluster_id, face.cluster_prob.

        Returns:
            ``(new_cluster_ids, new_cluster_events, merged_pairs)``.
        """
        new_cluster_ids: list[int] = [-1] * len(face_ids)
        # Compact label k → list of (old_cluster_id, count).
        votes: dict[int, dict[int, int]] = {}
        for i, k in enumerate(labels.tolist()):
            if k < 0:
                continue
            old = old_cluster_ids[i]
            votes.setdefault(k, {})
            votes[k][old] = votes[k].get(old, 0) + 1

        # Resolve compact label → canonical cluster_id.
        compact_to_canonical: dict[int, int] = {}
        new_cluster_events: list[dict[str, Any]] = []
        merged_pairs: list[tuple[int, int]] = []
        next_label_seq = _next_cluster_label(self._layout)

        for k, tallies in votes.items():
            # Drop the "no existing cluster" bucket when picking the
            # majority — we prefer to keep an existing cluster alive
            # over creating a new one.
            tally_no_existing = tallies.pop(-1, 0)
            if tallies:
                winner_old_id = max(tallies, key=lambda x: tallies[x])
                canonical = int(winner_old_id)
                compact_to_canonical[k] = canonical
                # Losers (other existing clusters whose faces ended
                # up in compact k) get folded in.
                for loser_id in tallies:
                    if int(loser_id) != canonical:
                        merged_pairs.append((int(loser_id), canonical))
            else:
                # Brand-new cluster.
                new_id = _insert_cluster_row(
                    self._layout,
                    label=f"person-{next_label_seq():04d}",
                )
                compact_to_canonical[k] = new_id
                new_cluster_events.append(
                    {"cluster_id": new_id, "label": f"person-{new_id:04d}"}
                )

        # Map per-face labels → canonical IDs.
        for i, k in enumerate(labels.tolist()):
            if k < 0:
                new_cluster_ids[i] = -1
            else:
                new_cluster_ids[i] = compact_to_canonical[int(k)]

        # Persist.
        self._write_face_clusters(face_ids, new_cluster_ids, labels.tolist(), probs.tolist())
        # Persist merges: mark loser clusters as merged_into canonical.
        if merged_pairs:
            self._write_merges(merged_pairs)

        return new_cluster_ids, new_cluster_events, merged_pairs

    # -- incremental recluster --------------------------------------------

    def _run_incremental(self) -> list[int]:
        """Assign unclustered faces to existing centroids; emit events.

        Returns the list of face IDs that were assigned (used by the
        caller to log + sidecar).
        """
        new_face_ids = self._load_unclustered_face_ids()
        if not new_face_ids:
            return []
        new_embs = self._load_face_embeddings_by_ids(new_face_ids)
        cents, labels_in_db = self._load_cluster_centroids()
        if cents.shape[0] == 0:
            # No existing clusters → fall back to creating one cluster
            # for all new faces.
            new_cluster_id = _insert_cluster_row(
                self._layout,
                label=f"person-{_next_cluster_label(self._layout)():04d}",
            )
            assigned = [new_cluster_id] * len(new_face_ids)
            probs = [1.0] * len(new_face_ids)
            self._write_face_clusters(new_face_ids, assigned, [0] * len(new_face_ids), probs)
            self._hnsw_add(new_embs, new_face_ids)
            return new_face_ids

        labels, probs = incremental_assign(
            new_embs,
            existing_centroids=cents,
            existing_labels=np.asarray(labels_in_db, dtype=np.int32),
            strong_match=self._config.strong_match,
            loose_match=self._config.loose_match,
        )
        # For label == -1, create a fresh cluster row.
        next_seq = _next_cluster_label(self._layout)
        final_labels: list[int] = []
        for k in labels.tolist():
            if k < 0:
                cid = _insert_cluster_row(
                    self._layout,
                    label=f"person-{next_seq():04d}",
                )
                final_labels.append(cid)
            else:
                final_labels.append(int(k))
        # Persist.
        self._write_face_clusters(
            new_face_ids, final_labels, labels.tolist(), probs.tolist()
        )
        # HNSW incremental append + persist.
        self._hnsw_add(new_embs, new_face_ids)
        return new_face_ids

    # -- HNSW --------------------------------------------------------------

    def _rebuild_hnsw(self, embs: np.ndarray, face_ids: list[int]) -> None:
        """Full HNSW rebuild after a periodic recluster.

        Uses ``hnsw_rebuild`` (the module-level function in
        ``store/index_hnsw.py``) which writes a fresh file.
        """
        if not face_ids:
            return
        self._hnsw = hnsw_rebuild(
            [embs[i] for i in range(len(face_ids))],
            out_path=self._layout.hnsw_path,
            dim=self._embedding_dim,
            metric="cosine",
            max_elements=max(len(face_ids) * 2, 1024),
        )

    def _hnsw_add(self, embs: np.ndarray, face_ids: list[int]) -> None:
        """Incremental append + save (M8-T-5)."""
        if not face_ids:
            return
        if self._hnsw is None:
            # No in-memory HNSW yet — initialise it lazily.
            self._hnsw = HnswIndex(
                dim=self._embedding_dim,
                metric="cosine",
                max_elements=max(len(face_ids) * 2, 1024),
            )
        self._hnsw.add_items(embs, np.asarray(face_ids, dtype=np.int64))
        self._hnsw.save(self._layout.hnsw_path)

    # -- DB helpers --------------------------------------------------------

    def _load_all_active_face_embeddings(
        self,
    ) -> tuple[np.ndarray, list[int], list[int]]:
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT f.id, f.source_id, f.embedding, f.cluster_id, f.cluster_prob
                FROM face f
                JOIN source s ON s.id = f.source_id
                WHERE s.status = ?
                ORDER BY f.id
                """,
                (DEFAULT_SOURCE_STATUS,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        embs, face_ids, cluster_ids = _decode_embeddings(
            [(int(r[0]), int(r[1]), bytes(r[2]), r[3], r[4]) for r in rows]
        )
        return embs, face_ids, cluster_ids

    def _load_unclustered_face_ids(self) -> list[int]:
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT f.id FROM face f
                JOIN source s ON s.id = f.source_id
                WHERE f.cluster_id IS NULL AND s.status = ?
                ORDER BY f.id
                """,
                (DEFAULT_SOURCE_STATUS,),
            )
            return [int(r[0]) for r in cur.fetchall()]
        finally:
            conn.close()

    def _load_face_embeddings_by_ids(self, face_ids: list[int]) -> np.ndarray:
        if not face_ids:
            return np.zeros((0, self._embedding_dim), dtype=np.float32)
        conn = open_db(self._layout.db_path)
        try:
            qmarks = ",".join("?" for _ in face_ids)
            cur = conn.execute(
                f"SELECT id, embedding FROM face WHERE id IN ({qmarks}) ORDER BY id",
                face_ids,
            )
            blobs = {int(r[0]): bytes(r[1]) for r in cur.fetchall()}
        finally:
            conn.close()
        embs = np.empty((len(face_ids), self._embedding_dim), dtype=np.float32)
        for i, fid in enumerate(face_ids):
            embs[i] = np.frombuffer(blobs[fid], dtype=np.float32)
        return embs

    def _load_cluster_centroids(self) -> tuple[np.ndarray, list[int]]:
        """Per-cluster mean embedding, averaged in float64 for stability."""
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT f.cluster_id, f.embedding
                FROM face f
                JOIN source s ON s.id = f.source_id
                WHERE f.cluster_id IS NOT NULL AND s.status = ?
                ORDER BY f.cluster_id, f.id
                """,
                (DEFAULT_SOURCE_STATUS,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        if not rows:
            return np.zeros((0, self._embedding_dim), dtype=np.float32), []
        # Group by cluster_id, average in float64.
        per_cluster: dict[int, list[np.ndarray]] = {}
        for r in rows:
            cid = int(r[0])
            per_cluster.setdefault(cid, []).append(np.frombuffer(bytes(r[1]), dtype=np.float32))
        centroids: list[np.ndarray] = []
        ids: list[int] = []
        for cid in sorted(per_cluster.keys()):
            arr = np.stack(per_cluster[cid], axis=0).astype(np.float64)
            mean = arr.mean(axis=0).astype(np.float32)
            centroids.append(mean)
            ids.append(cid)
        return np.stack(centroids, axis=0), ids

    def _write_face_clusters(
        self,
        face_ids: list[int],
        cluster_ids: list[int],
        labels: list[int],
        probs: list[float],
    ) -> None:
        if not face_ids:
            return
        conn = open_db(self._layout.db_path)
        try:
            rows = list(zip(face_ids, cluster_ids, labels, probs))
            with conn:
                conn.executemany(
                    """
                    UPDATE face
                    SET cluster_id = ?,
                        cluster_prob = ?
                    WHERE id = ?
                    """,
                    [(cid, float(prob), fid) for fid, cid, _lbl, prob in rows],
                )
        finally:
            conn.close()

    def _write_merges(self, merged_pairs: list[tuple[int, int]]) -> None:
        """Mark loser clusters as ``merged_into`` winner (best-effort)."""
        conn = open_db(self._layout.db_path)
        try:
            now = _now()
            with conn:
                for loser, winner in merged_pairs:
                    conn.execute(
                        "UPDATE cluster SET merged_into = ?, updated_at = ? WHERE id = ?",
                        (winner, now, loser),
                    )
        finally:
            conn.close()

    # -- SSE sidecar (M8-T-8) ---------------------------------------------

    def _append_sidecar_events(
        self,
        new_clusters: list[dict[str, Any]],
        merged_pairs: list[tuple[int, int]],
    ) -> None:
        """Append ``new_person`` + ``merged`` events to the active job's sidecar.

        If no scan is currently active, the events have no SSE
        consumer and are silently dropped — the next ``GET
        /api/persons`` will pick up the new cluster rows regardless.
        """
        svc = ScanService(self._layout)
        active = svc.active()
        if active is None:
            return
        sidecar = svc.events_file(active.id)
        if not sidecar.exists():
            return
        lines: list[str] = []
        for ev in new_clusters:
            lines.append(json.dumps({"type": "new_person", **ev}))
        for loser, winner in merged_pairs:
            lines.append(
                json.dumps(
                    {
                        "type": "merged",
                        "cluster_id": int(loser),
                        "into_cluster_id": int(winner),
                    }
                )
            )
        if not lines:
            return
        try:
            with sidecar.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as exc:  # pragma: no cover — defensive
            log.warning("cluster_worker: sidecar append failed: %s", exc)


# -----------------------------------------------------------------------------
# Module-level helpers (pure DB accessors; no state).
# -----------------------------------------------------------------------------


def _insert_cluster_row(layout: AppLayout, *, label: str) -> int:
    conn = open_db(layout.db_path)
    try:
        now = _now()
        cur = conn.execute(
            """
            INSERT INTO cluster (label, size, created_at, updated_at)
            VALUES (?, 0, ?, ?)
            """,
            (label, now, now),
        )
        return int(cur.lastrowid)
    finally:
        conn.close()


def _next_cluster_label(layout: AppLayout):
    """Return a callable that yields the next ``person-NNNN`` sequence."""
    conn = open_db(layout.db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM cluster")
        (count,) = cur.fetchone()
    finally:
        conn.close()
    counter = [int(count) + 1]

    def _next() -> int:
        n = counter[0]
        counter[0] = n + 1
        return n

    return _next


def _load_clustering_config(layout: AppLayout) -> ClusteringConfig:
    try:
        cfg = load_config(layout)
    except (OSError, ValueError):
        return ClusteringConfig()
    clustering = cfg.get("clustering") if isinstance(cfg, dict) else None
    if not isinstance(clustering, dict):
        return ClusteringConfig()
    # Pydantic v2 ignores unknown fields by default; only known fields
    # make it into the model.
    return ClusteringConfig.model_validate(clustering)


def ensure_hnsw_loaded(
    layout: AppLayout, *, embedding_dim: int
) -> HnswIndex | None:
    """Load the HNSW index from disk; rebuild from SQLite if corrupt/missing.

    Called from the FastAPI lifespan before the ClusterWorker is
    instantiated (M8-T-5). Returns ``None`` when the DB has zero
    faces (no index yet — ClusterWorker will create one on the first
    incremental run).
    """
    conn = open_db(layout.db_path)
    try:
        cur = conn.execute(
            """
            SELECT f.id, f.embedding FROM face f
            JOIN source s ON s.id = f.source_id
            WHERE s.status = ?
            ORDER BY f.id
            """,
            (DEFAULT_SOURCE_STATUS,),
        )
        rows = [(int(r[0]), bytes(r[1])) for r in cur.fetchall()]
    finally:
        conn.close()
    if not rows:
        return None
    if layout.hnsw_path.exists():
        try:
            return HnswIndex.load(layout.hnsw_path)
        except ValueError:
            layout.hnsw_path.unlink(missing_ok=True)
    # Rebuild from SQLite.
    embs = np.stack(
        [np.frombuffer(blob, dtype=np.float32) for _, blob in rows],
        axis=0,
    )
    return hnsw_rebuild(
        [embs[i] for i in range(len(rows))],
        out_path=layout.hnsw_path,
        dim=embedding_dim,
        metric="cosine",
        max_elements=max(len(rows) * 2, 1024),
    )


__all__ = [
    "ClusterWorker",
    "ensure_hnsw_loaded",
]