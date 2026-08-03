"""Tests for low_confidence_faces.json (T-105, M2 / docs/04 §2.5 + docs/09 §10).

We seed a tiny DB with 3 clusters of known similarity, mark one face per
cluster as `low_confidence` (cluster_prob < threshold), and verify:
  - the JSON schema + run_id + threshold fields are emitted;
  - only faces below threshold AND non-removed AND non-noise appear;
  - sorting is worst-first (lowest similarity at the top);
  - removed faces are filtered out;
  - noise (cluster_id IS NULL) faces are filtered out;
  - similarity is rounded to 4 decimals.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from pick_face.index import open_db
from pick_face.reporter import (
    collect_low_confidence_faces,
    write_low_confidence_json,
)


def _seed_db(db: Path) -> tuple[int, int, int, int, int]:
    """Create 3 clusters with faces of known similarity.

    Returns (f_high, f_mid, f_low, f_removed, f_noise).
    """
    con = open_db(db)
    now = time.time()

    # 1 source row that's referenced by every face
    con.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen) "
        "VALUES ('/x/a.jpg', 'a.jpg', 1, 1.0, 'h', 'active', ?, ?)",
        (now, now),
    )
    sid = con.execute("SELECT id FROM source WHERE rel_path='a.jpg'").fetchone()["id"]

    # 3 clusters
    cluster_ids = []
    for i in range(3):
        con.execute(
            "INSERT INTO cluster(label, size, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (f"person-{i + 1:04d}", now, now),
        )
        cluster_ids.append(
            con.execute(
                "SELECT id FROM cluster WHERE label=?", (f"person-{i + 1:04d}",)
            ).fetchone()["id"]
        )

    def _insert_face(cluster_id: int | None, prob: float | None, state: str = "auto") -> int:
        # 2048 random bytes stand in for the embedding BLOB.
        con.execute(
            """INSERT INTO face(
                source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                det_score, embedding, model_version, norm,
                cluster_id, cluster_prob, review_state
            ) VALUES (?, 0, 0, 10, 10, 0.9, ?, 'test@0', 1.0, ?, ?, ?)""",
            (sid, os.urandom(2048), cluster_id, prob, state),
        )
        return int(con.execute("SELECT last_insert_rowid()").fetchone()[0])

    f_high = _insert_face(cluster_ids[0], 0.85)   # above threshold
    f_mid = _insert_face(cluster_ids[1], 0.45)    # above default 0.40
    f_low = _insert_face(cluster_ids[2], 0.21)    # below default 0.40 → emits
    f_removed = _insert_face(cluster_ids[0], 0.10, state="removed")
    f_noise = _insert_face(None, None, state="auto")  # no cluster

    con.commit()
    con.close()
    return f_high, f_mid, f_low, f_removed, f_noise


def test_collect_filters_below_threshold(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    f_high, f_mid, f_low, f_removed, f_noise = _seed_db(db)

    con = open_db(db)
    try:
        rows = collect_low_confidence_faces(con, threshold=0.40)
    finally:
        con.close()

    ids = [r["face_id"] for r in rows]
    assert f_low in ids
    assert f_high not in ids
    assert f_mid not in ids
    assert f_removed not in ids
    assert f_noise not in ids


def test_collect_sorts_worst_first(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _, _, _, _, _ = _seed_db(db)

    # Add 2 more low-confidence faces with different similarities.
    con = open_db(db)
    now = time.time()
    cid = con.execute("SELECT id FROM cluster LIMIT 1").fetchone()["id"]
    sid = con.execute("SELECT id FROM source LIMIT 1").fetchone()["id"]
    for prob in (0.30, 0.05):
        con.execute(
            """INSERT INTO face(
                source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                det_score, embedding, model_version, norm,
                cluster_id, cluster_prob, review_state
            ) VALUES (?, 0,0,10,10, 0.9, ?, 'test@0', 1.0, ?, ?, 'auto')""",
            (sid, os.urandom(2048), cid, prob),
        )
    con.commit()
    rows = collect_low_confidence_faces(con, threshold=0.40)
    con.close()

    sims = [r["similarity"] for r in rows]
    assert sims == sorted(sims), f"expected ascending sort, got {sims}"


def test_collect_returns_empty_when_no_low_confidence(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    con = open_db(db)
    now = time.time()
    con.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen) "
        "VALUES ('/x/a.jpg', 'a.jpg', 1, 1.0, 'h', 'active', ?, ?)",
        (now, now),
    )
    sid = con.execute("SELECT id FROM source").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('person-0001', 0, ?, ?)",
        (now, now),
    )
    cid = con.execute("SELECT id FROM cluster").fetchone()["id"]
    # Only one face with similarity 0.85 (well above 0.40).
    con.execute(
        """INSERT INTO face(
            source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
            det_score, embedding, model_version, norm,
            cluster_id, cluster_prob
        ) VALUES (?, 0,0,10,10, 0.9, ?, 'test@0', 1.0, ?, 0.85)""",
        (sid, os.urandom(2048), cid),
    )
    con.commit()

    rows = collect_low_confidence_faces(con, threshold=0.40)
    con.close()
    assert rows == []


def test_write_low_confidence_json_shape(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    f_high, f_mid, f_low, _, _ = _seed_db(db)

    out_dir = tmp_pure / "out"
    out_dir.mkdir()
    con = open_db(db)
    try:
        target = write_low_confidence_json(
            con, out_dir=out_dir, threshold=0.40, run_id="2026-08-03T12-00-00",
        )
    finally:
        con.close()

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"] == "pick-face/low_confidence_faces@1"
    assert payload["run_id"] == "2026-08-03T12-00-00"
    assert payload["threshold"] == 0.40
    assert payload["count"] == len(payload["faces"])
    assert payload["count"] >= 1
    # Only f_low should be in the file.
    ids = [f["face_id"] for f in payload["faces"]]
    assert f_low in ids
    assert f_high not in ids
    assert f_mid not in ids

    # Schema fields on every face.
    sample = payload["faces"][0]
    for k in (
        "face_id", "cluster_id", "cluster_label", "similarity",
        "source_id", "source_path", "rel_path", "review_state",
    ):
        assert k in sample, f"missing field {k!r} in {sample}"


def test_write_low_confidence_json_similarity_precision(tmp_pure: Path) -> None:
    """similarity is rounded to 4 decimals (no float junk in the JSON)."""
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    con = open_db(db)
    now = time.time()
    con.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen) "
        "VALUES ('/x/a.jpg', 'a.jpg', 1, 1.0, 'h', 'active', ?, ?)",
        (now, now),
    )
    sid = con.execute("SELECT id FROM source").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('person-0001', 0, ?, ?)",
        (now, now),
    )
    cid = con.execute("SELECT id FROM cluster").fetchone()["id"]
    con.execute(
        """INSERT INTO face(
            source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
            det_score, embedding, model_version, norm,
            cluster_id, cluster_prob
        ) VALUES (?, 0,0,10,10, 0.9, ?, 'test@0', 1.0, ?, 0.123456789)""",
        (sid, os.urandom(2048), cid),
    )
    con.commit()

    out_dir = tmp_pure / "out"
    out_dir.mkdir()
    target = write_low_confidence_json(con, out_dir=out_dir, threshold=0.40)
    con.close()

    payload = json.loads(target.read_text(encoding="utf-8"))
    # Rounded to 4 decimals → 0.1235
    assert payload["faces"][0]["similarity"] == 0.1235


def test_write_low_confidence_creates_missing_dir(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)

    out_dir = tmp_pure / "deep" / "nested" / "out"
    con = open_db(db)
    try:
        target = write_low_confidence_json(con, out_dir=out_dir, threshold=0.40)
    finally:
        con.close()
    assert target.exists()
    assert target.parent == out_dir


def test_threshold_param_is_honored(tmp_pure: Path) -> None:
    """Setting a high threshold should flag even the 'high' face."""
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    f_high, f_mid, f_low, _, _ = _seed_db(db)

    con = open_db(db)
    try:
        rows = collect_low_confidence_faces(con, threshold=0.95)
    finally:
        con.close()
    ids = [r["face_id"] for r in rows]
    # Every face with prob < 0.95 (i.e. all three) appears.
    assert f_low in ids
    assert f_mid in ids
    assert f_high in ids