"""End-to-end smoke test for the AC-9 preflight gate on `pick-face index`.

We don't have an InsightFace pack installed in CI; that's fine — the gate
*must* fire before the runner tries to look one up. This script:

  1. Creates a fixture image set.
  2. Runs `pick-face scan` (writes source rows).
  3. Runs `pick-face index` with the default config (buffalo_l, license=false).
     Expects exit code = 2 + CommercialLicenseError panel on stderr.
  4. Re-runs with `accept_noncommercial_model_license = true` after creating
     a fake pack directory. Expects to fall through to ModelNotFoundError
     (because there's no actual .onnx file) — exit code = 3.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    work = Path(os.environ.get("TEMP", "/tmp")) / "pf-index-smoke"
    if work.exists():
        shutil.rmtree(work)
    src = work / "src"
    out = work / "out"
    src.mkdir(parents=True)
    out.mkdir()

    sys.path.insert(0, str(repo / "tests"))
    from unit._png import make_minimal_png

    (src / "a.jpg").write_bytes(make_minimal_png())
    (src / "b.png").write_bytes(make_minimal_png())

    cfg = out / "pick-face.toml"
    cfg.write_text(
        '[runtime]\n'
        'model_name = "buffalo_l"\n'
        'model_dir = "~/.insightface/models"\n'
        'accept_noncommercial_model_license = false\n'
        'provider = "cpu"\n',
        encoding="utf-8",
    )

    def run(cmd):
        print(">>", " ".join(cmd))
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        print(f"  rc={r.returncode}")
        if r.stdout:
            print("stdout:", r.stdout.strip())
        if r.stderr:
            stderr_tail = r.stderr.strip().splitlines()[-6:]
            print("stderr (last 6 lines):")
            for line in stderr_tail:
                print("  ", line)
        return r

    # 1) Pick-face scan populates the source table.
    r = run(["uv", "run", "pick-face", "scan", "--src", str(src), "--out", str(out)])
    if r.returncode != 0:
        print("FAIL: scan failed", file=sys.stderr)
        return r.returncode

    # 2) index with default (commercial-unsafe) config → exit code 2.
    r = run(["uv", "run", "pick-face", "index",
             "--config", str(cfg), "--out", str(out), "--provider", "cpu"])
    if r.returncode != 2:
        print(f"FAIL: expected rc=2 (compliance), got rc={r.returncode}", file=sys.stderr)
        return 1
    if "Commercial license" not in r.stderr and "AC-9" not in r.stderr:
        print("FAIL: expected AC-9 panel in stderr; not found", file=sys.stderr)
        return 1
    print("PASS: AC-9 gate fires before model lookup")

    # 3) Now acknowledge the license in a temp config. Model pack won't exist
    #    on disk → expect ModelNotFoundError → rc=3.
    cfg_acked = out / "acked.toml"
    cfg_acked.write_text(cfg.read_text(encoding="utf-8").replace(
        "accept_noncommercial_model_license = false",
        "accept_noncommercial_model_license = true",
    ), encoding="utf-8")
    r = run(["uv", "run", "pick-face", "index",
             "--config", str(cfg_acked), "--out", str(out), "--provider", "cpu"])
    # ModelLoadError (missing onnx) or ModelNotFoundError both exit code 3
    if r.returncode != 3:
        print(f"FAIL: expected rc=3 (model missing), got rc={r.returncode}", file=sys.stderr)
        return 1
    print("PASS: license acknowledged → falls through to rc=3 model lookup")
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
