"""Pytest fixture exposing the real-face dataset to integration tests.

The dataset is *not* committed — it lives under tests/fixtures/real_faces/
after running:

    uv run python scripts/fetch_face_dataset.py

Tests skip cleanly if the manifest is missing so the default unit-test
job stays fast and offline.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT / "tests" / "fixtures" / "real_faces"
MANIFEST = DATASET_DIR / "manifest.json"


def _is_available() -> bool:
    return MANIFEST.exists() and (DATASET_DIR / "labels.csv").exists()


@pytest.fixture(scope="session")
def real_face_dir() -> Path:
    """Path to the real-face dataset root (tests/fixtures/real_faces/)."""
    if not _is_available():
        pytest.skip(
            "real-face dataset not fetched — run: uv run python scripts/fetch_face_dataset.py"
        )
    return DATASET_DIR


@pytest.fixture(scope="session")
def real_face_manifest(real_face_dir: Path) -> dict:
    return json.loads((real_face_dir / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def real_face_labels(real_face_dir: Path) -> dict[str, str]:
    """Map rel_path → person_id."""
    labels: dict[str, str] = {}
    with (real_face_dir / "labels.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels[row["rel_path"]] = row["person_id"]
    return labels


@pytest.fixture(scope="session")
def real_face_person_counts(real_face_labels: dict[str, str]) -> dict[str, int]:
    return dict(Counter(real_face_labels.values()))


@pytest.fixture(scope="session")
def real_face_root_src(real_face_dir: Path) -> Path:
    """A directory whose contents are the per-person image folders.

    Use this as `--src` for `pick-face run`. The fixture flattens
    person_NNN/ into the root so the CLI sees a single tree.
    """
    return real_face_dir


# Marker registration — `pytest --strict-markers` will fail if a marker
# is used without registration.
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_data: integration tests that require the real-face dataset "
        "(skipped unless fetched). Run: "
        "`uv run python scripts/fetch_face_dataset.py`",
    )
