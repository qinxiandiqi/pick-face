"""Long-task resume checkpoint (M3 / T-204).

Reference:
- docs/09 §13 (long runs survive kill -9 / Ctrl-C / power loss)
- docs/05 §7 (run table records each stage start/finish; the last
  `face.id` reached is the resume point)

Design:
  - The CLI writes `checkpoint.json` into `<out>/.cache/` after every
    batch (or after every N items).
  - Schema (versioned):
        {
          "schema": "pick-face/checkpoint@1",
          "stage": "scan|index|cluster|link",
          "mode": "full|incremental|rebuild",
          "started_at": ISO-8601,
          "updated_at": ISO-8601,
          "last_face_id": 12345,        # for index
          "last_source_path": "..."      # for scan
          "stats": { "processed": K, "errors": E }
        }
  - `load_checkpoint` returns the dict or None if absent/corrupt.
  - `save_checkpoint` writes atomically (write-then-rename).
  - `clear_checkpoint` removes the file (called at the end of a
    successful run, or by `rebuild`).

Note: the actual resume logic lives in the CLI; this module is just
the durable on-disk format.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_FILENAME = "checkpoint.json"
SCHEMA = "pick-face/checkpoint@1"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def checkpoint_path(out_dir: Path) -> Path:
    """The canonical checkpoint location: <out>/.cache/checkpoint.json."""
    return Path(out_dir) / ".cache" / CHECKPOINT_FILENAME


def load_checkpoint(out_dir: Path) -> dict | None:
    """Read the checkpoint; return None if absent / corrupt / stale."""
    path = checkpoint_path(out_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != SCHEMA:
        return None
    return data


def save_checkpoint(
    out_dir: Path,
    *,
    stage: str,
    mode: str,
    last_face_id: int | None = None,
    last_source_path: str | None = None,
    stats: dict | None = None,
    started_at: str | None = None,
) -> Path:
    """Atomically write the checkpoint file. Returns the absolute path."""
    path = checkpoint_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "stage": stage,
        "mode": mode,
        "started_at": started_at or _now_iso(),
        "updated_at": _now_iso(),
        "last_face_id": last_face_id,
        "last_source_path": last_source_path,
        "stats": dict(stats or {}),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def update_checkpoint(out_dir: Path, **fields) -> dict:
    """Update the existing checkpoint (or start a new one) and save.

    Accepts the same kwargs as save_checkpoint. If a checkpoint doesn't
    exist yet, `stage`/`mode`/`started_at` are required (the caller's
    responsibility).
    """
    existing = load_checkpoint(out_dir) or {}
    merged = {
        "schema": SCHEMA,
        "stage": fields.get("stage", existing.get("stage", "unknown")),
        "mode": fields.get("mode", existing.get("mode", "incremental")),
        "started_at": fields.get("started_at", existing.get("started_at", _now_iso())),
        "updated_at": _now_iso(),
        "last_face_id": fields.get("last_face_id", existing.get("last_face_id")),
        "last_source_path": fields.get("last_source_path", existing.get("last_source_path")),
        "stats": dict(fields.get("stats", existing.get("stats", {}))),
    }
    save_checkpoint(
        out_dir,
        stage=merged["stage"],
        mode=merged["mode"],
        last_face_id=merged["last_face_id"],
        last_source_path=merged["last_source_path"],
        stats=merged["stats"],
        started_at=merged["started_at"],
    )
    return merged


def clear_checkpoint(out_dir: Path) -> bool:
    """Delete the checkpoint file. Returns True if anything was removed."""
    path = checkpoint_path(out_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def resume_offset(out_dir: Path) -> int:
    """Convenience: return the last_face_id stored in the checkpoint, or 0.

    Callers filter their work as `WHERE id > resume_offset(out_dir)`.
    """
    cp = load_checkpoint(out_dir)
    if cp is None:
        return 0
    val = cp.get("last_face_id")
    return int(val) if isinstance(val, (int, float)) and val >= 0 else 0