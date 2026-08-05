"""Benchmark harness for M3 / T-205.

Reference:
- docs/06 §T-205 (10k synthetic-image benchmark, CPU + GPU variants)
- docs/09 §13 (perf report: throughput / face / minute; largest cluster size)

We don't actually decode 10k JPEG files — the cost is dominated by the
detector/embedder, which depends on the model pack. Instead, we exercise
the in-process hot paths with synthetic data:

  1. Generate N face embeddings (k_people blobs + noise).
  2. Time `cluster_embeddings` over the matrix.
  3. Time `face_to_cluster_similarity` over the matrix.
  4. Time HNSW index build + kNN queries.
  5. Emit a JSON + Markdown perf report.

Outputs:
  - bench/<timestamp>/perf_report.json
  - bench/<timestamp>/perf_report.md

The numbers are deterministic for a given seed so we can pin them in
`tests/unit/test_bench.py` to a sane range (no flakiness).
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class BenchResult:
    name: str
    elapsed_sec: float
    items: int
    extra: dict = field(default_factory=dict)

    def rate(self) -> float:
        return self.items / self.elapsed_sec if self.elapsed_sec > 0 else 0.0


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n = np.where(n < 1e-12, 1.0, n)
    return v / n


def _synth_embeddings(n: int, k_people: int, dim: int, seed: int) -> np.ndarray:
    """Generate N unit-norm embeddings: k gaussian blobs + noise.

    Cheap, deterministic, doesn't depend on the model pack.
    """
    rng = np.random.default_rng(seed)
    # k mutually orthogonal unit anchors
    ids = rng.permutation(dim)[:k_people]
    centers = np.zeros((k_people, dim), dtype=np.float32)
    for i, idx in enumerate(ids):
        centers[i, idx] = 1.0
    per = max(1, n // k_people)
    blobs = []
    for c in centers:
        noise = rng.normal(scale=0.05, size=(per, dim)).astype(np.float32)
        b = noise + c[None, :]
        b = _l2(b)
        blobs.append(b)
    # Add remaining points as pure noise so total == n.
    if sum(b.shape[0] for b in blobs) < n:
        extra = rng.normal(scale=0.5, size=(n - sum(b.shape[0] for b in blobs), dim)).astype(
            np.float32
        )
        blobs.append(_l2(extra))
    out = np.concatenate(blobs, axis=0)[:n]
    return out


def _time(call: Callable[[], object]) -> tuple[float, object]:
    t0 = time.perf_counter()
    out = call()
    return time.perf_counter() - t0, out


def run_benchmark(
    *,
    n_embeddings: int = 10_000,
    k_people: int = 50,
    dim: int = 512,
    seed: int = 0,
) -> dict:
    """Run the in-process hot-path benchmark and return the report dict."""
    from pick_face.core.config import ClusteringConfig
    from pick_face.ingest.cluster import (
        cluster_embeddings,
        face_to_cluster_similarity,
    )
    from pick_face.ingest.embedder import cosine_distance_matrix

    cfg = ClusteringConfig(min_cluster_size=3, min_samples=2, merge_threshold=0.55)
    embs = _synth_embeddings(n_embeddings, k_people, dim, seed)

    results: list[BenchResult] = []

    # 1. Pairwise cosine distance (the N^2 baseline we're trying to escape).
    elapsed, _ = _time(lambda: cosine_distance_matrix(embs))
    results.append(BenchResult("cosine_distance_matrix", elapsed, embs.shape[0]))

    # 2. HDBSCAN + 2-pass centroid merge over the full set.
    elapsed, res = _time(lambda: cluster_embeddings(embs, cfg=cfg))
    results.append(
        BenchResult(
            "cluster_embeddings",
            elapsed,
            embs.shape[0],
            extra={"n_clusters": int(res.n_clusters), "n_noise": int(res.n_noise)},
        )
    )

    # 3. face_to_cluster_similarity (centroid lookup).
    elapsed, _ = _time(lambda: face_to_cluster_similarity(embs, res.labels))
    results.append(
        BenchResult(
            "face_to_cluster_similarity",
            elapsed,
            embs.shape[0],
        )
    )

    # 4. HNSW index build + 100 random queries.
    hnsw_result: dict = {"backend": "n/a"}
    try:
        from pick_face.store.index_hnsw import HnswIndex

        elapsed, idx = _time(lambda: HnswIndex(dim=dim, metric="cosine", max_elements=n_embeddings))
        build_elapsed = elapsed
        hnsw_result["backend"] = idx.backend

        add_elapsed, _ = _time(lambda: idx.add_items(embs))

        rng = np.random.default_rng(seed + 1)
        q = rng.normal(size=(100, dim)).astype(np.float32)
        q = _l2(q)
        query_elapsed, _ = _time(lambda: idx.knn_query(q, k=5))

        results.append(
            BenchResult(
                "hnsw_build",
                build_elapsed,
                1,
                extra={"max_elements": n_embeddings},
            )
        )
        results.append(
            BenchResult(
                "hnsw_add_items",
                add_elapsed,
                embs.shape[0],
                extra={"backend": idx.backend},
            )
        )
        results.append(
            BenchResult(
                "hnsw_knn_query_100x5",
                query_elapsed,
                100,
                extra={"k": 5, "backend": idx.backend},
            )
        )
    except Exception as e:
        hnsw_result["error"] = str(e)

    # 5. Report summary.
    payload = {
        "schema": "pick-face/perf_report@1",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "cpu_count": os.cpu_count(),
        },
        "config": {
            "n_embeddings": n_embeddings,
            "k_people": k_people,
            "dim": dim,
            "seed": seed,
        },
        "hnsw": hnsw_result,
        "results": [asdict(r) for r in results],
    }
    return payload


def write_report(payload: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write perf_report.json + perf_report.md to *out_dir*."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "perf_report.json"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    md_lines = [
        "# pick-face Performance Report",
        "",
        f"- **Generated**: `{payload['generated_at']}`",
        f"- **Platform**: `{payload['host']['platform']}`",
        f"- **Python**: `{payload['host']['python']}`",
        f"- **CPU count**: `{payload['host']['cpu_count']}`",
        f"- **HNSW backend**: `{payload['hnsw'].get('backend', 'n/a')}`",
        "",
        "## Workload",
        "",
        f"- **Embeddings**: {payload['config']['n_embeddings']:,}",
        f"- **People (clusters)**: {payload['config']['k_people']}",
        f"- **Embedding dim**: {payload['config']['dim']}",
        "",
        "## Hot-path timings",
        "",
        "| Stage | Items | Elapsed (s) | Rate (items/s) |",
        "|---|---:|---:|---:|",
    ]
    for r in payload["results"]:
        rate = r["items"] / r["elapsed_sec"] if r["elapsed_sec"] > 0 else 0
        md_lines.append(
            f"| `{r['name']}` | {r['items']:,} | {r['elapsed_sec']:.3f} | {rate:,.1f} |"
        )
    md_path = out_dir / "perf_report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, md_path
