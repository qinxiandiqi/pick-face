"""Smoke test for pick-face link: scan → synthetic faces → cluster (skipped)
→ link. We bypass `index` (no InsightFace in CI) by inserting synthetic
face rows with random unit embeddings directly into the DB.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    work = Path("/tmp") / "pf-link-smoke"
    if sys.platform == "win32":
        import tempfile
        work = Path(tempfile.gettempdir()) / "pf-link-smoke"
    if work.exists():
        shutil.rmtree(work)
    src = work / "src"
    out = work / "out"
    src.mkdir(parents=True)
    out.mkdir()
    # Minimal config so `link` doesn't fail before doing its work.
    (out / "pick-face.toml").write_text(
        '[runtime]\n'
        'model_name = "buffalo_l"\n'
        'accept_noncommercial_model_license = true\n'
        'provider = "cpu"\n\n'
        '[link]\n'
        'prefer = "copy"\n',  # copy keeps the smoke test boring but predictable
        encoding="utf-8",
    )

    sys.path.insert(0, str(repo / "tests"))
    from unit._png import make_minimal_png

    # 3 "people", each with 4 photos
    for p in range(3):
        person = src / f"p{p}"
        person.mkdir(parents=True)
        for i in range(4):
            (person / f"img{i}.jpg").write_bytes(make_minimal_png())

    # Run scan
    r = subprocess.run(
        ["uv", "run", "pick-face", "scan", "--src", str(src), "--out", str(out)],
        cwd=repo, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("scan failed:", r.stderr, file=sys.stderr)
        return r.returncode
    print("scan:", r.stderr.strip().splitlines()[-1])

    # Bypass index: insert fake faces + clusters directly.
    db = out / ".cache" / "index.sqlite"
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    srcs = [
        dict(r) for r in con.execute("SELECT id, rel_path FROM source WHERE status='active'").fetchall()
    ]
    print(f"sources: {len(srcs)}")

    # Group into 3 clusters (round-robin).
    clusters = []
    for ci in range(3):
        cur = con.execute(
            "INSERT INTO cluster(id, label, size, created_at, updated_at) VALUES (?, ?, 0, 0, 0)",
            (ci + 1, f"person-{ci+1:04d}"),
        )
        clusters.append(cur.lastrowid)

    import os
    import struct
    for i, s in enumerate(srcs):
        cid = clusters[i % 3]
        # 512-d float32 = 2048 bytes of plausible-looking data
        embed_bytes = os.urandom(2048)
        con.execute(
            """INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                                det_score, embedding, model_version, norm, cluster_id)
               VALUES (?, 0, 0, 10, 10, 0.99, ?, 'test@0', 1.0, ?)""",
            (s["id"], embed_bytes, cid),
        )
        con.execute("UPDATE cluster SET size = size + 1 WHERE id = ?", (cid,))
    con.commit()
    con.close()

    r = subprocess.run(
        ["uv", "run", "pick-face", "link",
         "--config", str(out / "pick-face.toml"),
         "--out", str(out)],
        cwd=repo, capture_output=True, text=True,
    )
    print("link rc:", r.returncode)
    if r.stderr:
        for line in r.stderr.strip().splitlines()[-6:]:
            print(" ", line)

    # Verify
    persons = sorted(p.name for p in (out).iterdir() if p.is_dir() and p.name.startswith("person-"))
    print("person dirs:", persons)

    # Count links per person dir
    total = 0
    for pd in persons:
        pdir = out / pd
        # We just need to check there are files in there
        files = list(pdir.rglob("*"))
        if files:
            total += len([f for f in files if f.is_file() or f.is_symlink()])
        # Sanity: also count symlinks
    print(f"total file/symlink entries under out: {total}")
    if total != len(srcs):
        print(f"FAIL: expected {len(srcs)} entries, got {total}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
