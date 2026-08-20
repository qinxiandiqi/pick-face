"""Tests for the AC-1 evaluation harness (tests/acceptance/run_eval.py)."""

from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

# Load run_eval.py directly (it lives outside the src/ tree).
_REPO = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "run_eval", _REPO / "packages" / "pick-face" / "tests" / "acceptance" / "run_eval.py"
)
assert _spec and _spec.loader
run_eval = importlib.util.module_from_spec(_spec)
sys.modules["run_eval"] = run_eval
_spec.loader.exec_module(run_eval)
EvalResult = run_eval.EvalResult
_pairwise_metrics = run_eval._pairwise_metrics
_load_truth = run_eval._load_truth
run_eval_fn = run_eval.run_eval


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rel_path", "person_id"])
        writer.writerows(rows)


def _seed_db(path: Path, faces: list[tuple[int, str]]) -> None:
    """faces: list of (cluster_id_or_-1, rel_path) tuples."""
    con = sqlite3.connect(str(path))
    # Minimal schema the harness needs.
    con.executescript(
        """
        CREATE TABLE source(id INTEGER PRIMARY KEY, path TEXT, rel_path TEXT);
        CREATE TABLE face(
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            cluster_id INTEGER
        );
        """
    )
    for i, (cid, rp) in enumerate(faces, 1):
        con.execute(
            "INSERT INTO source(id, path, rel_path) VALUES (?, ?, ?)",
            (i, f"/x/{rp}", rp),
        )
        con.execute(
            "INSERT INTO face(id, source_id, cluster_id) VALUES (?, ?, ?)",
            (i, i, cid if isinstance(cid, int) and cid >= 0 else None),
        )
    con.commit()
    con.close()


def test_load_truth_round_trip(tmp_pure: Path) -> None:
    csv = tmp_pure / "truth.csv"
    _write_csv(csv, [("a.jpg", "alice"), ("b.jpg", "alice"), ("c.jpg", "bob")])
    truth = _load_truth(csv)
    assert truth == {"a.jpg": "alice", "b.jpg": "alice", "c.jpg": "bob"}


def test_pairwise_metrics_perfect_clustering() -> None:
    # 3 alice + 2 bob in 2 clusters
    items = [
        ("a1", 1),
        ("a2", 1),
        ("a3", 1),
        ("b1", 2),
        ("b2", 2),
    ]
    truth = {"a1": "alice", "a2": "alice", "a3": "alice", "b1": "bob", "b2": "bob"}
    pp, pr, b3_f1, n, nc, np = _pairwise_metrics(items, truth)
    assert pp == 1.0
    assert pr == 1.0
    assert b3_f1 == 1.0


def test_pairwise_metrics_imperfect_clustering() -> None:
    # cluster 1 has a1, a2, b1 (one wrong); cluster 2 has b2 (alone)
    items = [("a1", 1), ("a2", 1), ("b1", 1), ("b2", 2)]
    truth = {"a1": "alice", "a2": "alice", "b1": "bob", "b2": "bob"}
    pp, pr, b3_f1, n, nc, np = _pairwise_metrics(items, truth)
    # pairs in cluster 1: (a1,a2) same; (a1,b1) diff; (a2,b1) diff → 1 of 3 same
    assert 0 < pp < 1
    # same-person pairs: alice={a1,a2} → 1 pair; bob={b1,b2} → 1 pair → 2 total
    # TP = 1 (the alice pair); so recall = 1/2 = 0.5
    assert pr == 0.5
    # B³ F1 should be lower than 1
    assert b3_f1 < 1


def test_pairwise_metrics_skips_noise() -> None:
    items = [("a1", -1), ("a2", 1), ("b1", 1)]
    truth = {"a1": "alice", "a2": "alice", "b1": "bob"}
    # cluster 1 = {a2, b1} → 0 same-person pairs
    pp, pr, b3_f1, n, nc, np = _pairwise_metrics(items, truth)
    assert n == 2  # a1 is noise and skipped


def test_run_eval_writes_json(tmp_pure: Path) -> None:
    db = tmp_pure / "index.sqlite"
    _seed_db(db, [(1, "a1"), (1, "a2"), (2, "b1")])
    truth_csv = tmp_pure / "truth.csv"
    _write_csv(truth_csv, [("a1", "x"), ("a2", "x"), ("b1", "y")])
    truth = _load_truth(truth_csv)
    out = tmp_pure / "report.json"
    result = run_eval_fn(db, truth, out)
    assert isinstance(result, EvalResult)
    assert result.ac1_pass is True  # all metrics at 1.0
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert "pairwise_precision" in parsed


def test_run_eval_without_truth_returns_null_metrics(tmp_pure: Path) -> None:
    db = tmp_pure / "index.sqlite"
    _seed_db(db, [(1, "a1"), (1, "a2")])
    out = tmp_pure / "report.json"
    result = run_eval_fn(db, None, out)
    assert result.ac1_pass is None
    assert result.pairwise_precision is None


def test_run_eval_fails_when_thresholds_missed(tmp_pure: Path) -> None:
    """Deliberately construct a broken clustering and verify ac1_pass=False."""
    db = tmp_pure / "index.sqlite"
    # cluster 1 = {a1, a2, b1, b2, c1}  → all mixed → low precision
    _seed_db(db, [(1, "a1"), (1, "a2"), (1, "b1"), (1, "b2"), (1, "c1"), (2, "c2")])
    truth_csv = tmp_pure / "truth.csv"
    _write_csv(
        truth_csv,
        [
            ("a1", "alice"),
            ("a2", "alice"),
            ("b1", "bob"),
            ("b2", "bob"),
            ("c1", "carol"),
            ("c2", "carol"),
        ],
    )
    truth = _load_truth(truth_csv)
    out = tmp_pure / "report.json"
    result = run_eval_fn(db, truth, out)
    assert result.ac1_pass is False
    assert result.pairwise_precision < 0.95
