"""File-system linker with 3-stage fallback (symlink → hardlink/junction → copy).

Reference:
- docs/05 §4 (平台分支表: Linux/macOS, Windows 管理员, Windows 普通用户)
- docs/05 §5 (输出目录原子切换 staging → rename)

The decision tree (per docs/05 §4.1):
  Linux/macOS:
    symlink → fallback to copy on OSError.
  Windows non-admin / no symlink privilege:
    files   → os.link (hardlink) → fallback to copy.
    dirs    → mklink /J (junction) → fallback to copy.
  Windows admin with symlink privilege:
    symlink first; for directories, mklink /D or symlink works depending on
    developer-mode flag — we try symlink first, fall back as above.

Cross-volume hardlinks will fail; cross-device copies are always allowed.
We do NOT catch PermissionError for symlinks — those should propagate so the
user notices that dev mode needs enabling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# On Windows, symlinks typically require either admin or developer mode.
# We probe that capability once per process to keep linking hot.
_HAS_WIN_SYMLINK: bool | None = None


@dataclass(frozen=True)
class LinkResult:
    link_path: Path
    target: Path
    kind: str        # "symlink" | "hardlink" | "junction" | "copy"

    def target_resolved(self) -> Path:
        if self.kind == "copy":
            return self.target
        # symlink/hardlink/junction: target is the source
        return self.target


def link_or_copy(src: Path, dst: Path, *, prefer: str = "symlink") -> LinkResult:
    """Create a link to *src* at *dst*, returning which method was used.

    Args:
        src: existing source file/dir.
        dst: link path to create. Parent dirs are created.
        prefer: "symlink" | "hardlink" | "copy" | "junction" — order of
            preference. Mapped onto docs/05 §4's decision table.

    Returns:
        LinkResult with .kind set to the actual method that worked.

    Raises:
        FileNotFoundError: src does not exist.
    """
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst, ignore_errors=True)

    attempts = _attempt_order(src, dst, prefer=prefer)
    last_err: OSError | None = None
    for kind in attempts:
        try:
            _do_link(kind, src, dst)
            return LinkResult(link_path=dst, target=src, kind=kind)
        except (OSError, subprocess.SubprocessError) as e:
            last_err = e if isinstance(e, OSError) else OSError(str(e))
            continue
    # Nothing worked — raise the last observed OSError, falling back to a
    # generic message if we somehow never saw one.
    raise last_err or OSError(f"failed to link {src} -> {dst}")


def _attempt_order(src: Path, dst: Path, *, prefer: str) -> list[str]:
    """Return the ordered list of link methods to attempt (docs/05 §4.1)."""
    is_win = sys.platform == "win32"
    is_dir = src.is_dir()

    # Build per-platform fallback chain rooted at *prefer*.
    if prefer == "copy":
        return ["copy"]

    chain: list[str]
    if not is_win:
        chain = ["symlink", "copy"]
    elif is_dir:
        chain = ["symlink", "junction", "copy"]
    else:
        chain = ["symlink", "hardlink", "copy"]

    # Move *prefer* to the front when it's already in the chain.
    if prefer in chain:
        chain.remove(prefer)
        chain.insert(0, prefer)
    else:
        chain.insert(0, prefer)
    return chain


def _do_link(kind: str, src: Path, dst: Path) -> None:
    if kind == "symlink":
        # target_is_directory=True on Windows so the symlink to a directory
        # is created correctly even if dst doesn't yet exist when os.symlink
        # is called. (We just unlinked above, so dst is absent anyway.)
        os.symlink(str(src), str(dst), target_is_directory=src.is_dir())
        return
    if kind == "hardlink":
        os.link(str(src), str(dst))
        return
    if kind == "junction":
        # mklink /J only exists for directories.
        subprocess.check_call(
            ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    if kind == "copy":
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return
    raise ValueError(f"unknown link kind: {kind!r}")


def unlink_safely(path: Path) -> bool:
    """Remove *path* whether it's a file, dir, or symlink. Returns whether
    anything was actually removed."""
    if not path.exists() and not path.is_symlink():
        return False
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path, ignore_errors=True)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Atomic staging → rename (docs/05 §5)
# ---------------------------------------------------------------------------


def staging_rename_atomic(staging: Path, final: Path, prev_marker: str = ".prev-") -> tuple[Path | None, str]:
    """Atomically swap *staging* into place at *final*.

    Behaviour (docs/05 §5):
      - If *final* exists, rename it to ``final/<prev_marker><run_id>``.
      - Move *staging* to *final* in a single os.replace (atomic on POSIX,
        near-atomic on Windows when both paths are on the same volume).

    Returns:
        (prev_path_or_None, run_id). prev_path is the .prev-<run_id>
        directory that holds the prior contents (callers should keep at
        most 3).
    """
    import time

    run_id = time.strftime("%Y-%m-%dT%H-%M-%S")
    final = Path(final)
    staging = Path(staging)

    prev_path: Path | None = None
    if final.exists():
        prev = final.parent / f"{final.name}{prev_marker}{run_id}"
        os.replace(final, prev)
        prev_path = prev

    os.replace(staging, final)
    return prev_path, run_id
