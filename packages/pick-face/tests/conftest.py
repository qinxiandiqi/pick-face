"""Shared pytest fixtures for the pick-face test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable when pytest is invoked without editable install.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def tmp_pure(tmp_path: Path):
    """An isolated tmp_path with no inherited env vars that could change behavior."""
    old_env = os.environ.copy()
    for var in ("INSIGHTFACE_HOME", "PICK_FACE_MODEL_DIR", "PICK_FACE_CONFIG"):
        os.environ.pop(var, None)
    try:
        yield tmp_path
    finally:
        os.environ.clear()
        os.environ.update(old_env)
