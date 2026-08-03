"""Tests for pick_face.scanner.

Covers:
- iter_candidate_files: extension filtering, glob include/exclude, nested walks
- scan() diff classification: ADD / MOD / UNCHANGED / DEL
- content hash: only computed for ADD/MOD
- stats counters consistent with rows
"""

from __future__ import annotations

from pathlib import Path

from pick_face.hashing import content_hash
from pick_face.scanner import (
    DEFAULT_IMAGE_EXTS,
    DiffKind,
    ScanStats,
    iter_candidate_files,
    scan,
)
from tests.unit._png import make_minimal_png

# ---------------------------------------------------------------------------
# iter_candidate_files
# ---------------------------------------------------------------------------


def test_iter_filters_to_default_image_extensions(tmp_pure: Path) -> None:
    (tmp_pure / "a.jpg").write_bytes(make_minimal_png())
    (tmp_pure / "b.png").write_bytes(make_minimal_png())
    (tmp_pure / "c.txt").write_text("not an image")
    (tmp_pure / "d").write_text("also not an image")

    files = sorted(abs_p.name for _, abs_p, _ in iter_candidate_files([tmp_pure]))
    assert files == ["a.jpg", "b.png"]


def test_iter_include_glob(tmp_pure: Path) -> None:
    (tmp_pure / "a.jpg").write_bytes(make_minimal_png())
    (tmp_pure / "a.png").write_bytes(make_minimal_png())
    files = sorted(
        abs_p.name for _, abs_p, _ in iter_candidate_files([tmp_pure], include=["*.jpg"])
    )
    assert files == ["a.jpg"]


def test_iter_exclude_glob(tmp_pure: Path) -> None:
    sub = tmp_pure / "trash"
    sub.mkdir()
    (sub / "x.jpg").write_bytes(make_minimal_png())
    (tmp_pure / "y.jpg").write_bytes(make_minimal_png())

    files = sorted(
        abs_p.name for _, abs_p, _ in iter_candidate_files([tmp_pure], exclude=["trash/*"])
    )
    assert files == ["y.jpg"]


def test_iter_recurses_into_subdirs(tmp_pure: Path) -> None:
    deep = tmp_pure / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "x.png").write_bytes(make_minimal_png())
    [(root, abs_p, rel)] = list(iter_candidate_files([tmp_pure]))
    assert abs_p == deep / "x.png"
    assert rel == Path("a/b/c/x.png")


def test_iter_handles_multiple_roots(tmp_pure: Path) -> None:
    r1 = tmp_pure / "r1"
    r2 = tmp_pure / "r2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "a.png").write_bytes(make_minimal_png())
    (r2 / "b.png").write_bytes(make_minimal_png())

    found = sorted((abs_p.name, str(rel)) for _, abs_p, rel in iter_candidate_files([r1, r2]))
    assert found == [("a.png", "a.png"), ("b.png", "b.png")]


def test_default_extensions_include_heic_and_raw() -> None:
    """Per docs/09 §2.1, heic + raw extensions are listed even though
    their *decode* needs extras — glob filtering must not silently drop them."""
    assert ".heic" in DEFAULT_IMAGE_EXTS
    assert ".cr2" in DEFAULT_IMAGE_EXTS
    assert ".nef" in DEFAULT_IMAGE_EXTS
    assert ".dng" in DEFAULT_IMAGE_EXTS


# ---------------------------------------------------------------------------
# scan() — diff classification
# ---------------------------------------------------------------------------


def _touch(path: Path, content: bytes = b"hi") -> tuple[int, float]:
    path.write_bytes(content)
    st = path.stat()
    return int(st.st_size), float(st.st_mtime)


def test_scan_classifies_add_when_no_db(tmp_pure: Path) -> None:
    (tmp_pure / "a.jpg").write_bytes(make_minimal_png())
    (tmp_pure / "b.jpg").write_bytes(make_minimal_png())
    rows, stats = scan([tmp_pure])
    kinds = sorted(r.kind for r in rows)
    assert kinds == [DiffKind.ADD, DiffKind.ADD]
    assert stats.add == 2
    assert stats.unchanged == 0
    assert stats.mod == 0
    assert stats.del_ == 0
    for r in rows:
        assert r.hash is not None
        assert len(r.hash) == 16


