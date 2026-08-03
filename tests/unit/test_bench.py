"""Tests for pick_face.bench (M3 / T-205).

We exercise the benchmark harness with a SMALL workload (500 embeddings,
dim=64) and verify the JSON + markdown reports have the right shape.
Full 10k runs live in CI / manual runs, not the unit suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from pick_face.bench import run_benchmark, write_report


def test_bench_runs_and_returns_payload() -> None:
    payload = run_benchmark(n_embeddings=500, k_people=5, dim=64, seed=0)
    assert payload["schema"] == "pick-face/perf_report@1"
    assert "generated_at" in payload
    assert payload["config"]["n_embeddings"] == 500
    assert "host" in payload
    assert payload["host"]["platform"] != ""
    assert isinstance(payload["host"]["cpu_count"], int)


def test_bench_results_have_required_keys() -> None:
    payload = run_benchmark(n_embeddings=300, k_people=3, dim=32, seed=1)
    names = {r["name"] for r in payload["results"]}
    # Must include the three core hot paths.
    assert "cosine_distance_matrix" in names
    assert "cluster_embeddings" in names
    assert "face_to_cluster_similarity" in names
    for r in payload["results"]:
        assert r["elapsed_sec"] >= 0
        assert r["items"] >= 0


def test_bench_hnsw_block_present() -> None:
    payload = run_benchmark(n_embeddings=200, k_people=3, dim=32, seed=2)
    assert "hnsw" in payload
    # hnswlib may or may not be installed; we always record the backend.
    assert "backend" in payload["hnsw"]


def test_bench_is_deterministic_same_seed() -> None:
    a = run_benchmark(n_embeddings=200, k_people=3, dim=32, seed=42)
    b = run_benchmark(n_embeddings=200, k_people=3, dim=32, seed=42)
    # Same seed → identical embedding matrix; clustering should match.
    assert a["config"] == b["config"]
    a_clusters = next(r for r in a["results"] if r["name"] == "cluster_embeddings")
    b_clusters = next(r for r in b["results"] if r["name"] == "cluster_embeddings")
    assert a_clusters["extra"]["n_clusters"] == b_clusters["extra"]["n_clusters"]


def test_write_report_emits_both_files(tmp_pure: Path) -> None:
    payload = run_benchmark(n_embeddings=200, k_people=3, dim=32, seed=3)
    out_dir = tmp_pure / "bench-out"
    json_path, md_path = write_report(payload, out_dir)
    assert json_path.exists()
    assert md_path.exists()

    # JSON round-trip.
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["schema"] == payload["schema"]

    # Markdown has the headline sections.
    md = md_path.read_text(encoding="utf-8")
    assert "# pick-face Performance Report" in md
    assert "## Workload" in md
    assert "## Hot-path timings" in md
    # Table includes the known stages.
    assert "cosine_distance_matrix" in md
    assert "cluster_embeddings" in md


def test_write_report_creates_missing_dir(tmp_pure: Path) -> None:
    payload = run_benchmark(n_embeddings=100, k_people=2, dim=16, seed=4)
    out_dir = tmp_pure / "deep" / "nested" / "bench"
    json_path, md_path = write_report(payload, out_dir)
    assert json_path.parent == out_dir
    assert md_path.parent == out_dir


def test_bench_small_workload_finishes_fast() -> None:
    """Sanity: 100 embeddings, dim=16, must finish under 5 seconds."""
    import time

    t0 = time.perf_counter()
    payload = run_benchmark(n_embeddings=100, k_people=2, dim=16, seed=5)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0
    assert payload["config"]["n_embeddings"] == 100
