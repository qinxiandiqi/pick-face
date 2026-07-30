"""End-to-end smoke test for pick-face scan CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    import os
    work = Path(os.environ.get("TEMP", "/tmp")) / "pf-smoke"
    if work.exists():
        shutil.rmtree(work)
    src = work / "src"
    src.mkdir(parents=True)
    out = work / "out"
    out.mkdir()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
    from unit._png import make_minimal_png

    (src / "a.jpg").write_bytes(make_minimal_png())
    (src / "b.png").write_bytes(make_minimal_png())
    (src / "ignore.txt").write_text("ignore me")

    repo = Path(__file__).resolve().parent.parent
    cmd = [
        "uv", "run", "pick-face", "scan",
        "--src", str(src),
        "--out", str(out),
    ]
    print(">>", " ".join(cmd))
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    print("stdout:", r.stdout)
    print("stderr:", r.stderr)
    print("rc:", r.returncode)
    if r.returncode != 0:
        return r.returncode

    # Re-run should classify the two images as UNCHANGED.
    print("--- second run ---")
    r2 = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    print("stdout:", r2.stdout)
    print("stderr:", r2.stderr)
    print("rc:", r2.returncode)

    # Check the source table shape.
    import sqlite3
    db = out / ".cache" / "index.sqlite"
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT path, rel_path, size, status, hash FROM source ORDER BY path"
    ).fetchall()]
    print("--- source table ---")
    for row in rows:
        print(row)
    con.close()

    # Expectations: 2 active rows (a.jpg, b.png), 0 'missing', 0 'ignore.txt'.
    active = [r for r in rows if r["status"] == "active"]
    if len(active) != 2:
        print(f"FAIL: expected 2 active rows, got {len(active)}", file=sys.stderr)
        return 1
    if any(r["path"].endswith("ignore.txt") for r in active):
        print("FAIL: ignore.txt leaked into active rows", file=sys.stderr)
        return 1
    for r in active:
        if not r["hash"] or len(r["hash"]) != 16:
            print(f"FAIL: bad hash on {r['path']!r}: {r['hash']!r}", file=sys.stderr)
            return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
