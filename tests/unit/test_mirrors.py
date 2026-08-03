"""Tests for T-108: meta.json + index.json mirror generation.

We seed a tiny DB with 2 clusters + 3 sources + 3 links, then verify:
  - meta.json schema + fields per cluster are correct.
  - index.json reflects cluster + link counts (no embeddings).
  - Merged clusters are skipped in meta.json.
  - write_all_cluster_metas writes one file per non-merged cluster.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pick_face.index import open_db
from pick_face.mirrors import (
    INDEX_SCHEMA,
    META_SCHEMA,
    write_all_cluster_metas,
    write_cluster_meta,
    write_index_json,
)


def _seed_db(db: Path) -> None:
    con = open_db(db)
    now = time.time()
    # 3 sources
    for i in range(3):
        con.execute(
            "INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
            (f"/x/{i}.jpg", f"{i}.jpg", 100, 1.0, f"h{i}", now, now),
        )
    sids = [r["id"] for r in con.execute("SELECT id FROM source ORDER BY id").fetchall()]
    # 2 visible clusters + 1 merged
    con.execute(
        "INSERT INTO cluster(label, size, mean_sim, created_at, updated_at) "
        "VALUES ('person-0001', 2, 0.62, ?, ?)",
        (now, now),
    )
    c1 = con.execute("SELECT id FROM cluster WHERE label='person-0001'").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, mean_sim, created_at, updated_at) "
        "VALUES ('person-0002', 1, 0.51, ?, ?)",
        (now, now),
    )
    c2 = con.execute("SELECT id FROM cluster WHERE label='person-0002'").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, mean_sim, created_at, updated_at, merged_into) "
        "VALUES ('person-0003-old', 0, NULL, ?, ?, ?)",
        (now, now, c1),
    )
    # 3 faces: 2 in c1, 1 in c2
    for sid, cid in zip(sids, [c1, c1, c2]):
        con.execute(
            """INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                                det_score, embedding, model_version, norm, cluster_id)
               VALUES (?, 0,0,10,10, 0.9, ?, 'test@0', 1.0, ?)""",
            (sid, os.urandom(2048), cid),
        )
    # 3 links (one per source) into c1 and c2
    con.execute(
        """INSERT INTO link(cluster_id, source_id, rel_path, link_kind, actual_target, created_at)
           VALUES (?, ?, 'a.jpg', 'symlink', '/x/0.jpg', ?)""",
        (c1, sids[0], now),
    )
    con.execute(
        """INSERT INTO link(cluster_id, source_id, rel_path, link_kind, actual_target, created_at)
           VALUES (?, ?, 'b.jpg', 'hardlink', '/x/1.jpg', ?)""",
        (c1, sids[1], now),
    )
    con.execute(
        """INSERT INTO link(cluster_id, source_id, rel_path, link_kind, actual_target, created_at)
           VALUES (?, ?, 'c.jpg', 'copy', '/x/2.jpg', ?)""",
        (c2, sids[2], now),
    )
    con.commit()
    con.close()


def test_meta_json_shape(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)

    con = open_db(db)
    row = con.execute("SELECT id FROM cluster WHERE label='person-0001'").fetchone()
    cid = int(row["id"])
    out_dir = tmp_pure / "person-0001"
    target = write_cluster_meta(con, cid, out_dir)
    con.close()

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"] == META_SCHEMA
    assert payload["schema_version"] == 1
    assert payload["cluster_id"] == cid
    assert payload["label"] == "person-0001"
    assert payload["size"] == 2
    assert payload["mean_sim"] == 0.62
    assert payload["merged_into"] is None
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None
    assert payload["first_seen"] is not None
    assert payload["last_seen"] is not None


def test_meta_json_merged_cluster_is_skipped(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)

    con = open_db(db)
    written = write_all_cluster_metas(con, tmp_pure)
    con.close()

    # Two non-merged clusters → 2 meta.json files.
    labels = sorted(p.parent.name for p in written)
    assert labels == ["person-0001", "person-0002"]
    # No meta.json for the merged cluster.
    assert not (tmp_pure / "person-0003-old" / "meta.json").exists()


def test_meta_json_creates_missing_dir(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    con = open_db(db)
    row = con.execute("SELECT id FROM cluster WHERE label='person-0001'").fetchone()
    cid = int(row["id"])
    target = write_cluster_meta(con, cid, tmp_pure / "deep" / "nested" / "person-0001")
    con.close()
    assert target.exists()
    assert target.name == "meta.json"


def test_index_json_shape(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    out_dir = tmp_pure / "out"
    out_dir.mkdir()
    con = open_db(db)
    target = write_index_json(con, out_dir, run_id="2026-08-03T12-00-00")
    con.close()

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"] == INDEX_SCHEMA
    assert payload["schema_version"] == 1
    assert payload["run_id"] == "2026-08-03T12-00-00"
    assert "generated_at" in payload

    # Totals
    t = payload["totals"]
    assert t["clusters"] == 3  # incl. merged
    assert t["persons"] == 2  # excl. merged
    assert t["links"] == 3
    assert t["faces"] == 3
    assert t["active_sources"] == 3
    assert t["missing_sources"] == 0

    # Clusters list (in DB insertion order)
    cl = payload["clusters"]
    assert len(cl) == 3
    labels = [c["label"] for c in cl]
    assert "person-0001" in labels
    # The merged cluster is included with merged_into set.
    merged = [c for c in cl if c["merged_into"] is not None]
    assert len(merged) == 1

    # Links list mirrors the DB
    ll = payload["links"]
    assert len(ll) == 3
    kinds = sorted(link["link_kind"] for link in ll)
    assert kinds == ["copy", "hardlink", "symlink"]


def test_index_json_omits_embeddings(tmp_pure: Path) -> None:
    """ADR-009: index.json must NEVER contain embeddings."""
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    _seed_db(db)
    out_dir = tmp_pure / "out"
    out_dir.mkdir()
    con = open_db(db)
    target = write_index_json(con, out_dir)
    con.close()
    text = target.read_text(encoding="utf-8")
    # Embeddings are 2048-byte BLOBs; verify there's no large base64/hex blob.
    assert "embedding" not in text
    # Sanity: file size should be small (< 5 KB for this fixture).
    assert target.stat().st_size < 5_000


def test_index_json_handles_empty_db(tmp_pure: Path) -> None:
    """Empty DB → index.json with zeros but no exceptions."""
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    con = open_db(db)
    target = write_index_json(con, tmp_pure)
    con.close()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["totals"]["clusters"] == 0
    assert payload["clusters"] == []
    assert payload["links"] == []
