"""Tests for service/paths.py — the v3 app-root contract.

Covers `docs/03 §1.1` and the user-confirmed `~/.pick-face` root
(`PICK_FACE_HOME` env override; explicit arg wins).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_resolve_root_default(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Path.home() reads USERPROFILE on Windows / HOME elsewhere.
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_pure))
    monkeypatch.delenv("PICK_FACE_HOME", raising=False)
    from pick_face.service.paths import DEFAULT_ROOT_NAME, resolve_root

    root = resolve_root()
    assert root == (tmp_pure / DEFAULT_ROOT_NAME).resolve()
    assert root.is_dir()


def test_resolve_root_env_override(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_pure / "custom-app"
    monkeypatch.setenv("PICK_FACE_HOME", str(custom))
    from pick_face.service.paths import resolve_root

    root = resolve_root()
    assert root == custom.resolve()
    assert root.is_dir()


def test_resolve_root_explicit_arg_wins(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "env-root"))
    explicit = tmp_pure / "arg-root"
    from pick_face.service.paths import resolve_root

    assert resolve_root(explicit) == explicit.resolve()


def test_compute_layout_has_all_thirteen_subdirs(tmp_pure: Path) -> None:
    from pick_face.service.paths import compute_layout, resolve_root

    root = resolve_root(tmp_pure / "app")
    layout = compute_layout(root)
    # All AppLayout fields exist.
    names = {f.name for f in layout.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    expected = {
        "root",
        "config_dir",
        "data_dir",
        "cache_dir",
        "config_file",
        "db_path",
        "hnsw_path",
        "chips_dir",
        "thumbnails_dir",
        "covers_dir",
        "jobs_dir",
        "logs_dir",
        "models_dir",
        "tmp_dir",
    }
    assert expected.issubset(names)
    # Subdirs actually live under the three-tier buckets.
    assert layout.config_dir.is_relative_to(root)
    assert layout.data_dir.is_relative_to(root)
    assert layout.cache_dir.is_relative_to(root)


def test_get_layout_creates_dirs_idempotently(tmp_pure: Path) -> None:
    from pick_face.service.paths import get_layout

    layout1 = get_layout(data_dir=tmp_pure / "x")
    layout2 = get_layout(data_dir=tmp_pure / "x")
    assert layout1.root == layout2.root
    # Every subdir exists after first call.
    for d in (layout1.config_dir, layout1.data_dir, layout1.cache_dir):
        assert d.is_dir()
    for f in (
        layout1.db_path,
        layout1.hnsw_path,
        layout1.config_file,
    ):
        # Files don't need to exist; just under correct parent.
        assert f.parent.is_dir()


def test_layout_files_resolve_under_correct_tier(tmp_pure: Path) -> None:
    """config_file is under config/, db/hnsw/chips/.. are under data/."""
    from pick_face.service.paths import get_layout

    layout = get_layout(data_dir=tmp_pure / "app")
    assert layout.config_file.is_relative_to(layout.config_dir)
    assert layout.db_path.is_relative_to(layout.data_dir)
    assert layout.hnsw_path.is_relative_to(layout.data_dir)
    assert layout.chips_dir.is_relative_to(layout.data_dir)
    assert layout.thumbnails_dir.is_relative_to(layout.data_dir)
    assert layout.covers_dir.is_relative_to(layout.data_dir)
    assert layout.models_dir.is_relative_to(layout.cache_dir)


def test_default_root_name_is_dot_pick_face() -> None:
    from pick_face.service.paths import DEFAULT_ROOT_NAME, ENV_VAR

    assert DEFAULT_ROOT_NAME == ".pick-face"
    assert ENV_VAR == "PICK_FACE_HOME"
