"""HNSW index wrapper for face embeddings (M3 / T-203).

Reference:
- docs/05 §3 (faces.hnsw lives at .cache/faces.hnsw)
- docs/04 §2.4 (HDBSCAN O(N^2) → HNSW O(N log N) per-query)
- docs/09 §13 (HNSW rebuilt at start; periodic incremental appends)

Design:
  - We always go through this module; the underlying lib is hnswlib
    when it's installed, otherwise we fall back to a brute-force numpy
    implementation that has the same `knn_query` / `add_items` /
    `save` / `load` surface area.
  - Crash rebuild: if `load_hnsw(...)` raises (corrupt file / version
    mismatch / wrong dim), the caller deletes the file and calls
    `rebuild(...)` from scratch. We don't auto-magic this; the user
    should know their index got rebuilt.
  - Persistence format: a small header (magic + dim + count + metric)
    followed by the hnswlib native blob OR (for the numpy fallback) a
    npy with the embeddings.

Schema (binary header):
  4 bytes: "PFI1" magic
  4 bytes: int32 dim
  4 bytes: int32 count
  4 bytes: int32 metric (0=cosine, 1=l2)
  4 bytes: int32 backend (0=numpy, 1=hnswlib)
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Iterable

import numpy as np

MAGIC = b"PFI1"
METRIC_COSINE = 0
METRIC_L2 = 1
BACKEND_NUMPY = 0
BACKEND_HNSWLIB = 1


def _hnswlib_available() -> bool:
    try:
        import hnswlib  # noqa: F401
        return True
    except ImportError:
        return False


def _metric_str(metric_int: int) -> str:
    if metric_int == METRIC_COSINE:
        return "cosine"
    if metric_int == METRIC_L2:
        return "l2"
    raise ValueError(f"unsupported metric code: {metric_int!r}")


def _metric_int(metric: str) -> int:
    m = metric.lower()
    if m == "cosine":
        return METRIC_COSINE
    if m in ("l2", "euclidean"):
        return METRIC_L2
    raise ValueError(f"unsupported metric: {metric!r}")


class HnswIndex:
    """Tiny wrapper exposing add_items / knn_query / save / load.

    The class is intentionally minimal — we only need what pick-face uses:
    append embeddings, query nearest neighbours, persist to disk, reload.
    """

    def __init__(
        self,
        dim: int,
        *,
        metric: str = "cosine",
        max_elements: int = 10_000,
        ef_construction: int = 200,
        M: int = 16,
    ) -> None:
        if dim <= 0:
            raise ValueError(f"dim must be > 0, got {dim}")
        # Validate metric eagerly — hnswlib will happily accept anything
        # but later raise on first query, which is too late.
        _metric_int(metric)  # raises ValueError on bad metric
        self.dim = int(dim)
        self.metric = metric
        self.max_elements = int(max_elements)
        self._ef_construction = ef_construction
        self._M = M
        self._count = 0
        self._backend = "hnswlib" if _hnswlib_available() else "numpy"
        self._items: np.ndarray | None = None  # numpy fallback storage
        self._hnsw = None  # hnswlib index

        if self._backend == "hnswlib":
            self._init_hnswlib()
        # numpy fallback: items are appended into self._items below.

    def _init_hnswlib(self) -> None:
        import hnswlib

        space = "cosine" if self.metric == "cosine" else "l2"
        idx = hnswlib.Index(space=space, dim=self.dim)
        idx.init_index(
            max_elements=self.max_elements,
            ef_construction=self._ef_construction,
            M=self._M,
        )
        idx.set_ef(50)  # query-time ef
        idx.set_num_threads(1)
        self._hnsw = idx

    def add_items(self, embeddings: np.ndarray, ids: np.ndarray | None = None) -> np.ndarray:
        """Append embeddings. Returns the assigned internal IDs (row indices).

        The IDs are 0-based row indices in the order items were added.
        Callers should keep their own (face_id → index_id) map.
        """
        if embeddings.ndim != 2 or embeddings.shape[1] != self.dim:
            raise ValueError(
                f"expected (N, {self.dim}) embeddings, got {embeddings.shape}"
            )
        n = embeddings.shape[0]
        if n == 0:
            return np.zeros(0, dtype=np.int64)
        emb = embeddings.astype(np.float32, copy=False)
        # hnswlib requires normalized vectors for cosine.
        if self.metric == "cosine":
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            norms = np.where(norms < 1e-12, 1.0, norms)
            emb = emb / norms
        ids = np.arange(self._count, self._count + n, dtype=np.int64) if ids is None else np.asarray(ids, dtype=np.int64)
        if self._backend == "hnswlib":
            self._hnsw.add_items(emb, ids, replace_deleted=False)
        else:
            # Numpy fallback: append to a preallocated buffer.
            if self._items is None:
                self._items = np.zeros((self.max_elements, self.dim), dtype=np.float32)
            needed = self._count + n
            if needed > self.max_elements:
                # Grow geometrically.
                new_size = max(self.max_elements * 2, needed)
                self._items = np.resize(self._items, (new_size, self.dim))
                self.max_elements = new_size
            self._items[self._count:self._count + n] = emb
        self._count += n
        return ids

    def knn_query(self, queries: np.ndarray, k: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """Return (distances, ids) for each query, shape (Q, k)."""
        if queries.ndim != 2 or queries.shape[1] != self.dim:
            raise ValueError(
                f"expected (Q, {self.dim}) queries, got {queries.shape}"
            )
        if self._count == 0:
            # Empty index → return shape (Q, 0) arrays; this matches
            # what callers (incremental cluster assign, downstream review)
            # expect when there are no neighbours yet.
            return (
                np.zeros((queries.shape[0], 0), dtype=np.float32),
                np.zeros((queries.shape[0], 0), dtype=np.int64),
            )
        if k < 1 or k > self._count:
            k = max(1, min(k, self._count))
        q = queries.astype(np.float32, copy=False)
        if self.metric == "cosine":
            norms = np.linalg.norm(q, axis=1, keepdims=True)
            norms = np.where(norms < 1e-12, 1.0, norms)
            q = q / norms

        if self._backend == "hnswlib":
            labels, distances = self._hnsw.knn_query(q, k=k)
            return distances.astype(np.float32), labels.astype(np.int64)
        # Numpy fallback: brute-force.
        assert self._items is not None
        sim = q @ self._items[: self._count].T  # (Q, N)
        if self.metric == "cosine":
            dist = 1.0 - sim
        else:
            # squared L2
            q2 = (q * q).sum(axis=1, keepdims=True)
            i2 = (self._items[: self._count] ** 2).sum(axis=1)
            dist = q2 + i2[None, :] - 2 * sim
        idx = np.argpartition(dist, kth=k - 1, axis=1)[:, :k]
        rows = np.arange(dist.shape[0])[:, None]
        distances = dist[rows, idx]
        # Sort each row ascending (argpartition only guarantees order within
        # the top-k, not across).
        order = np.argsort(distances, axis=1)
        return distances[rows, order], idx[rows, order].astype(np.int64)

    def save(self, path: Path) -> Path:
        """Persist to *path* atomically (write-then-rename)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        metric_int = _metric_int(self.metric)
        if self._backend == "hnswlib":
            backend = BACKEND_HNSWLIB
            # hnswlib can save to a file; we wrap with our header.
            inner = tmp.with_suffix(tmp.suffix + ".hnsw")
            self._hnsw.save_index(str(inner))
            with open(tmp, "wb") as f:
                f.write(struct.pack(
                    ">4siiiI",
                    MAGIC,
                    self.dim,
                    self._count,
                    metric_int,
                    backend,
                ))
                f.write(inner.read_bytes())
            inner.unlink(missing_ok=True)
        else:
            backend = BACKEND_NUMPY
            payload = self._items[: self._count].tobytes()
            with open(tmp, "wb") as f:
                f.write(struct.pack(
                    ">4siiiI",
                    MAGIC,
                    self.dim,
                    self._count,
                    metric_int,
                    backend,
                ))
                f.write(payload)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Path) -> "HnswIndex":
        """Load *path*. Raises ValueError if the header is unparseable so the
        caller can delete + rebuild."""
        path = Path(path)
        with open(path, "rb") as f:
            header = f.read(20)
        if len(header) != 20:
            raise ValueError(f"{path}: header truncated")
        magic, dim, count, metric_int, backend = struct.unpack(">4siiiI", header)
        if magic != MAGIC:
            raise ValueError(f"{path}: bad magic {magic!r}")
        idx = cls(dim=dim, metric=_metric_str(metric_int))
        idx._count = int(count)
        # Read remainder.
        with open(path, "rb") as f:
            f.seek(20)
            payload = f.read()
        if backend == BACKEND_HNSWLIB and idx._backend == "hnswlib":
            tmp = path.with_suffix(path.suffix + ".hnsw.tmp")
            tmp.write_bytes(payload)
            idx._hnsw.load_index(str(tmp))
            tmp.unlink(missing_ok=True)
        elif backend == BACKEND_NUMPY:
            arr = np.frombuffer(payload, dtype=np.float32).reshape(-1, dim)
            idx._items = np.zeros((max(idx.max_elements, arr.shape[0]), dim), dtype=np.float32)
            idx._items[: arr.shape[0]] = arr
            idx.max_elements = max(idx.max_elements, arr.shape[0])
            idx._count = arr.shape[0]
        else:
            # Backend mismatch (saved with hnswlib, current python without).
            # Fall back to numpy reconstruction: deserialize raw embeddings
            # if header matches our fallback format.
            if backend == BACKEND_HNSWLIB:
                raise ValueError(
                    f"{path}: saved with hnswlib backend but not installed now; "
                    "install hnswlib or delete the index to rebuild from SQLite."
                )
        return idx

    @property
    def count(self) -> int:
        return self._count

    @property
    def backend(self) -> str:
        return self._backend


def rebuild(
    embeddings: Iterable[np.ndarray],
    *,
    out_path: Path,
    dim: int,
    metric: str = "cosine",
    max_elements: int = 100_000,
) -> HnswIndex:
    """Build a fresh index from an iterable of (D,) arrays. Replaces any
    existing file at *out_path*.

    Crash-rebuild entry point: if a previous run left a corrupt
    `faces.hnsw`, the caller does `out_path.unlink(missing_ok=True)`
    and then calls this. We don't auto-magic the rebuild so the user
    knows their on-disk cache was destroyed.
    """
    out_path = Path(out_path)
    if out_path.exists():
        out_path.unlink()
    idx = HnswIndex(dim=dim, metric=metric, max_elements=max_elements)
    batch: list[np.ndarray] = []
    BATCH = 1024
    for emb in embeddings:
        batch.append(emb)
        if len(batch) >= BATCH:
            idx.add_items(np.stack(batch).astype(np.float32, copy=False))
            batch.clear()
    if batch:
        idx.add_items(np.stack(batch).astype(np.float32, copy=False))
    idx.save(out_path)
    return idx