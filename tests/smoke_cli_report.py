"""Smoke test for `pick-face report`.

Reuses the smoke_cli_link pre-seeded DB: a SQLite with 3 clusters, fake
faces, and a config that already has `accept_noncommercial_model_license`
set so the compliance gate doesn't reject the run. We then invoke
`pick-face report --format md|json` and assert both files are written
with the docs/11 §3.4 top-line header.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def _seed(out: Path) -> None:
    """Replicate smoke_cli_link's seed: 3 sources, 3 clusters, 3 faces."""
    import os
    db = out / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    # We rely on `pick-face scan` having already created the schema. If the
    # file doesn't exist yet, call scan first.
    if not db.exists():
        raise RuntimeError("smoke_cli_report expects smoke_cli_link's DB to exist first")


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    work = Path(tempfile.gettempdir()) / "pf-report-smoke"
    if work.exists():
        shutil.rmtree(work)
    src = work / "src"
    out = work / "out"
    src.mkdir(parents=True)
    out.mkdir()

    (out / "pick-face.toml").write_text(
        '[runtime]\n'
        'model_name = "buffalo_l"\n'
        'accept_noncommercial_model_license = true\n'
        'provider = "cpu"\n',
        encoding="utf-8",
    )

    sys.path.insert(0, str(repo / "tests"))
    from unit._png import make_minimal_png

    for p in range(3):
        person = src / f"p{p}"
        person.mkdir(parents=True)
        (person / "img.jpg").write_bytes(make_minimal_png())

    # scan first
    r = subprocess.run(
        ["uv", "run", "pick-face", "scan", "--src", str(src), "--out", str(out)],
        cwd=repo, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("scan failed:", r.stderr, file=sys.stderr)
        return r.returncode

    db = out / ".cache" / "index.sqlite"
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    srcs = [dict(r) for r in con.execute("SELECT id FROM source WHERE status='active'").fetchall()]
    clusters = []
    for ci in range(3):
        cur = con.execute(
            "INSERT INTO cluster(label, size, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (f"person-{ci+1:04d}", 0, 0.0, 0.0),
        )
        clusters.append(cur.lastrowid)
    for i, s in enumerate(srcs):
        cid = clusters[i % 3]
        con.execute(
            """INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                                det_score, embedding, model_version, norm, cluster_id)
               VALUES (?, 0, 0, 10, 10, 0.99, ?, 'test@0', 1.0, ?)""",
            (s["id"], os.urandom(2048), cid),
        )
        con.execute("UPDATE cluster SET size = size + 1 WHERE id = ?", (cid,))
    con.commit()
    con.close()

    for fmt, expected in (("md", "report.md"), ("json", "report.json")):
        r = subprocess.run(
            ["uv", "run", "pick-face", "report",
             "--config", str(out / "pick-face.toml"),
             "--out", str(out),
             "--format", fmt],
            cwd=repo, capture_output=True, text=True,
        )
        print(f"report {fmt} rc: {r.returncode}")
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            return r.returncode
        path = out / expected
        if not path.exists():
            print(f"FAIL: missing {path}", file=sys.stderr)
            return 1

    # Validate JSON content has the audit header.
    parsed = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert parsed["model"]["name"] == "buffalo_l"
    assert "InsightFace" in parsed["model"]["license"]
    assert parsed["model"]["license_accepted"] is True
    assert parsed["stats"]["persons"] == 3
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())