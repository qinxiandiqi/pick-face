"""Cross-platform cache / model / data directory resolution.

Reference: docs/03 §4.2 运行期数据布局 + docs/10 §7.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir

APP_NAME = "pick-face"
APP_AUTHOR = "pick-face"


def default_model_dir() -> Path:
    """Default per-platform model root.

    Linux : $XDG_CACHE_HOME/pick-face/models  (default ~/.cache/pick-face/models)
    macOS : ~/Library/Caches/pick-face/models/
    Windows: %LOCALAPPDATA%\\pick-face\\models\\
    """
    base = Path(
        os.environ.get("INSIGHTFACE_HOME")
        or os.environ.get("PICK_FACE_MODEL_DIR")
        or user_cache_dir(APP_NAME, APP_AUTHOR)
    )
    return base / "models"


def default_data_dir() -> Path:
    """Per-platform data root (db, hnsw, etc)."""
    return Path(user_data_dir(APP_NAME, APP_AUTHOR))


def ensure_dir(path: Path) -> Path:
    """Create path (parents=True, exist_ok=True) and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
