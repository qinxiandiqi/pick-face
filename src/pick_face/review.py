"""Review decisions: merge / split / remove / rename.

Reference:
- docs/03 §7 (review / review apply commands)
- docs/05 §3 (review_decision schema)
- docs/09 §6.4 (decision application order)

The CLI workflow:
  1. `pick-face review interactive` (TUI) lets a human mark decisions.
  2. Decisions are saved as a JSON file (TUI is M3 scope).
  3. `pick-face review apply <file>` reads the JSON and applies each
     decision to the SQLite DB, then re-runs the link stage.

Decision schema (one per line in the JSON array, or as a top-level array):

  {
    "kind": "must_link" | "cannot_link" | "remove" | "rename",
    "face_a": 123,            # required for must_link / cannot_link
    "face_b": 456,            # required for must_link / cannot_link
    "face_id": 789,           # required for remove
    "cluster_id": 1,          # required for rename
    "label": "Alice",         # required for rename
    "applied_at": "2026-07-30T12:00:00Z"  # optional, defaults to now
  }
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ReviewDecision:
    kind: str
    face_a: int | None = None
    face_b: int | None = None
    face_id: int | None = None
    cluster_id: int | None = None
    label: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d = {k: v for k, v in d.items() if v is not None}
        d["applied_at"] = datetime.now(tz=timezone.utc).isoformat()
        return d


def load_decisions(path: Path) -> list[ReviewDecision]:
    """Parse a JSON file into ReviewDecisions.

    Accepts either a top-level array or a {"decisions": [...]} wrapper.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "decisions" in raw:
        items = raw["decisions"]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(f"unsupported review file shape: {type(raw).__name__}")
    out: list[ReviewDecision] = []
    for i, item in enumerate(items):
        try:
            out.append(ReviewDecision(**item))
        except TypeError as e:
            raise ValueError(f"decision #{i} malformed: {e}") from e
    return out


def apply_decisions(
    conn: sqlite3.Connection, decisions: list[ReviewDecision]
) -> tuple[int, int, int, int]:
    """Apply each decision to the DB; return counts per kind.

    For must_link: union of face_a.cluster_id and face_b.cluster_id
    (if different, face_b's cluster_id is rewritten and merged into
    face_a's via cluster.merged_into).
    For cannot_link: if both faces share a cluster_id, split them by
    putting face_b into a new cluster.
    For remove: mark face.review_state='removed' (does NOT delete the
    face row — we keep the embedding for audit).
    For rename: update cluster.label where id matches.

    Returns:
        (must_link, cannot_link, removed, renamed) counts.
    """
    counts = {"must_link": 0, "cannot_link": 0, "remove": 0, "rename": 0}
    with conn:
        for d in decisions:
            if d.kind == "must_link":
                _apply_must_link(conn, d)
                counts["must_link"] += 1
            elif d.kind == "cannot_link":
                _apply_cannot_link(conn, d)
                counts["cannot_link"] += 1
            elif d.kind == "remove":
                _apply_remove(conn, d)
                counts["remove"] += 1
            elif d.kind == "rename":
                _apply_rename(conn, d)
                counts["rename"] += 1
            else:
                raise ValueError(f"unknown decision kind: {d.kind!r}")

            _record(conn, d)
    return counts["must_link"], counts["cannot_link"], counts["remove"], counts["rename"]


def _now() -> float:
    import time

    return time.time()


def _record(conn: sqlite3.Connection, d: ReviewDecision) -> None:
    payload = json.dumps(d.to_dict(), sort_keys=True)
    conn.execute(
        """INSERT INTO review_decision(
            kind, face_a, face_b, cluster_id, payload, created_at, applied_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            d.kind,
            d.face_a,
            d.face_b,
            d.cluster_id,
            payload,
            _now(),
            _now(),
        ),
    )


def _apply_must_link(conn: sqlite3.Connection, d: ReviewDecision) -> None:
    if d.face_a is None or d.face_b is None:
        raise ValueError("must_link needs face_a and face_b")
    rows = conn.execute(
        "SELECT id, cluster_id FROM face WHERE id IN (?, ?)",
        (d.face_a, d.face_b),
    ).fetchall()
    if len(rows) != 2:
        raise ValueError(f"must_link: faces {d.face_a}/{d.face_b} not both in DB")
    a, b = rows
    a_cluster = a["cluster_id"]
    b_cluster = b["cluster_id"]
    if a_cluster == b_cluster:
        return  # already linked; nothing to do
    target = a_cluster if a_cluster is not None else b_cluster
    other = b_cluster if target == a_cluster else a_cluster
    if target is None or other is None:
        # One of them is noise → just adopt the other's cluster.
        conn.execute(
            "UPDATE face SET cluster_id=? WHERE id=?",
            (target if target is not None else other, d.face_b if a_cluster is None else d.face_a),
        )
        return
    # Mark the 'other' cluster as merged_into the target.
    conn.execute(
        "UPDATE cluster SET merged_into=? WHERE id=?",
        (target, other),
    )
    # Move all faces of 'other' to 'target'.
    conn.execute(
        "UPDATE face SET cluster_id=? WHERE cluster_id=?",
        (target, other),
    )


def _apply_cannot_link(conn: sqlite3.Connection, d: ReviewDecision) -> None:
    if d.face_a is None or d.face_b is None:
        raise ValueError("cannot_link needs face_a and face_b")
    rows = conn.execute(
        "SELECT id, cluster_id FROM face WHERE id IN (?, ?)",
        (d.face_a, d.face_b),
    ).fetchall()
    if len(rows) != 2:
        raise ValueError(f"cannot_link: faces {d.face_a}/{d.face_b} not both in DB")
    a, b = rows
    if a["cluster_id"] != b["cluster_id"] or a["cluster_id"] is None:
        return  # already separated; nothing to do
    # Split: create a new cluster for b, leave a alone.
    cur = conn.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) VALUES (?, 0, ?, ?)",
        (f"split-{d.face_b}", _now(), _now()),
    )
    new_id = int(cur.lastrowid)
    conn.execute("UPDATE face SET cluster_id=? WHERE id=?", (new_id, d.face_b))


def _apply_remove(conn: sqlite3.Connection, d: ReviewDecision) -> None:
    if d.face_id is None:
        raise ValueError("remove needs face_id")
    conn.execute(
        "UPDATE face SET review_state='removed' WHERE id=?",
        (d.face_id,),
    )


def _apply_rename(conn: sqlite3.Connection, d: ReviewDecision) -> None:
    if d.cluster_id is None or not d.label:
        raise ValueError("rename needs cluster_id and label")
    conn.execute(
        "UPDATE cluster SET label=? WHERE id=?",
        (d.label, d.cluster_id),
    )
