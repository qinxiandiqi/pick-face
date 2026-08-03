"""Tests for pick_face.review (T-104, M2 / docs/03 §7).

We build a minimal DB with 2 clusters + 4 faces, then exercise:
  - must_link unions two clusters (and marks the smaller merged_into).
  - cannot_link splits two same-cluster faces apart.
  - remove flips review_state to 'removed'.
  - rename changes cluster.label.
  - review_decision rows are appended for audit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pick_face.index import open_db
from pick_face.review import ReviewDecision, apply_decisions, load_decisions


def _seed_db(path: Path) -> None:
    con = open_db(path)
    import time

    now = time.time()
    con.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen) "
        "VALUES ('/x/a.jpg', 'a.jpg', 100, 1.0, 'a1', 'active', ?, ?)",
        (now, now),
    )
    sid = con.execute("SELECT id FROM source WHERE rel_path='a.jpg'").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('person-0001', 0, ?, ?)",
        (now, now),
    )
    c1 = con.execute("SELECT id FROM cluster WHERE label='person-0001'").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('person-0002', 0, ?, ?)",
        (now, now),
    )
    c2 = con.execute("SELECT id FROM cluster WHERE label='person-0002'").fetchone()["id"]
    # 4 faces: f1,f2 in c1; f3,f4 in c2
    for cid in (c1, c1, c2, c2):
        con.execute(
            """INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                                det_score, embedding, model_version, norm, cluster_id)
               VALUES (?, 0,0,10,10, 0.9, ?, 'test@0', 1.0, ?)""",
            (sid, os.urandom(2048), cid),
        )
    con.commit()
    con.close()


def _face_ids_by_cluster(path: Path) -> dict[int, list[int]]:
    con = open_db(path)
    rows = con.execute("SELECT id, cluster_id FROM face ORDER BY id").fetchall()
    con.close()
    out: dict[int, list[int]] = {}
    for r in rows:
        out.setdefault(r["cluster_id"], []).append(r["id"])
    return out


def test_load_decisions_accepts_array(tmp_pure: Path) -> None:
    f = tmp_pure / "decisions.json"
    f.write_text(
        json.dumps(
            [
                {"kind": "must_link", "face_a": 1, "face_b": 2},
                {"kind": "remove", "face_id": 3},
            ]
        ),
        encoding="utf-8",
    )
    decisions = load_decisions(f)
    assert len(decisions) == 2
    assert decisions[0].kind == "must_link"
    assert decisions[1].kind == "remove"


def test_load_decisions_accepts_wrapper(tmp_pure: Path) -> None:
    f = tmp_pure / "d.json"
    f.write_text(json.dumps({"decisions": [{"kind": "rename", "cluster_id": 1, "label": "Alice"}]}))
    decisions = load_decisions(f)
    assert decisions[0].label == "Alice"


def test_load_decisions_accepts_malformed_fields(tmp_pure: Path) -> None:
    """load_decisions is permissive — the strict validation happens at
    apply time so a single broken entry in a batch file surfaces with a
    clear pointer to the bad index instead of failing the whole parse."""
    f = tmp_pure / "d.json"
    f.write_text(json.dumps([{"kind": "must_link"}]))
    # load_decisions succeeds (default None fields are valid dataclass).
    decisions = load_decisions(f)
    assert decisions[0].face_a is None


def test_apply_malformed_must_link_raises(tmp_pure: Path) -> None:
    """A must_link without face_a/face_b raises at apply time."""
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    decisions = [ReviewDecision(kind="must_link")]  # missing face_a/b
    con = open_db(db)
    with pytest.raises(ValueError):
        apply_decisions(con, decisions)
    con.close()


def test_must_link_unions_clusters(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    before = _face_ids_by_cluster(db)
    c1, c2 = sorted(before.keys())
    f_in_c1 = before[c1][0]
    f_in_c2 = before[c2][0]

    decisions = [ReviewDecision(kind="must_link", face_a=f_in_c1, face_b=f_in_c2)]
    con = open_db(db)
    try:
        apply_decisions(con, decisions)
    finally:
        con.close()

    after = _face_ids_by_cluster(db)
    # c2 should now be merged_into c1 and have no faces.
    con = open_db(db)
    row = con.execute("SELECT merged_into FROM cluster WHERE id=?", (c2,)).fetchone()
    con.close()
    assert row["merged_into"] == c1
    assert c2 not in after or len(after[c2]) == 0


def test_cannot_link_splits_same_cluster(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    before = _face_ids_by_cluster(db)
    c1 = sorted(before.keys())[0]
    f_a, f_b = before[c1][0], before[c1][1]

    decisions = [ReviewDecision(kind="cannot_link", face_a=f_a, face_b=f_b)]
    con = open_db(db)
    try:
        apply_decisions(con, decisions)
    finally:
        con.close()

    after = _face_ids_by_cluster(db)
    # f_a still in c1; f_b moved into a brand-new cluster
    assert f_a in after[c1]
    new_clusters = set(after.keys()) - {c1}
    assert any(f_b in after[c] for c in new_clusters)


def test_remove_marks_face_removed(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    con = open_db(db)
    fid = con.execute("SELECT id FROM face LIMIT 1").fetchone()["id"]
    con.close()

    decisions = [ReviewDecision(kind="remove", face_id=fid)]
    con = open_db(db)
    try:
        apply_decisions(con, decisions)
    finally:
        con.close()

    con = open_db(db)
    state = con.execute("SELECT review_state FROM face WHERE id=?", (fid,)).fetchone()[
        "review_state"
    ]
    con.close()
    assert state == "removed"


def test_rename_updates_label(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    con = open_db(db)
    cid = con.execute("SELECT id FROM cluster WHERE label='person-0001'").fetchone()["id"]
    con.close()

    decisions = [ReviewDecision(kind="rename", cluster_id=cid, label="Alice")]
    con = open_db(db)
    try:
        apply_decisions(con, decisions)
    finally:
        con.close()

    con = open_db(db)
    label = con.execute("SELECT label FROM cluster WHERE id=?", (cid,)).fetchone()["label"]
    con.close()
    assert label == "Alice"


def test_apply_records_audit_rows(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    con = open_db(db)
    fid = con.execute("SELECT id FROM face LIMIT 1").fetchone()["id"]
    con.close()
    decisions = [ReviewDecision(kind="remove", face_id=fid)]
    con = open_db(db)
    try:
        apply_decisions(con, decisions)
    finally:
        con.close()

    con = open_db(db)
    rows = con.execute("SELECT kind FROM review_decision").fetchall()
    con.close()
    assert len(rows) == 1
    assert rows[0]["kind"] == "remove"


def test_apply_unknown_kind_raises(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    decisions = [ReviewDecision(kind="frobnicate")]
    con = open_db(db)
    with pytest.raises(ValueError):
        apply_decisions(con, decisions)
    con.close()
