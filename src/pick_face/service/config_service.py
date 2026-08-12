"""Path whitelist CRUD — `docs/01 §1.1 US-1` + `docs/03 §2.1`.

The config service persists user-facing configuration in
``~/.pick-face/config/config.toml`` and exposes a CRUD API over the
list of scan paths. The whitelist invariant is:

    * Every accepted path must exist, be readable, and be a directory.
    * Every accepted path is normalized via ``Path.resolve()`` (no
      symlink games, no relative paths, no ``..`` traversal).
    * The whitelist is enforced in *both* directions: adding a path
      requires validation; serving photos requires the photo's resolved
      path to live under a whitelisted ancestor (``photo_service`` does
      this check).

The service is *stateless*: it loads / saves the config file each call.
This is fine for the v3 single-user target — concurrent writers are
the CLI itself + the FastAPI handler, both inside one process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import tomllib

from pick_face.core.errors import ConfigError

from .paths import AppLayout, get_layout


@dataclass
class ScanPath:
    """A whitelisted scan root.

    Mirrors the ``scan_paths`` table documented in `docs/05 §2`. In
    M6 the same data lives in config.toml (no SQLite yet); once the
    FastAPI app boots and the worker starts writing, this dataclass
    is the read-side view onto that table.
    """

    id: int
    path: Path
    enabled: bool = True
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_scan_at: datetime | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": str(self.path),
            "enabled": self.enabled,
            "added_at": self.added_at.isoformat(),
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "notes": self.notes,
        }


class PathValidationError(ValueError):
    """Raised when a candidate path fails whitelist validation.

    Carries a stable ``code`` so HTTP handlers can map to 400-class
    responses without leaking internals (see ``docs/01 §1.1 AC-2`` and
    ``docs/03 §2.1`` error contract).
    """

    VALID = "OK"
    NOT_FOUND = "NOT_FOUND"
    NOT_A_DIRECTORY = "NOT_A_DIRECTORY"
    NOT_READABLE = "NOT_READABLE"
    NOT_WHITELISTED = "NOT_WHITELISTED"
    DUPLICATE = "DUPLICATE"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


def validate_candidate(raw: str | os.PathLike[str]) -> Path:
    """Resolve a candidate path to its absolute, canonical form.

    Rules (per docs/01 §1.1 AC-2 / AC-3):

    1. ``Path.resolve(strict=False)`` — raises nothing for missing
       paths; we check existence below so we can give a precise error
       code.
    2. ``..`` traversal is rejected at the lexical level before
       ``resolve()`` — even if ``resolve()`` would normalize it away,
       we want a loud error to surface hostile input fast.
    3. The path must exist.
    4. The path must be a directory (not a single file).
    5. The path must be readable by the current process.
    """
    raw_str = str(raw)
    if not raw_str or raw_str.strip() == "":
        raise PathValidationError(
            PathValidationError.NOT_FOUND, "empty path"
        )
    # Lexical traversal guard. resolve() will normalize `..` away but
    # we want explicit rejection so an attacker sees a 400 not a
    # silently-rewritten path.
    if ".." in Path(raw_str).parts:
        raise PathValidationError(
            PathValidationError.PATH_TRAVERSAL,
            f"path contains '..' segment: {raw_str!r}",
        )
    candidate = Path(raw_str).expanduser().resolve(strict=False)
    if not candidate.exists():
        raise PathValidationError(
            PathValidationError.NOT_FOUND,
            f"path does not exist: {candidate}",
        )
    if not candidate.is_dir():
        raise PathValidationError(
            PathValidationError.NOT_A_DIRECTORY,
            f"path is not a directory: {candidate}",
        )
    if not os.access(candidate, os.R_OK):
        raise PathValidationError(
            PathValidationError.NOT_READABLE,
            f"path is not readable: {candidate}",
        )
    return candidate


def is_under_any_whitelisted(
    candidate: Path, whitelisted: list[Path]
) -> bool:
    """True if ``candidate`` is at or under any whitelisted root.

    Used by ``photo_service`` before serving a file: the resolved
    photo path must be a descendant of a whitelisted scan root, or
    we refuse (defense in depth against DB tampering).
    """
    candidate_resolved = candidate.resolve(strict=False)
    for root in whitelisted:
        try:
            candidate_resolved.relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


# -----------------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------------


_DEFAULT_CONFIG_TEMPLATE = """\
# pick-face v3.0 configuration
# Auto-generated by `pick-face-web init`. Edit values and restart the service.

