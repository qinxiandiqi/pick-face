"""AC-9 guard: no *.onnx files inside the pick-face distribution.

Reference: docs/11 §1.3 (AC-9) — we never ship ONNX weights in the
repo, the built wheel, the sdist, or the docker image. InsightFace
weights are downloaded by the user via `pick-face init-models --allow-network`.

This test walks:
  1. The git working tree (excluding .venv/, .git/, build artifacts).
  2. The built wheel and sdist under dist/ if `uv build` has been run.
  3. The repo at large (via `git ls-files`) for tracked files.

If any *.onnx is found anywhere we FAIL so it cannot ship by accident.
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

# Paths we never descend into.
SKIP_DIRS = {
    ".venv",
    "venv",
    ".git",
    "node_modules",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",  # user's local cache (the runner / report output)
    "smoke_out",
}


def _iter_files(root: Path):
    """Yield candidate files under *root*, skipping the usual junk."""
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in {".onnx", ".onnxdata", ".onnx.tar"}:
            yield path


def _git_tracked_files() -> list[Path]:
    """Return all files tracked by git, as absolute paths."""
    out = subprocess.check_output(
        ["git", "ls-files"],
        cwd=str(REPO),
        text=True,
    )
    return [(REPO / line.strip().replace("/", os.sep)) for line in out.splitlines() if line.strip()]


def test_no_onnx_in_repo_filesystem() -> None:
    bad = list(_iter_files(REPO))
    assert not bad, (
        f"AC-9 violation: found {len(bad)} *.onnx file(s) under repo root "
        f"(must NOT be shipped — see docs/11 §1.3):\n  "
        + "\n  ".join(str(p.relative_to(REPO)) for p in bad[:10])
    )


def test_no_onnx_in_git_tracked_files() -> None:
    """Even if a stray .onnx sneaks into the working tree (untracked) we
    don't catch it in step 1, so we also assert that nothing tracked by
    git is .onnx. This is what would actually ship in source tarballs."""
    tracked = _git_tracked_files()
    bad = [p for p in tracked if p.suffix.lower() in {".onnx", ".onnxdata"}]
    assert not bad, f"AC-9 violation: {len(bad)} *.onnx file(s) tracked by git:\n  " + "\n  ".join(
        str(p.relative_to(REPO)) for p in bad[:10]
    )


def test_no_onnx_in_built_wheel_or_sdist() -> None:
    """If dist/ has been built, both .whl and the .tar.gz must be free
    of *.onnx. Skip silently if dist/ doesn't exist (build-on-demand CI)."""
    dist = REPO / "packages" / "pick-face" / "dist"
    if not dist.exists():
        return  # not built yet
    archives = list(dist.glob("*.whl")) + list(dist.glob("*.tar.gz"))
    if not archives:
        return  # not built yet
    bad: list[tuple[Path, str]] = []
    for arc in archives:
        if arc.suffix == ".whl":
            with zipfile.ZipFile(arc) as z:
                for name in z.namelist():
                    if name.lower().endswith((".onnx", ".onnxdata")):
                        bad.append((arc, name))
        else:  # sdist tarball
            import tarfile

            with tarfile.open(arc, "r:gz") as t:
                for member in t.getmembers():
                    if member.name.lower().endswith((".onnx", ".onnxdata")):
                        bad.append((arc, member.name))
    assert not bad, (
        f"AC-9 violation: {len(bad)} *.onnx file(s) inside built archives:\n  "
        + "\n  ".join(f"{a.name}::{n}" for a, n in bad[:10])
    )


def test_no_dockerfile_bakes_onnx() -> None:
    """If a Dockerfile is present, it must not COPY *.onnx from anywhere."""
    dockerfiles = list(REPO.rglob("Dockerfile*"))
    for df in dockerfiles:
        if any(part in SKIP_DIRS for part in df.parts):
            continue
        text = df.read_text(encoding="utf-8")
        # Heuristic: any COPY/ADD directive whose source contains .onnx.
        for line in text.splitlines():
            upper = line.strip().upper()
            if upper.startswith(("COPY ", "ADD ")):
                # Naive check — source token mentions .onnx
                if ".onnx" in line.lower():
                    raise AssertionError(
                        f"AC-9 violation: {df.relative_to(REPO)} copies .onnx: {line!r}"
                    )
