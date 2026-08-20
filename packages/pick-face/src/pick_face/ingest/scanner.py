"""Filesystem scanner: walk sources, filter by extension/glob, content-hash, diff.

Reference:
- docs/03 §5 (Scan 阶段: 增量 diff ADD/MOD/UNCHANGED/DEL)
- docs/09 §2.1 (格式白名单: jpg/png/webp/bmp/gif/tiff + heic/raw extras)
- docs/05 §3.1 (source 表字段)
- docs/10 §3.3 (xxh3_64 over first 64 KB)

Diff semantics (incremental, vs `source` table in index.sqlite):
    ADD       — path present on disk, missing in DB
    MOD       — path present in DB but mtime/size changed
    UNCHANGED — path present in DB and mtime+size identical (skip content hash)
    DEL       — path in DB but absent on disk (DB row's status → 'missing')

We compare (path, size, mtime) first because xxh3_64 of a 50 MB RAW is 50 ms;
(size, mtime) is ~0.1 ms. A collision between ADD/MOD and a miss in size-or-mtime
is vanishingly rare for photo files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

from pick_face.core.hashing import HASH_HEX_LEN, content_hash

# Core image extensions supported by Pillow alone (docs/09 §2.1).
# HEIC and RAW are behind extras; the scanner still lists them so glob'd
# files aren't silently dropped — the downstream decoder will fail with a
# clear "install pick-face[heic]" or similar hint.
# .pgm / .pbm / .ppm are Pillow-supported PNM formats — included so the
# real-face test fixture (AT&T/ORL/Olivetti ships 400 PGM frames) walks.
DEFAULT_IMAGE_EXTS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
        ".gif",
        ".tif",
        ".tiff",
        ".heic",
        ".heif",
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".dng",
        ".raf",
        ".orf",
        ".rw2",
        ".pgm",
        ".pbm",
        ".ppm",
    }
)


class DiffKind(str, Enum):
    """Incremental-diff classification of a scanned file vs the index."""

    ADD = "add"
    MOD = "mod"
    UNCHANGED = "unchanged"
    DEL = "del"


@dataclass(frozen=True)
class ScanRow:
    """One row produced by scan() per filesystem path."""

    abs_path: Path
    rel_path: Path  # relative to the --src root it came from
    root: Path  # the --src root that contained it
    size: int
    mtime: float
    kind: DiffKind
    hash: str | None = None  # xxh3_64 hex (16 chars); None for UNCHANGED+DEL

    def __post_init__(self) -> None:
        if self.hash is not None and len(self.hash) != HASH_HEX_LEN:
            raise ValueError(f"hash must be {HASH_HEX_LEN}-char xxh3_64 hex; got {self.hash!r}")


@dataclass
class ScanStats:
    """Aggregate counters for a single scan pass."""

    add: int = 0
    mod: int = 0
    unchanged: int = 0
    del_: int = 0  # renamed from `del` because `del` is reserved
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "add": self.add,
            "mod": self.mod,
            "unchanged": self.unchanged,
            "del": self.del_,
            "errors": self.errors,
        }


def iter_candidate_files(
    roots: list[Path],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    follow_symlinks: bool = False,
) -> tuple[Path, Path, Path]:
    """Yield (root, abs_path, rel_path) for every image under each root.

    Args:
        roots: --src directories (each is treated as a separate identity root).
        include: glob patterns; if set, only files matching at least one are kept.
        exclude: glob patterns applied relative to *root*; matching files are skipped.
        follow_symlinks: when True, descend into symlinked directories (default False).

    Yields:
        (root, abs_path, rel_path) tuples. abs_path may equal root for top-level files.
    """
    for root in roots:
        root = root.resolve()
        for dirpath, dirnames, filenames in os.walk(
            root, followlinks=follow_symlinks, topdown=True
        ):
            # Prune excluded dirs early — saves syscalls on big trees.
            kept_dirs: list[str] = []
            for d in dirnames:
                full = Path(dirpath) / d
                if _any_match(str(full.relative_to(root)), exclude):
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs

            for name in filenames:
                abs_p = Path(dirpath) / name
                try:
                    rel = abs_p.relative_to(root)
                except ValueError:
                    rel = Path(name)
                rel_str = str(rel)
                if exclude and _any_match(rel_str, exclude):
                    continue
                ext = abs_p.suffix.lower()
                if not _is_image(ext, include, str(abs_p)):
                    continue
                yield root, abs_p, rel


def scan(
    roots: list[Path],
    db_rows: dict[str, tuple[int, float, str]] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    follow_symlinks: bool = False,
    compute_hash: bool = True,
) -> tuple[list[ScanRow], ScanStats]:
    """Walk *roots* and classify each candidate vs the index.

    Args:
        roots: --src directories.
        db_rows: optional map of absolute-path → (size, mtime, hash) from the
            `source` table. Without it, every file is treated as ADD (slower
            but correct — this is the cold-start path used by `rebuild`).
        include/exclude: glob filters.
        follow_symlinks: passed through to iter_candidate_files.
        compute_hash: when False, skip content hashing even for ADD/MOD (used
            by tests + by `cluster` after it has already hashed).

    Returns:
        (rows, stats) where rows is the full diff and stats is a counter bag.
    """
    db_rows = db_rows or {}
    rows: list[ScanRow] = []
    stats = ScanStats()

    for root, abs_p, rel in iter_candidate_files(roots, include, exclude, follow_symlinks):
        try:
            st = abs_p.stat()
        except OSError:
            stats.errors += 1
            continue

        size, mtime = int(st.st_size), float(st.st_mtime)
        key = str(abs_p.resolve())
        prev = db_rows.get(key)

        if prev is None:
            kind = DiffKind.ADD
        elif prev[0] != size or prev[1] != mtime:
            kind = DiffKind.MOD
        else:
            kind = DiffKind.UNCHANGED

        h: str | None = None
        if kind == DiffKind.ADD:
            stats.add += 1
            h = content_hash(abs_p) if compute_hash else None
        elif kind == DiffKind.MOD:
            stats.mod += 1
            h = content_hash(abs_p) if compute_hash else None
        else:
            stats.unchanged += 1
            # UNCHANGED: we still know the hash (from DB) but skip re-hashing;
            # the index layer will reuse the persisted hash on re-insert.
            h = db_rows.get(key, (0, 0.0, ""))[2] or None

        rows.append(
            ScanRow(
                abs_path=abs_p, rel_path=rel, root=root, size=size, mtime=mtime, kind=kind, hash=h
            )
        )

    # DEL: rows in DB whose path is missing on disk.
    seen = {str(r.abs_path.resolve()) for r in rows}
    for db_path, (size, mtime, h) in db_rows.items():
        if db_path in seen:
            continue
        p = Path(db_path)
        if not p.exists():
            stats.del_ += 1
            rows.append(
                ScanRow(
                    abs_path=p,
                    rel_path=Path(p.name),
                    root=p.parent,
                    size=size,
                    mtime=mtime,
                    kind=DiffKind.DEL,
                    hash=h or None,
                )
            )

    return rows, stats


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_image(ext: str, include: list[str] | None, abs_path: str) -> bool:
    """Decide whether a candidate file is an image.

    `include` patterns are matched against the absolute path (so users can
    write `"photos/2024/*"` or `"**/*.jpg"` style globs without surprises).
    """
    if include:
        return any(fnmatch(abs_path, p) for p in include)
    return ext in DEFAULT_IMAGE_EXTS


def _any_match(value: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return False
    return any(fnmatch(value, p) for p in patterns)
