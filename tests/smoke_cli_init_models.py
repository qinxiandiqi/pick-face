"""Smoke test for `pick-face init-models`.

Verifies the License Notice is printed and `.license_ack` is emitted
when `--allow-network --yes` is used (docs/11 §3.3).

We do NOT actually contact InsightFace servers — pick-face only emits
the License Notice + audit file in M1; the actual download is left to
the bundled `insightface.model_zoo`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    work = Path(tempfile.gettempdir()) / "pf-init-smoke"
    if work.exists():
        shutil.rmtree(work)
    out = work / "out"
    models = work / "models"
    out.mkdir(parents=True)
    models.mkdir(parents=True)

    (out / "pick-face.toml").write_text(
        f'[runtime]\n'
        f'model_name = "buffalo_l"\n'
        f'accept_noncommercial_model_license = true\n'
        f'provider = "cpu"\n'
        f'model_dir = "{models.as_posix()}"\n',
        encoding="utf-8",
    )

    r = subprocess.run(
        ["uv", "run", "pick-face", "init-models",
         "--config", str(out / "pick-face.toml"),
         "--allow-network", "--yes"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print("init-models rc:", r.returncode)
    # Notice can include unicode; we read as utf-8 with errors='replace' above.
    notice_in_stderr = "InsightFace buffalo_l" in r.stderr

    # License Notice was printed (Rich Console is configured to stderr).
    if not notice_in_stderr:
        print("FAIL: License Notice not printed", file=sys.stderr)
        return 1

    # .license_ack was emitted
    ack_path = models / "buffalo_l" / ".license_ack"
    if not ack_path.exists():
        print(f"FAIL: missing {ack_path}", file=sys.stderr)
        return 1
    payload = json.loads(ack_path.read_text(encoding="utf-8"))
    assert payload["model"] == "buffalo_l"
    assert payload["license"] == "InsightFace non-commercial-research"
    assert "acked_by" in payload

    # Now run without --allow-network — must fail fast.
    r2 = subprocess.run(
        ["uv", "run", "pick-face", "init-models",
         "--config", str(out / "pick-face.toml")],
        cwd=repo, capture_output=True, text=True,
    )
    print("init-models (no --allow-network) rc:", r2.returncode)
    if r2.returncode == 0:
        print("FAIL: should refuse without --allow-network", file=sys.stderr)
        return 1
    if "Refusing to download models" not in r2.stderr and "Refusing to download models" not in r2.stdout:
        print("FAIL: refusal message missing", file=sys.stderr)
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())