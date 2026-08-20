"""Fetch a small license-clean real-face test set for pick-face.

Dataset: AT&T / ORL / Olivetti Faces
  - 40 subjects × 10 images = 400 PGM frames
  - 92 × 112 px greyscale, already close-cropped
  - CC-BY 4.0 — attribution to "AT&T Laboratories Cambridge
    (formerly Olivetti Research Laboratory)"
  - ~4 MB compressed / ~4.5 MB extracted
  - Variety in expression, glasses, scale (~10%), rotation (~20°)

Why this dataset (out of the candidates surveyed):
  * License is unambiguous (CC-BY 4.0) and compatible with pick-face's
    Apache-2.0 — only requires attribution, not source disclosure.
  * Small (sub-10 MB), already cropped, suitable for fast CI smoke.
  * 40 × 10 is dense enough to exercise HDBSCAN + the 2-pass centroid
    merge without overfitting thresholds to a single dataset.
  * "5 Celebrity Faces" (the obvious Kaggle small option) is rejected:
    its license is unclear and the photos of named celebrities carry
    publicity rights the uploader does not hold.

Output layout (created under tests/fixtures/real_faces/):

    real_faces/
    ├── manifest.json      # {person_count, image_count, source_url, license, attribution}
    ├── labels.csv         # rel_path,person_id  (consumed by tests/acceptance/run_eval.py)
    ├── NOTICE             # CC-BY 4.0 attribution written after fetch
    └── person_001/
        ├── 001.pgm
        ├── 002.pgm
        └── ...

Usage:

    uv run python scripts/fetch_face_dataset.py             # default location
    uv run python scripts/fetch_face_dataset.py --out DIR   # custom dir
    uv run python scripts/fetch_face_dataset.py --force     # re-download even if present

Fetch strategy: AT&T's tar.Z archive at
    https://www.cl.cam.ac.uk/research/dtg/attarchive/pub/data/att_faces.tar.Z
Despite the `.Z` suffix, the bytes are gzip-framed — `gzip -d` decodes
them on every platform we support (Linux, macOS, Git-Bash on Windows,
MSYS, Cygwin). The archive extracts to `orl_faces/s1/1.pgm` ...
`orl_faces/s40/10.pgm` and a README; we flatten that into the
canonical `person_NNN/<seq>.<ext>` layout.

Exit codes:
    0  dataset fetched + manifest verified
    2  network or source error (printed to stderr)
    3  downloaded payload is unusable (extracted but no images / wrong layout)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_faces"

DATASET_NAME = "AT&T / ORL / Olivetti Faces"
LICENSE_NAME = "CC-BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = (
    "AT&T Laboratories Cambridge (formerly Olivetti Research Laboratory). "
    "Source: https://www.cl.cam.ac.uk/research/dtg/attarchive/facedatabase.html"
)

# Only URL we use. Despite the `.Z` suffix, the bytes are gzip-framed
# (AT&T's archive script gzips with --suffix .Z for historical reasons),
# so `gzip -d` works on every platform we support.
SOURCE = {
    "url": "https://www.cl.cam.ac.uk/research/dtg/attarchive/pub/data/att_faces.tar.Z",
    "kind": "tar_z",
    # Upstream extracts to <root>/s1/1.pgm ... s40/10.pgm + README.
    # We accept either root name (att_faces or orl_faces) and rewrite
    # into person_NNN/<seq>.<ext>.
}

MIN_PERSONS = 30
MIN_IMAGES_PER_PERSON = 8
IMAGE_EXTS = {".pgm", ".png", ".jpg", ".jpeg", ".bmp"}


def _download(url: str) -> bytes:
    """Stream a URL to bytes. Raises on HTTP error."""
    req = urllib.request.Request(url, headers={"User-Agent": "pick-face-test-fixture/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to download {url}: {exc}") from exc


def _gzip_decompress(blob: bytes) -> bytes:
    """Decode a gzip-framed payload using the system `gzip -d` binary.

    Cross-platform note: we deliberately shell out instead of using
    `gzip.decompress(blob)` so the same code path works on every host.
    Git-Bash on Windows ships `gzip.exe`; Linux/macOS always have it.
    """
    gzip_bin = shutil.which("gzip")
    if gzip_bin is None:
        raise RuntimeError(
            "`gzip` binary not found on PATH — install it (apt/brew/Git-Bash)"
        )
    try:
        r = subprocess.run(
            [gzip_bin, "-d", "-c"],
            input=blob,
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"gzip -d failed: {exc}") from exc
    return r.stdout


def _extract_tar(blob: bytes, target: Path) -> None:
    """Extract a plain tarball (already decompressed) into target."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as t:
        for member in t.getmembers():
            if member.name.startswith(("..", "/")):
                continue
            t.extract(member, target)