def test_scan_marks_unchanged_when_size_and_mtime_match(tmp_pure: Path) -> None:
    p = tmp_pure / "a.jpg"
    size, mtime = _touch(p, make_minimal_png())
    persisted_hash = content_hash(p)
    # Db says this exact size+mtime exists. UNCHANGED rows must reuse the
    # persisted hash from the DB (so downstream consumers can short-circuit
    # re-detection). They must NOT recompute.
    db = {str(p.resolve()): (size, mtime, persisted_hash)}
    rows, stats = scan([tmp_pure], db_rows=db)
    assert len(rows) == 1
    assert rows[0].kind == DiffKind.UNCHANGED
    assert rows[0].hash == persisted_hash
    assert stats.unchanged == 1
    assert stats.add == 0


def test_scan_marks_mod_when_mtime_changes(tmp_pure: Path) -> None:
    p = tmp_pure / "a.jpg"
    p.write_bytes(make_minimal_png())
    real_hash = content_hash(p)
    # Pretend the DB has a stale size+mtime pair — must trigger MOD + rehash.
    db = {str(p.resolve()): (1, 0.0, real_hash)}
    rows, stats = scan([tmp_pure], db_rows=db)
    assert len(rows) == 1
    assert rows[0].kind == DiffKind.MOD
    assert rows[0].hash == real_hash
    assert stats.mod == 1


def test_scan_marks_del_when_db_path_missing(tmp_pure: Path) -> None:
    ghost = tmp_pure / "ghost.jpg"  # never written to disk
    persisted_hash = "0123456789abcdef"
    db = {str(ghost.resolve()): (1234, 1000.0, persisted_hash)}
    rows, stats = scan([tmp_pure], db_rows=db)
    assert len(rows) == 1
    assert rows[0].kind == DiffKind.DEL
    assert rows[0].hash == persisted_hash
    assert stats.del_ == 1


def test_scan_honours_compute_hash_false(tmp_pure: Path) -> None:
    (tmp_pure / "a.jpg").write_bytes(make_minimal_png())
    rows, _ = scan([tmp_pure], compute_hash=False)
    assert rows[0].hash is None


def test_scan_mixed_diff_in_one_pass(tmp_pure: Path) -> None:
    add_path = tmp_pure / "new.jpg"
    add_size, add_mtime = _touch(add_path, make_minimal_png())
    add_hash = content_hash(add_path)

    mod_path = tmp_pure / "mod.jpg"
    _touch(mod_path, make_minimal_png())
    mod_hash = content_hash(mod_path)

    unchanged_path = tmp_pure / "unchanged.jpg"
    size_u, mtime_u = _touch(unchanged_path, make_minimal_png())
    unchanged_hash = content_hash(unchanged_path)

    db = {
        str(mod_path.resolve()): (1, 0.0, mod_hash),  # size mismatch -> MOD
        str(unchanged_path.resolve()): (size_u, mtime_u, unchanged_hash),
        str((tmp_pure / "gone.jpg").resolve()): (5, 100.0, "22" * 8),  # ghost -> DEL
    }
    rows, stats = scan([tmp_pure], db_rows=db)

    by_kind: dict[DiffKind, list[str]] = {k: [] for k in DiffKind}
    for r in rows:
        by_kind[r.kind].append(r.abs_path.name)

    assert sorted(by_kind[DiffKind.ADD]) == ["new.jpg"]
    assert sorted(by_kind[DiffKind.MOD]) == ["mod.jpg"]
    assert sorted(by_kind[DiffKind.UNCHANGED]) == ["unchanged.jpg"]
    assert sorted(by_kind[DiffKind.DEL]) == ["gone.jpg"]

    assert stats.add == 1
    assert stats.mod == 1
    assert stats.unchanged == 1
    assert stats.del_ == 1

    # ADD rows should produce a real hash recomputed by content_hash.
    add_row = next(r for r in rows if r.kind == DiffKind.ADD)
    assert add_row.hash == add_hash


def test_scan_handles_unreadable_file(tmp_pure: Path) -> None:
    """A path that vanishes between os.walk() and stat() must bump stats.errors,
    not crash the entire scan."""
    p = tmp_pure / "a.jpg"
    p.write_bytes(make_minimal_png())
    import unittest.mock as mock

    with mock.patch.object(Path, "stat", side_effect=OSError("boom")):
        rows, stats = scan([tmp_pure])
    assert rows == []
    assert stats.errors == 1

    # Recovery: outside the patch, scan again should succeed normally.
    rows2, stats2 = scan([tmp_pure])
    assert len(rows2) == 1
    assert stats2.add == 1


def test_scan_stats_as_dict_keys() -> None:
    """Stable surface for the report stage."""
    s = ScanStats(add=1, mod=2, unchanged=3, del_=4, errors=5)
    d = s.as_dict()
    assert d == {"add": 1, "mod": 2, "unchanged": 3, "del": 4, "errors": 5}
