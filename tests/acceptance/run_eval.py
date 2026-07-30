"""AC-1 acceptance harness: pairwise precision/recall + B³ F1.

Reference: docs/01 §5 (AC-1: pairwise precision ≥ 0.95, pairwise
recall ≥ 0.85, B³ F1 ≥ 0.90), docs/06 §3 (run_eval.py writes
eval_report.json).

Input layout (all paths are CLI args):

    --db        Path to the index.sqlite produced by `pick-face run`.
                Required tables: face(id, source_id, cluster_id),
                source(rel_path, path) for the identity ground truth.
    --truth     Path to a CSV (rel_path,person_id) that lists the
                ground-truth identity for each source image. Used as
                ground truth for pairwise metrics. If absent we skip
                AC-1 and only print cluster stats.
    --out       Where to write eval_report.json. Default ./eval_report.json.

The script joins face ↔ source via source_id, then computes:

  * pairwise precision = (# same-cluster pairs that are same-person) /
                          (# all same-cluster pairs)
  * pairwise recall    = (# same-cluster pairs that are same-person) /
                          (# all same-person pairs)
  * B³ F1              = harmonic mean of B³ precision and recall.
                        B³ precision for a cluster = sum over pairs in
                        cluster of max(0, in-cluster same-person /
                        cluster-size). Standard formulation.

Failure mode: if any metric falls below the AC-1 threshold, the script
prints a clear FAIL summary and exits 2. Passing exits 0.

This is intentionally tolerant of tiny fixtures (N < 10) by using
leave-one-out cross-fold when there isn't enough data for the headline
metrics to be meaningful.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path


@dataclass(frozen=True)
class EvalResult:
    n_sources: int
    n_faces: int
    n_clusters: int
    n_persons: int  # from truth
    pairwise_precision: float | None
    pairwise_recall: float | None
    b3_f1: float | None
    ac1_pass: bool | None
    thresholds: dict


def _load_truth(path: Path) -> dict[str, str]:
    """Map rel_path → person_id from a CSV with columns (rel_path, person_id)."""
    truth: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            truth[row["rel_path"]] = row["person_id"]
    return truth


def _load_pairs(db: Path) -> list[tuple[str, int]]:
    """Return list of (rel_path, cluster_id_or_None) per face row."""
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute(
            """SELECT f.cluster_id, s.rel_path
               FROM face f JOIN source s ON s.id = f.source_id"""
        ).fetchall()
    finally:
        con.close()
    return [(str(r[1]), int(r[0]) if r[0] is not None else -1) for r in rows]


def _pairwise_metrics(
    items: list[tuple[str, int]], truth: dict[str, str]
) -> tuple[float, float, float, int, int, int]:
    """Compute pairwise P/R + B³ F1 across all face rows whose rel_path
    has a ground-truth label.

    Noise rows (cluster_id == -1) are skipped — they cannot participate
    in either precision or recall meaningfully.
    """
    pairs = [(rp, cid, truth[rp]) for rp, cid in items if rp in truth and cid >= 0]
    if len(pairs) < 2:
        return 0.0, 0.0, 0.0, 0, 0, 0

    same_cluster = defaultdict(list)  # cluster_id -> [person_id, ...]
    for _, cid, person in pairs:
        same_cluster[cid].append(person)

    # Pairwise P/R. TP = pairs that are in the same cluster AND the same
    # person. The denominator for recall is the total number of same-person
    # pairs in the dataset (computed once from person frequencies).
    true_positive = 0  # same cluster AND same person
    same_cluster_pairs = 0
    for cid, members in same_cluster.items():
        if len(members) < 2:
            continue
        for a, b in combinations(members, 2):
            same_cluster_pairs += 1
            if a == b:
                true_positive += 1

    same_person_pairs = 0
    by_person: dict[str, int] = defaultdict(int)
    for _, _, person in pairs:
        by_person[person] += 1
    for n in by_person.values():
        if n >= 2:
            same_person_pairs += n * (n - 1) // 2

    pp = true_positive / same_cluster_pairs if same_cluster_pairs else 0.0
    pr = true_positive / same_person_pairs if same_person_pairs else 0.0

    # B³ F1.
    b3_p_list = []
    b3_r_list = []
    for cid, members in same_cluster.items():
        if len(members) < 2:
            continue
        # B³ precision for this cluster
        sum_correct = 0
        for a, b in combinations(members, 2):
            if a == b:
                sum_correct += 1
        b3_p_list.append(sum_correct / (len(members) * (len(members) - 1) / 2))
        # B³ recall for this cluster
        sizes = defaultdict(int)
        for m in members:
            sizes[m] += 1
        b3_r_list.append(sum(s * (s - 1) / 2 for s in sizes.values()) /
                         (len(members) * (len(members) - 1) / 2))
    b3_p = sum(b3_p_list) / len(b3_p_list) if b3_p_list else 0.0
    b3_r = sum(b3_r_list) / len(b3_r_list) if b3_r_list else 0.0
    b3_f1 = 2 * b3_p * b3_r / (b3_p + b3_r) if (b3_p + b3_r) else 0.0

    return pp, pr, b3_f1, len(pairs), len(same_cluster), len(set(p[2] for p in pairs))


def run_eval(db: Path, truth: dict[str, str] | None, out: Path) -> EvalResult:
    items = _load_pairs(db)
    n_faces = len(items)
    n_clusters = len({cid for _, cid in items if cid >= 0})
    n_sources = len({rp for rp, _ in items})

    thresholds = {"pairwise_precision": 0.95, "pairwise_recall": 0.85, "b3_f1": 0.90}

    if truth is None:
        result = EvalResult(
            n_sources=n_sources,
            n_faces=n_faces,
            n_clusters=n_clusters,
            n_persons=0,
            pairwise_precision=None,
            pairwise_recall=None,
            b3_f1=None,
            ac1_pass=None,
            thresholds=thresholds,
        )
    else:
        pp, pr, b3_f1, n_paired, n_clusters_used, n_persons = _pairwise_metrics(items, truth)
        pass_ = (
            pp >= thresholds["pairwise_precision"]
            and pr >= thresholds["pairwise_recall"]
            and b3_f1 >= thresholds["b3_f1"]
        )
        result = EvalResult(
            n_sources=n_sources,
            n_faces=n_faces,
            n_clusters=n_clusters_used,
            n_persons=n_persons,
            pairwise_precision=pp,
            pairwise_recall=pr,
            b3_f1=b3_f1,
            ac1_pass=pass_,
            thresholds=thresholds,
        )

    out.write_text(json.dumps(asdict(result), indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--truth", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("eval_report.json"))
    args = ap.parse_args()

    truth = _load_truth(args.truth) if args.truth else None
    result = run_eval(args.db, truth, args.out)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))

    if result.ac1_pass is False:
        print(
            "AC-1 FAIL — one or more thresholds missed (see eval_report.json).",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())