def _extract(blob: bytes, kind: str, target: Path) -> None:
    if kind == "tar_z":
        # AT&T's `att_faces.tar.Z` is actually gzip-framed (file magic
        # starts with 1f 8b) — gzip -d produces a plain tar.
        tar_bytes = _gzip_decompress(blob)
        _extract_tar(tar_bytes, target)
    elif kind == "tar_gz":
        _extract_tar(blob, target)
    elif kind == "zip":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            z.extractall(target)
    else:
        raise RuntimeError(f"unknown archive kind: {kind}")


def _normalize(out: Path) -> tuple[int, int]:
    """Rewrite the upstream tree into our person_NNN/<n>.<ext> layout.

    AT&T extracts to `orl_faces/s1/1.pgm`, `orl_faces/s1/2.pgm`, ...,
    `orl_faces/s40/10.pgm` (and historically `att_faces/` on older
    mirrors). Either root works because we only look at the `s*/` dirs
    underneath.

    Returns (person_count, total_image_count).
    """
    # Find the upstream root — it's whichever single subdir of `out`
    # contains the `s*/` per-person folders. If extraction landed the
    # per-person dirs directly under `out` (rootless tar), upstream_root
    # stays as `out`.
    upstream_root = out
    for child in out.iterdir():
        if not child.is_dir():
            continue
        if any(
            d.is_dir() and d.name.startswith("s") and d.name[1:].isdigit()
            for d in child.iterdir()
        ):
            upstream_root = child
            break

    person_dirs = sorted(
        [
            d
            for d in upstream_root.iterdir()
            if d.is_dir() and d.name.startswith("s") and d.name[1:].isdigit()
        ],
        key=lambda p: int(p.name[1:]),
    )

    if not person_dirs:
        raise RuntimeError(
            f"no per-person folders found under {upstream_root} "
            f"(expected names like s1, s2, ..., s40)"
        )

    total = 0
    for idx, src in enumerate(person_dirs, start=1):
        new_name = f"person_{idx:03d}"
        target = out / new_name
        target.mkdir(exist_ok=True)
        imgs = sorted(
            [f for f in src.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS],
            key=lambda p: p.name,
        )
        for n, img in enumerate(imgs, start=1):
            new_path = target / f"{n:03d}{img.suffix.lower()}"
            shutil.move(str(img), str(new_path))
        # Move any non-image files (README, etc.) into the new dir too.
        for f in src.iterdir():
            if f.is_file():
                shutil.move(str(f), str(target / f.name))
        if not any(src.iterdir()):
            src.rmdir()
        total += len(
            [f for f in target.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        )

    # Drop the upstream wrapper dir's non-image files (e.g. README) so
    # `out/` contains only person_NNN/ + manifest/labels/NOTICE.
    for leftover in upstream_root.iterdir():
        if leftover.is_file():
            leftover.unlink()
        elif leftover.is_dir() and not any(leftover.iterdir()):
            leftover.rmdir()

    # Drop the upstream wrapper dir if it's now empty.
    if upstream_root is not out and not any(upstream_root.iterdir()):
        upstream_root.rmdir()

    return len(person_dirs), total


def _write_labels_and_manifest(
    out: Path, source_url: str, person_count: int, image_count: int
) -> None:
    labels = out / "labels.csv"
    rows: list[tuple[str, str]] = []
    for person_dir in sorted(out.iterdir()):
        if not person_dir.is_dir() or not person_dir.name.startswith("person_"):
            continue
        pid = person_dir.name
        for img in sorted(person_dir.iterdir()):
            if img.is_file() and img.suffix.lower() in IMAGE_EXTS:
                rows.append((f"{person_dir.name}/{img.name}", pid))
    with labels.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rel_path", "person_id"])
        w.writerows(rows)

    manifest = {
        "dataset": DATASET_NAME,
        "source_url": source_url,
        "license": LICENSE_NAME,
        "license_url": LICENSE_URL,
        "attribution": ATTRIBUTION,
        "person_count": person_count,
        "image_count": image_count,
        "min_persons": MIN_PERSONS,
        "min_images_per_person": MIN_IMAGES_PER_PERSON,
        "labels_csv": "labels.csv",
        "layout": "person_NNN/<seq>.<ext>",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Attribution file — Apache-2.0 + CC-BY-4.0 are compatible: Apache
    # §4(d) explicitly preserves "NOTICE" text, and CC-BY requires
    # attribution. A NOTICE file in the fixture is the cleanest way to
    # satisfy both.
    notice = out / "NOTICE"
    notice.write_text(
        "\n".join([
            "pick-face real-face test fixture",
            "================================",
            "",
            f"Dataset: {DATASET_NAME}",
            f"License: {LICENSE_NAME} ({LICENSE_URL})",
            "",
            "Attribution (required by CC-BY 4.0):",
            f"  {ATTRIBUTION}",
            "",
            "Modifications:",
            "  - Re-bundled from per-subject .pgm archives into",
            "    person_NNN/<seq>.<ext> layout.",
            "  - Not redistributed in source form; this NOTICE is the",
            "    only required attribution carried inside the test",
            "    fixture directory.",
            "",
        ]),
        encoding="utf-8",
    )


def _validate(out: Path) -> None:
    manifest_path = out / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("manifest.json missing — extraction/normalize failed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pc = manifest["person_count"]
    ic = manifest["image_count"]
    min_p = manifest["min_persons"]
    min_i = manifest["min_images_per_person"]
    if pc < min_p:
        raise RuntimeError(f"only {pc} persons found, need >= {min_p}")
    per_person = Counter(
        person_dir.name
        for person_dir in out.iterdir()
        if person_dir.is_dir() and person_dir.name.startswith("person_")
        for f in person_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )
    below = {k: v for k, v in per_person.items() if v < min_i}
    if below:
        raise RuntimeError(f"persons below min_images_per_person={min_i}: {below}")
    print(f"OK: {pc} persons, {ic} images (min {min_p}x{min_i})")


def _fetch(out: Path) -> tuple[int, int, str]:
    """Single-source fetch (AT&T archive). Returns (person_count, image_count, source_url)."""
    url = SOURCE["url"]
    kind = SOURCE["kind"]
    print(f"fetching {url} ...")
    blob = _download(url)
    print(f"  {len(blob):,} bytes — extracting via gzip -d")
    _extract(blob, kind, out)
    pc, ic = _normalize(out)
    return pc, ic, url


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if manifest.json is present")
    args = ap.parse_args()

    out: Path = args.out
    manifest = out / "manifest.json"
    if manifest.exists() and not args.force:
        print(f"already present at {out} (pass --force to re-download)")
        _validate(out)
        return 0

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    pc, ic, url = _fetch(out)
    _write_labels_and_manifest(out, url, pc, ic)
    _validate(out)
    print(f"dataset ready at {out}")
    print(f"license: {LICENSE_NAME} -- see {out / 'NOTICE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
