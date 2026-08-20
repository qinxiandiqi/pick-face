#!/usr/bin/env python3
"""Pin SHA256 hashes for the shipped ModelPack weights.

Route B reference (docs/14 §4 / T-503). After downloading the yunet-mfn
weights once into ``<model_dir>/yunet-mfn/``, run:

    uv run python scripts/pin_sha256.py

It will compute the SHA256 of every file in the directory and emit a
small ``pinned_sha256.py`` snippet that you paste into
``src/pick_face/platform/packs/yunet_mfn.py`` to replace the
``<TBD-pin on first CI build>`` placeholders.

Why this is manual: we don't want to ship the bytes themselves in the
repo (AC-9 says no *.onnx in repo/wheel/sdist), but we *do* want the
hash pinned in source so the integrity check is auditable in code
review. CI is expected to call this script once per release.

Usage:
    PICK_FACE_MODEL_DIR=~/.cache/pick-face/models \\
        uv run python scripts/pin_sha256.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

CHUNKSIZE = 65536


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNKSIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    model_dir = Path(
        os.environ.get("PICK_FACE_MODEL_DIR", "~/.cache/pick-face/models")
    ).expanduser()
    pack_dir = model_dir / "yunet-mfn"
    if not pack_dir.exists():
        print(
            f"ERROR: {pack_dir} not found. Run\n"
            f"  pick-face init-models --pack yunet-mfn --allow-network\n"
            f"first.",
            file=sys.stderr,
        )
        return 1
    print(f"# Pin these hashes into src/pick_face/platform/packs/yunet_mfn.py\n")
    for f in sorted(pack_dir.iterdir()):
        if f.suffix != ".onnx":
            continue
        h = sha256_of(f)
        var = "YUNET_SHA256" if "yunet" in f.name.lower() else "MFN_SHA256"
        print(f'{var} = "{h}"   # {f.name} ({f.stat().st_size} bytes)')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())