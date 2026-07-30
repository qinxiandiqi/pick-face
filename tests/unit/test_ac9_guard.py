"""Sanity check: the AC-9 guard actually fires when a stray *.onnx appears.

We create a tiny .onnx file in a temp location that mimics the repo
walk, then run the same scan logic against it. This test is *not* run
on the real repo (it would falsely fail); it's a unit test of the
guard's detection logic in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _has_onnx(root: Path) -> list[Path]:
    """Replicates AC-9 guard's filesystem walk."""
    SKIP = {".venv", ".git", "__pycache__", ".cache"}
    out = []
    for p in root.rglob("*"):
        if any(part in SKIP for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() == ".onnx":
            out.append(p)
    return out


def test_guard_detects_onnx(tmp_pure: Path) -> None:
    fake = tmp_pure / "models" / "detector.onnx"
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"\x00\x00fake-onnx-bytes")
    found = _has_onnx(tmp_pure)
    assert fake in found


def test_guard_ignores_venv_and_git(tmp_pure: Path) -> None:
    """Junk dirs (which may legitimately contain ONNX wheels' test data)
    are skipped."""
    (tmp_pure / ".venv" / "lib" / "site-packages").mkdir(parents=True)
    (tmp_pure / ".venv" / "lib" / "site-packages" / "x.onnx").write_bytes(b"x")
    (tmp_pure / ".git" / "objects").mkdir(parents=True)
    (tmp_pure / ".git" / "objects" / "y.onnx").write_bytes(b"y")
    assert _has_onnx(tmp_pure) == []