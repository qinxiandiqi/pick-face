"""Application root resolution — `~/.pick-face/` per docs/05 §0.

The single source of truth for where pick-face stores its files.
Resolution priority (high → low):

    1. ``PICK_FACE_HOME`` environment variable (Docker / multi-instance / debug)
    2. ``data_dir`` argument passed explicitly (used by tests + CLI flags)
    3. ``~/.pick-face/`` (the default)

All other paths in the Web service are derived from this root via
:meth:`AppPaths.layout`. The layout follows the three-tier split from
docs/05 §0.1: ``config/`` (editable), ``data/`` (backup-this-equals-
backup-the-album), ``cache/`` (redownloadable).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT_NAME = ".pick-face"
ENV_VAR = "PICK_FACE_HOME"


def resolve_root(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the application root directory.

    Args:
        data_dir: explicit override (CLI flag / test fixture). Wins over
            the env var.

    Returns:
        Absolute path to the application root. Created if it doesn't
        already exist (mkdir -p semantics, so callers don't need to
        race on first startup).
    """
    if data_dir is not None:
        root = Path(data_dir).expanduser().resolve()
    else:
        env = os.environ.get(ENV_VAR)
        if env:
            root = Path(env).expanduser().resolve()
        else:
            root = (Path.home() / DEFAULT_ROOT_NAME).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass(frozen=True)
class AppLayout:
    """Resolved sub-paths under the application root.

    All paths are absolute. ``None`` sub-paths (rare; only when the
    caller explicitly disables a tier) are surfaced as such so service
    code can fail loudly rather than silently write to ``/``.
    """

    root: Path
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    config_file: Path
    db_path: Path
    hnsw_path: Path
    chips_dir: Path
    thumbnails_dir: Path
    covers_dir: Path
    jobs_dir: Path
    logs_dir: Path
    models_dir: Path
    tmp_dir: Path


def compute_layout(root: Path) -> AppLayout:
    """Compute the canonical layout under ``root``.

    Mirrors ``docs/05 §1``. Side-effect: creates every directory
    eagerly so downstream services can write without TOCTOU races.
    """
    config_dir = root / "config"
    data_dir = root / "data"
    cache_dir = root / "cache"
    paths = AppLayout(
        root=root,
        config_dir=config_dir,
        data_dir=data_dir,
        cache_dir=cache_dir,
        config_file=config_dir / "config.toml",
        db_path=data_dir / "index.sqlite",
        hnsw_path=data_dir / "index.hnsw",
        chips_dir=data_dir / "chips",
        thumbnails_dir=data_dir / "thumbnails",
        covers_dir=data_dir / "covers",
        jobs_dir=data_dir / "jobs",
        logs_dir=data_dir / "logs",
        models_dir=cache_dir / "models",
        tmp_dir=cache_dir / "tmp",
    )
    for p in (
        paths.config_dir,
        paths.data_dir,
        paths.cache_dir,
        paths.chips_dir,
        paths.thumbnails_dir,
        paths.covers_dir,
        paths.jobs_dir,
        paths.logs_dir,
        paths.models_dir,
        paths.tmp_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)
    return paths


def get_layout(data_dir: str | os.PathLike[str] | None = None) -> AppLayout:
    """Convenience: resolve root + compute layout in one call.

    This is the function every service / api / worker entry point
    should use. Tests pass ``data_dir=tmp_path``; production uses the
    env var or default.
    """
    return compute_layout(resolve_root(data_dir))
