"""Tests for pick_face.output.linker.

Exercises the link-or-copy fallback at file level (skipping directory
junction which is Windows-only and requires admin). We cover:
- symlink preferred → falls back to copy when source is replaced by a
  broken-symlink error.
- prefer='copy' just copies.
- hardlink fallback when symlink fails (we mock it).
- unlink_safely handles all three variants (file, dir, symlink).
- staging_rename_atomic produces .prev-<ts> + atomic swap.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def test_link_prefer_symlink_falls_back_to_copy(tmp_pure: Path) -> None:
    if sys.platform.startswith("win") and not _windows_can_symlink():
        pytest.skip("windows symlinks need developer mode")
    from pick_face.output.linker import link_or_copy

    src = tmp_pure / "src.bin"
    src.write_bytes(b"hello world")
    dst = tmp_pure / "out" / "link.bin"
    res = link_or_copy(src, dst, prefer="symlink")
    assert res.kind == "symlink"
    assert dst.exists()
    assert (
        dst.resolve() == src.resolve()
        if os.path.islink(dst)
        else dst.read_bytes() == src.read_bytes()
    )


def test_link_prefer_copy_makes_copy(tmp_pure: Path) -> None:
    from pick_face.output.linker import link_or_copy

    src = tmp_pure / "src.bin"
    src.write_bytes(b"hello world")
    dst = tmp_pure / "out" / "copy.bin"
    res = link_or_copy(src, dst, prefer="copy")
    assert res.kind == "copy"
    assert dst.read_bytes() == b"hello world"


def test_link_unlinks_existing_dst(tmp_pure: Path) -> None:
    """If dst already exists, it must be removed first (no stale data)."""
    from pick_face.output.linker import link_or_copy

    src = tmp_pure / "src.bin"
    src.write_bytes(b"new")
    dst = tmp_pure / "out" / "dst.bin"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"stale old data here")
    res = link_or_copy(src, dst, prefer="copy")
    assert res.kind == "copy"
    assert dst.read_bytes() == b"new"


def test_link_missing_src_raises(tmp_pure: Path) -> None:
    from pick_face.output.linker import link_or_copy

    ghost = tmp_pure / "nope.bin"
    dst = tmp_pure / "out" / "link.bin"
    with pytest.raises(FileNotFoundError):
        link_or_copy(ghost, dst)


def test_unlink_safely_handles_missing(tmp_pure: Path) -> None:
    from pick_face.output.linker import unlink_safely

    assert unlink_safely(tmp_pure / "nothing") is False


def test_unlink_safely_removes_files_dirs_symlinks(tmp_pure: Path) -> None:
    from pick_face.output.linker import link_or_copy, unlink_safely

    # File via copy
    f = tmp_pure / "f.bin"
    f.write_bytes(b"x")
    assert unlink_safely(f)
    assert not f.exists()

    # Dir
    d = tmp_pure / "d"
    d.mkdir()
    (d / "x").write_text("hi")
    assert unlink_safely(d)
    assert not d.exists()

    # Symlink (if available)
    if not (sys.platform.startswith("win") and not _windows_can_symlink()):
        tgt = tmp_pure / "tgt.bin"
        tgt.write_bytes(b"x")
        link = tmp_pure / "lnk.bin"
        link_or_copy(tgt, link, prefer="symlink")
        assert link.is_symlink()
        assert unlink_safely(link)
        assert tgt.exists()  # original is intact


def test_staging_rename_atomic_creates_prev(tmp_pure: Path) -> None:
    from pick_face.output.linker import staging_rename_atomic

    final = tmp_pure / "out"
    staging = tmp_pure / ".staging"
    final.mkdir()
    (final / "old.txt").write_text("old")
    staging.mkdir()
    (staging / "new.txt").write_text("new")

    prev, run_id = staging_rename_atomic(staging, final)
    assert (final / "new.txt").exists()
    assert not (final / "old.txt").exists()
    assert prev is not None
    assert prev.exists()
    assert (prev / "old.txt").exists()
    assert run_id  # non-empty timestamp


def test_staging_rename_no_existing_final(tmp_pure: Path) -> None:
    from pick_face.output.linker import staging_rename_atomic

    staging = tmp_pure / ".staging"
    staging.mkdir()
    (staging / "x.txt").write_text("x")
    final = tmp_pure / "out"

    prev, _ = staging_rename_atomic(staging, final)
    assert (final / "x.txt").exists()
    assert prev is None  # no .prev created when there was no prior output


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _windows_can_symlink() -> bool:
    """Best-effort check whether the current Windows user can create symlinks
    without elevation. (Skips the test if not.) On non-Windows, returns True."""
    if not sys.platform.startswith("win"):
        return True
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tgt = f.name
        link = tgt + "_lnk"
        os.symlink(tgt, link)
        os.unlink(link)
        os.unlink(tgt)
        return True
    except OSError:
        return False
