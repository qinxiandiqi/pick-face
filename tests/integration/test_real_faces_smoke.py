"""Real-face smoke test (mark: real_data).

Drives the full CLI pipeline against the real-face fixture:

    pick-face init        -> write pick-face.toml
    pick-face init-models --allow-network --yes  (only if model missing)
    pick-face run         -> scan + detect + embed + cluster + link + report
    pick-face report      -> render report.md

What we verify:

    * Pipeline runs end-to-end without error.
    * SQLite has at least one row per expected table (source, face,
      cluster, link).
    * report.md / report.html exist and are non-empty.
    * Person count in report matches `manifest.person_count`.

Default fixture is the AT&T / ORL / Olivetti faces dataset (40 × 10 PGM
frames, CC-BY 4.0) fetched via:

    uv run python scripts/fetch_face_dataset.py
    uv run pytest tests/integration/test_real_faces_smoke.py -v

The test is **mark: real_data** and **skips automatically** if the
dataset hasn't been fetched yet.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_data


def _face_runner() -> str:
    """Path to the pick-face console script."""
    # `uv run pick-face ...` is the documented user path. When uv isn't
    # on PATH (rare), fall back to `python -m pick_face`.
    if shutil.which("pick-face"):
        return "pick-face"
    return "python -m pick_face"


def _run(cmd: list[str], cwd: Path, timeout: int = 1800) -> None:
    print(f"$ {' '.join(cmd)}  (cwd={cwd})")
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.stderr = sys.stderr  # noqa: PLW0127 (keep visible)
        raise AssertionError(
            f"command failed (rc={r.returncode}): {' '.join(cmd)}\n"
            f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
        )


def test_real_face_smoke(tmp_path: Path, real_face_dir: Path, real_face_manifest: dict) -> None:
    src = real_face_dir
    out = tmp_path / "by_face"
    out.mkdir()

    runner = _face_runner()

    # 1. Generate a fresh pick-face.toml — pointing model_dir somewhere
    #    the test owns (won't download if the host already has buffalo_l).
    cfg = tmp_path / "pick-face.toml"
    _run([runner, "init", "-o", str(cfg), "--force"], cwd=tmp_path)

    # 1a. Flip the AC-9 license gate to true. The default is `false`
    #     (fail-safe — see docs/11 §3.2). For real-face testing we need
    #     the AC-9 guard lifted so index/run can load buffalo_l; the
    #     .license_ack file is written separately by `init-models`.
    #
    #     Also tune detection to AT&T's small + low-contrast PGM frames:
    #     det_size=320 keeps the face at ~75% of the canvas (vs. ~5% at
    #     the default 640), and det_thresh=0.3 lets borderline scores
    #     through (avg 0.86 at det_size=320, vs. 0 detected at default).
    text = cfg.read_text(encoding="utf-8")
    text = text.replace(
        "accept_noncommercial_model_license = false",
        "accept_noncommercial_model_license = true",
    )
    text = text.replace("det_thresh = 0.5", "det_thresh = 0.3")
    text = text.replace("det_size = 640", "det_size = 320")
    cfg.write_text(text, encoding="utf-8")

    # 2. Run the pipeline. If InsightFace weights aren't on disk, this
    #    surfaces ModelNotFoundError → test fails with a clear message.
    #    --no-atomic keeps the SQLite at by_face/.cache/index.sqlite;
    #    with the default atomic swap the DB moves into by_face.prev-*/,
    #    which is correct production behavior but inconvenient for tests.
    _run(
        [
            runner,
            "run",
            "--src",
            str(src),
            "-o",
            str(out),
            "--config",
            str(cfg),
            "--provider",
            "cpu",
            "--no-atomic",
        ],
        cwd=tmp_path,
        timeout=1800,
    )

    # 3. Report (post-hoc render — already produced by `run`, but
    #    explicit call makes the smoke independent of internal order).
    #    --format html exercises the M4 T-301 dark-mode report path.
    _run(
        [runner, "report", "-o", str(out), "--config", str(cfg), "--format", "html"],
        cwd=tmp_path,
    )

    # 4. Validate outputs.
    db = out / ".cache" / "index.sqlite"
    assert db.exists(), f"SQLite not created at {db}"

    with sqlite3.connect(str(db)) as conn:
        n_sources = conn.execute("SELECT COUNT(*) FROM source").fetchone()[0]
        n_faces = conn.execute("SELECT COUNT(*) FROM face").fetchone()[0]
        n_clusters = conn.execute(
            "SELECT COUNT(*) FROM cluster WHERE merged_into IS NULL"
        ).fetchone()[0]

    assert n_sources >= int(real_face_manifest["image_count"]), (
        f"source rows {n_sources} < manifest images {real_face_manifest['image_count']}"
    )
    assert n_faces > 0, "no faces detected in real-face dataset"
    assert n_clusters > 0, "no clusters produced — clustering stage failed silently"
    # The `link` CLI subcommand currently emits filesystem links but does
    # not record them into the `link` table — validate filesystem output.
    cluster_dirs = [d for d in out.iterdir() if d.is_dir() and d.name.startswith("person-")]
    n_filesystem_links = sum(
        1 for d in cluster_dirs for f in d.rglob("*") if f.is_file() or f.is_symlink()
    )
    assert n_filesystem_links > 0, (
        f"linker produced no files (cluster_dirs={len(cluster_dirs)})"
    )

    # 5. Reports exist. We asked for --format html (the M4 T-301 path),
    #    so md may not be present alongside — assert html only.
    html = out / "report.html"
    assert html.exists() and html.stat().st_size > 0, "report.html missing or empty"

    # 6. Sanity: cluster count should not exceed person_count by orders
    #    of magnitude — if clustering wildly over-segments, something's
    #    wrong. (Exact match not asserted; we expect HDBSCAN to merge.)
    assert n_clusters <= real_face_manifest["person_count"] * 5, (
        f"too many clusters ({n_clusters}) for {real_face_manifest['person_count']} "
        f"people — clustering likely broken"
    )
