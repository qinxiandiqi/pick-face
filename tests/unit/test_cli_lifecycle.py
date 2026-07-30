"""Tests for the gc / prune / rollback / rebuild CLI commands (T-011).

We exercise the four command bodies in isolation via a thin wrapper
that bypasses Typer and directly calls the underlying functions. The
goal is to verify the database + filesystem invariants, not the
Typer plumbing (which has its own smoke test).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from pick_face.index import open_db


def _seed_db(out: Path) -> None:
    """Populate out/.cache/index.sqlite with one active source, one face,
    and one link row pointing at the source file."""
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
    """Invoke one of the gc/prune/rollback/rebuild command bodies."""
    import sys

    from pick_face.cli import app

    yes = kwargs.pop("yes", False)
    argv = ["pick-face", name, "--out", str(out)]
    if yes:
        argv.append("--yes")
    # Map Python param names to the CLI flag names we used in cli.py.
    name_map = {"keep_n": "keep", "to": "to"}
    for k, v in kwargs.items():
        flag = name_map.get(k, k.replace("_", "-"))
        argv.extend([f"--{flag}", str(v)])
    old_argv = sys.argv
    sys.argv = argv
    try:
        app(standalone_mode=False)
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv


def test_gc_removes_dangling_symlink(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    _seed_db(out)
    # Real link entry pointing at a source file that exists.
    src = out / "src.jpg"
    src.write_bytes(b"x")
    cluster_dir = out / "person-0001"
    cluster_dir.mkdir()
    entry = cluster_dir / "src.jpg"
    # Make a real symlink so it exists; then delete the target — symlink
    # now dangles.
    entry.symlink_to(src)
    src.unlink()

    _call("gc", out)
    # The dangling symlink was removed.
    assert not entry.exists()
    # The DB no longer has the link row.
    db = out / ".cache" / "index.sqlite"
    con = open_db(db)
    rows = con.execute("SELECT * FROM link").fetchall()
    con.close()
    assert len(rows) == 0


def test_gc_marks_orphan_sources_missing(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    _seed_db(out)
    # Remove the source file but leave a working symlink to it (simulating
    # someone deleted a file the scanner hadn't seen yet).
    (out / "src.jpg").write_bytes(b"x")
    cluster_dir = out / "person-0001"
    cluster_dir.mkdir()
    entry = cluster_dir / "src.jpg"
    entry.symlink_to(out / "src.jpg")
    (out / "src.jpg").unlink()
    entry.unlink()  # clean link so only the DB row remains

    _call("gc", out)
    db = out / ".cache" / "index.sqlite"
    con = open_db(db)
    status = con.execute("SELECT status FROM source WHERE rel_path='src.jpg'").fetchone()["status"]
    con.close()
    assert status == "missing"


def test_prune_keeps_n_most_recent(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    # Create 5 .prev- siblings with distinct mtimes
    import time

    for i in range(5):
        p = out.parent / f"{out.name}.prev-2026-07-30T00-00-0{i}"
        p.mkdir()
        time.sleep(0.02)  # ensure distinct mtimes

    _call("prune", out, keep_n=2)
    remaining = sorted(p for p in out.parent.iterdir() if p.name.startswith(f"{out.name}.prev-"))
    assert len(remaining) == 2


def test_prune_drops_empty_archive_dirs(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    archive = out / "_archive"
    nested = archive / "deep" / "deeper"
    nested.mkdir(parents=True)
    _call("prune", out, keep_n=3)
    # Empty directories cleaned
    assert not (out / "_archive" / "deep" / "deeper").exists()


def test_rollback_swaps_current_with_named_snapshot(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    out.joinpath("CURRENT").write_text("current-data")
    snap = out.parent / f"{out.name}.prev-2026-07-30T00-00-00"
    snap.mkdir()
    snap.joinpath("RESTORED").write_text("snap-data")

    _call("rollback", out, yes=True, to="2026-07-30T00-00-00")
    assert (out / "RESTORED").exists()
    assert not (out / "CURRENT").exists()
    # The current is now preserved as .prev-<new_ts>
    new_prevs = list(out.parent.glob(f"{out.name}.prev-*"))
    assert any(p.joinpath("CURRENT").exists() for p in new_prevs)


def test_rollback_unknown_snapshot_raises(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    # Snapshot dir doesn't exist → SystemExit (mapped from SourceNotFoundError rc=3)
    import sys

    from pick_face.cli import app

    sys.argv = ["pick-face", "rollback", "--out", str(out), "--to", "nope", "--yes"]
    try:
        app(standalone_mode=False)
    except SystemExit as e:
        assert e.code == 2  # SourceNotFoundError exit_code
    else:
        pytest.fail("expected SystemExit")


def test_rebuild_wipes_cache_and_prevs(tmp_pure: Path) -> None:
    out = tmp_pure / "out"
    out.mkdir()
    _seed_db(out)
    snap = out.parent / f"{out.name}.prev-old"
    snap.mkdir()

    _call("rebuild", out, yes=True)
    assert not (out / ".cache").exists()
    assert not snap.exists()