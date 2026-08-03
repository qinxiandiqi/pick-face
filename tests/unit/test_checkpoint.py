"""Tests for pick_face.checkpoint (M3 / T-204).

We verify:
  - save_checkpoint writes atomically (no .tmp leftover).
  - load_checkpoint returns the same data on round-trip.
  - load_checkpoint returns None for missing / corrupt / wrong-schema files.
  - update_checkpoint preserves `started_at` while bumping `updated_at`.
  - clear_checkpoint deletes the file.
  - resume_offset returns the last_face_id, defaulting to 0.
"""

from __future__ import annotations

import json
from pathlib import Path

from pick_face.checkpoint import (
    SCHEMA,
    checkpoint_path,
    clear_checkpoint,
    load_checkpoint,
    resume_offset,
    save_checkpoint,
    update_checkpoint,
)


def test_save_and_load_roundtrip(tmp_pure: Path) -> None:
    save_checkpoint(
        tmp_pure,
        stage="index",
        mode="incremental",
        last_face_id=42,
        last_source_path="/x/a.jpg",
        stats={"processed": 100, "errors": 2},
    )
    data = load_checkpoint(tmp_pure)
    assert data is not None
    assert data["schema"] == SCHEMA
    assert data["stage"] == "index"
    assert data["mode"] == "incremental"
    assert data["last_face_id"] == 42
    assert data["last_source_path"] == "/x/a.jpg"
    assert data["stats"]["processed"] == 100
    assert data["stats"]["errors"] == 2
    assert "started_at" in data
    assert "updated_at" in data


def test_save_atomic_no_tmp_leftover(tmp_pure: Path) -> None:
    save_checkpoint(tmp_pure, stage="scan", mode="full", last_face_id=1)
    cp = checkpoint_path(tmp_pure)
    leftovers = list(cp.parent.glob("*.tmp*"))
    assert leftovers == []


def test_load_missing_returns_none(tmp_pure: Path) -> None:
    assert load_checkpoint(tmp_pure) is None


def test_load_corrupt_returns_none(tmp_pure: Path) -> None:
    cp = checkpoint_path(tmp_pure)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text("{not json", encoding="utf-8")
    assert load_checkpoint(tmp_pure) is None


def test_load_wrong_schema_returns_none(tmp_pure: Path) -> None:
    cp = checkpoint_path(tmp_pure)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"schema": "unknown@0"}), encoding="utf-8")
    assert load_checkpoint(tmp_pure) is None


def test_load_non_dict_returns_none(tmp_pure: Path) -> None:
    cp = checkpoint_path(tmp_pure)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_checkpoint(tmp_pure) is None


def test_update_checkpoint_preserves_started_at(tmp_pure: Path) -> None:
    save_checkpoint(
        tmp_pure,
        stage="cluster",
        mode="incremental",
        last_face_id=10,
        started_at="2026-08-03T10:00:00+00:00",
    )
    data = update_checkpoint(
        tmp_pure,
        last_face_id=20,
        stats={"k": 1},
    )
    assert data["started_at"] == "2026-08-03T10:00:00+00:00"
    assert data["last_face_id"] == 20
    assert data["stats"]["k"] == 1


def test_update_checkpoint_creates_when_missing(tmp_pure: Path) -> None:
    """update_checkpoint on a missing file creates one (caller sets stage)."""
    data = update_checkpoint(
        tmp_pure,
        stage="index",
        mode="incremental",
        last_face_id=5,
    )
    assert data["last_face_id"] == 5
    assert load_checkpoint(tmp_pure) is not None


def test_clear_checkpoint_removes_file(tmp_pure: Path) -> None:
    save_checkpoint(tmp_pure, stage="index", mode="full", last_face_id=1)
    assert checkpoint_path(tmp_pure).exists()
    assert clear_checkpoint(tmp_pure) is True
    assert not checkpoint_path(tmp_pure).exists()


def test_clear_checkpoint_no_file_returns_false(tmp_pure: Path) -> None:
    assert clear_checkpoint(tmp_pure) is False


def test_resume_offset_returns_last_face_id(tmp_pure: Path) -> None:
    save_checkpoint(tmp_pure, stage="index", mode="incremental", last_face_id=42)
    assert resume_offset(tmp_pure) == 42


def test_resume_offset_default_zero(tmp_pure: Path) -> None:
    assert resume_offset(tmp_pure) == 0


def test_resume_offset_handles_negative(tmp_pure: Path) -> None:
    """A corrupted/negative value defaults to 0 (callers shouldn't choke)."""
    save_checkpoint(tmp_pure, stage="index", mode="incremental", last_face_id=-1)
    assert resume_offset(tmp_pure) == 0


def test_save_overwrites_existing(tmp_pure: Path) -> None:
    save_checkpoint(tmp_pure, stage="scan", mode="full", last_face_id=1)
    save_checkpoint(tmp_pure, stage="scan", mode="full", last_face_id=2)
    data = load_checkpoint(tmp_pure)
    assert data["last_face_id"] == 2


def test_checkpoint_path_lives_in_cache(tmp_pure: Path) -> None:
    assert checkpoint_path(tmp_pure) == tmp_pure / ".cache" / "checkpoint.json"
