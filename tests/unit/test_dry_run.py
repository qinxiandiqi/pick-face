"""Tests for --dry-run on destructive commands (T-106, M2).

Verifies that gc / prune / rollback / rebuild plan their work and exit
without touching the filesystem or DB when `--dry-run` is passed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pick_face.cli import app
from pick_face.index import open_db


def _seed_db(out: Path) -> None:
    """Same seed as test_cli_lifecycle (replicated to avoid coupling)."""
    db = out / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = open_db(db)
    con.execute(
        """INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, 'active', 0, 0)""",
        (str(out / "src.jpg"), "src.jpg", 100, 1.0, "abc"),
    )
    sid = con.execute("SELECT id FROM source WHERE rel_path='src.jpg'").fetchone()["id"]
    con.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) VALUES (?, 1, 0, 0)",
        ("person-0001",),
    )
    cid = con.execute("SELECT id FROM cluster WHERE label='person-0001'").fetchone()["id"]
    con.execute(
        """INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                            det_score, embedding, model_version, norm, cluster_id)
           VALUES (?, 0, 0, 10, 10, 0.9, ?, 'test@0', 1.0, ?)""",
        (sid, os.urandom(2048), cid),
    )
    con.execute(
        """INSERT INTO link(cluster_id, source_id, rel_path, link_kind, actual_target,
                            created_at) VALUES (?, ?, ?, 'symlink', ?, 0)""",
        (cid, sid, "src.jpg", str(out / "src.jpg")),
    )
    con.commit()
    con.close()


def _call(name: str, out: Path, **kwargs):
    argv = ["pick-face", name, "--out", str(out)]
    name_map = {"keep_n": "keep", "to": "to"}
    for k, v in kwargs.items():
        flag = name_map.get(k, k.replace("_", "-"))
        if isinstance(v, bool):
            if v:
                argv.append(f"--{flag}")
        else:
            argv.extend([f"--{flag}", str(v)])
    old = sys.argv
    sys.argv = argv
    try:
        app(standalone_mode=False)
    except SystemExit:
        pass
    finally:
        sys.argv = old


def test_gc_dry_run_does_not_delete(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    _seed_db(out)
    src = out / "src.jpg"
    src.write_bytes(b"x")
    cluster_dir = out / "person-0001"
    cluster_dir.mkdir()
    entry = cluster_dir / "src.jpg"
    entry.symlink_to(src)
    src.unlink()  # dangling

    _call("gc", out, dry_run=True)
    # Nothing changed on disk; link row still present.
    assert entry.exists() or entry.is_symlink()
    db = out / ".cache" / "index.sqlite"
    con = open_db(db)
    n_links = con.execute("SELECT COUNT(*) AS c FROM link").fetchone()["c"]
    con.close()
    assert n_links == 1


def test_gc_dry_run_with_no_work_exits_clean(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    _seed_db(out)
    src = out / "src.jpg"
    src.write_bytes(b"x")  # target exists, link resolves → nothing to gc
    cluster_dir = out / "person-0001"
    cluster_dir.mkdir()
    entry = cluster_dir / "src.jpg"
    entry.symlink_to(src)

    _call("gc", out, dry_run=True)
    assert entry.exists()


def test_prune_dry_run_does_not_delete(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    import time

    for i in range(4):
        p = out.parent / f"{out.name}.prev-2026-07-30T00-00-0{i}"
        p.mkdir()
        time.sleep(0.02)

    _call("prune", out, keep_n=1, dry_run=True)
    # All four .prev- still exist.
    remaining = [p for p in out.parent.iterdir() if p.name.startswith(f"{out.name}.prev-")]
    assert len(remaining) == 4


def test_rollback_dry_run_does_not_swap(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    out.joinpath("CURRENT").write_text("current-data")
    snap = out.parent / f"{out.name}.prev-2026-07-30T00-00-00"
    snap.mkdir()
    snap.joinpath("RESTORED").write_text("snap-data")

    _call("rollback", out, to="2026-07-30T00-00-00", yes=True, dry_run=True)
    # Nothing moved.
    assert (out / "CURRENT").exists()
    assert (snap / "RESTORED").exists()


def test_rebuild_dry_run_does_not_delete(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    _seed_db(out)
    snap = out.parent / f"{out.name}.prev-old"
    snap.mkdir()

    _call("rebuild", out, dry_run=True)
    # Cache + snapshot untouched.
    assert (out / ".cache").exists()
    assert snap.exists()


def test_rebuild_dry_run_no_targets(tmp_pure: Path) -> None:
    """--dry-run with nothing to delete still exits cleanly."""
    out = tmp_pure / "out"
    out.mkdir()
    # No .cache, no .prev- → plan is empty.
    _call("rebuild", out, dry_run=True)
    assert out.exists()