[server]
host = "127.0.0.1"
port = 8000

[scan]
default_pack = "yunet-sface"          # or "yunet-arcface"
incremental_interval_sec = 300        # watchdog fallback poll

[index]
# Sub-paths override the defaults under ~/.pick-face/. All relative to
# the application root unless absolute.
db_path = "data/index.sqlite"
hnsw_path = "data/index.hnsw"
chips_dir = "data/chips"
thumbnails_dir = "data/thumbnails"
covers_dir = "data/covers"
models_dir = "cache/models"

[clustering]
merge_threshold = 0.0                  # 0.0 for SFace 128-D, 0.55 for ArcFace 512-D
auto_recluster_min_new = 500

[commercial]
accept_noncommercial_model_license = false  # AC-9 fail-safe

# Scan paths are managed via `pick-face-web` / `POST /api/config/paths`.
# Edit by hand only if you know what you're doing; the on-disk shape
# mirrors the `scan_paths` table documented in docs/05 §2.
[[scan_paths]]
path = "__SCAN_PATH__"
enabled = true
notes = "initial path"
"""


def write_default_config(layout: AppLayout, scan_path: Path | None = None) -> Path:
    """Write a default config.toml under ``layout.config_dir``.

    The first-run experience: ``pick-face-web init`` writes a working
    config so the user can ``serve`` immediately after.

    Returns:
        The path of the written config file.
    """
    if layout.config_file.exists():
        return layout.config_file
    body = _DEFAULT_CONFIG_TEMPLATE
    if scan_path is not None:
        # Escape the path as a TOML basic string (backslashes, quotes).
        toml_path = _toml_value(str(scan_path)).strip('"')
        body = body.replace("__SCAN_PATH__", toml_path)
    else:
        body = body.replace('[[scan_paths]]\npath = "__SCAN_PATH__"', "")
    layout.config_file.parent.mkdir(parents=True, exist_ok=True)
    layout.config_file.write_text(body, encoding="utf-8")
    return layout.config_file


def load_config(layout: AppLayout) -> dict[str, object]:
    """Load and parse ``config.toml``; returns empty dict if missing.

    The returned shape is intentionally loose: the config service only
    cares about ``[[scan_paths]]`` for the whitelist. Other sections
    are passed through to the workers / runtime.
    """
    if not layout.config_file.exists():
        return {}
    with layout.config_file.open("rb") as f:
        return tomllib.load(f)


def save_config(layout: AppLayout, data: dict[str, object]) -> None:
    """Persist the in-memory config dict back to ``config.toml``.

    We delegate to a hand-rolled writer rather than pulling in
    ``tomli-w`` to keep the web extra lean. The writer preserves the
    structure of the default template so hand-edits stay readable.
    """
    lines: list[str] = []
    lines.append("# pick-face v3.0 configuration")
    lines.append("")
    server = data.get("server", {})
    if isinstance(server, dict):
        lines.append("[server]")
        for k, v in server.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    scan_cfg = data.get("scan", {})
    if isinstance(scan_cfg, dict):
        lines.append("[scan]")
        for k, v in scan_cfg.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    scan_paths = data.get("scan_paths", [])
    if isinstance(scan_paths, list) and scan_paths:
        for sp in scan_paths:
            if not isinstance(sp, dict):
                continue
            lines.append("[[scan_paths]]")
            for k, v in sp.items():
                lines.append(f"{k} = {_toml_value(v)}")
            lines.append("")
    layout.config_file.parent.mkdir(parents=True, exist_ok=True)
    layout.config_file.write_text("\n".join(lines), encoding="utf-8")


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        # TOML basic strings: escape backslashes, then double-quotes,
        # then newlines. Hand-rolled (no tomli-w dep) so keep the
        # escape order correct: backslashes first, otherwise we double
        # the escapes we just added.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(v, Path):
        return _toml_value(str(v))
    raise ConfigError(f"unsupported toml value type: {type(v).__name__}")


# -----------------------------------------------------------------------------
# Public CRUD API
# -----------------------------------------------------------------------------


class ConfigService:
    """Stateless CRUD over the whitelist.

    Every method either returns a ``ScanPath`` (or list thereof) or
    raises ``PathValidationError``. There's no in-memory cache: we
    re-read the file each call. The single-process assumption makes
    this safe and cheap; a multi-process v4 will replace this with a
    SQLite-backed implementation that mirrors v2.x's review table
    pattern.
    """

    def __init__(self, layout: AppLayout) -> None:
        self._layout = layout
        # Load the existing config (may be missing on first run).
        self._data: dict[str, object] = load_config(layout)
        # In-memory id counter (auto-increment). We persist the data
        # to config.toml so the counter survives restarts.
        existing = self._data.get("scan_paths", [])
        self._next_id = (
            max(
                (int(sp.get("id", 0)) for sp in existing if isinstance(sp, dict)),
                default=0,
            )
            + 1
        )

    # -- queries --------------------------------------------------------------

    def list_paths(self) -> list[ScanPath]:
        """Return all whitelisted scan paths in insertion order."""
        rows = self._data.get("scan_paths", [])
        out: list[ScanPath] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(_row_to_scan_path(row))
        return out

    def enabled_paths(self) -> list[Path]:
        """Return resolved paths for enabled scan roots only."""
        return [sp.path for sp in self.list_paths() if sp.enabled]

    # -- mutations ------------------------------------------------------------

    def add_path(self, raw: str | os.PathLike[str], notes: str = "") -> ScanPath:
        """Validate, dedupe, and append a scan path.

        Raises:
            PathValidationError: with a stable error code on failure.
        """
        candidate = validate_candidate(raw)
        for existing in self.list_paths():
            if existing.path == candidate:
                raise PathValidationError(
                    PathValidationError.DUPLICATE,
                    f"path already whitelisted: {candidate}",
                )
        sp = ScanPath(
            id=self._next_id,
            path=candidate,
            enabled=True,
            notes=notes,
        )
        self._next_id += 1
        rows = self._data.setdefault("scan_paths", [])
        rows.append(
            {
                "id": sp.id,
                "path": str(sp.path),
                "enabled": sp.enabled,
                "added_at": sp.added_at.isoformat(),
                "notes": sp.notes,
            }
        )
        save_config(self._layout, self._data)
        return sp

    def remove_path(self, path_id: int) -> bool:
        """Remove the entry with ``path_id``. Returns False if not found."""
        rows = self._data.get("scan_paths", [])
        for i, row in enumerate(list(rows)):
            if isinstance(row, dict) and int(row.get("id", -1)) == path_id:
                rows.pop(i)
                save_config(self._layout, self._data)
                return True
        return False

    def set_enabled(self, path_id: int, enabled: bool) -> bool:
        """Toggle the ``enabled`` flag. Returns False if not found."""
        rows = self._data.get("scan_paths", [])
        for row in rows:
            if isinstance(row, dict) and int(row.get("id", -1)) == path_id:
                row["enabled"] = enabled
                save_config(self._layout, self._data)
                return True
        return False


def _row_to_scan_path(row: dict[str, object]) -> ScanPath:
    """Reconstruct a ``ScanPath`` from a config row."""
    path = Path(str(row["path"]))
    added_at_raw = row.get("added_at")
    added_at = (
        datetime.fromisoformat(str(added_at_raw))  # type: ignore[arg-type]
        if isinstance(added_at_raw, str)
        else datetime.now(timezone.utc)
    )
    last_scan_raw = row.get("last_scan_at")
    last_scan = (
        datetime.fromisoformat(str(last_scan_raw))  # type: ignore[arg-type]
        if isinstance(last_scan_raw, str)
        else None
    )
    return ScanPath(
        id=int(row.get("id", 0)),
        path=path,
        enabled=bool(row.get("enabled", True)),
        added_at=added_at,
        last_scan_at=last_scan,
        notes=str(row.get("notes", "")),
    )


__all__ = [
    "AppLayout",
    "ConfigService",
    "PathValidationError",
    "ScanPath",
    "get_layout",
    "is_under_any_whitelisted",
    "load_config",
    "save_config",
    "validate_candidate",
    "write_default_config",
]
