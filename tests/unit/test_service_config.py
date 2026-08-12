"""Tests for service/config_service.py — path whitelist CRUD + validation."""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def test_validate_candidate_rejects_traversal(tmp_pure: Path) -> None:
    from pick_face.service.config_service import (
        PathValidationError,
        validate_candidate,
    )

    with pytest.raises(PathValidationError) as exc:
        validate_candidate(str(tmp_pure / "a" / ".." / "b"))
    assert exc.value.code == PathValidationError.PATH_TRAVERSAL


def test_validate_candidate_rejects_empty(tmp_pure: Path) -> None:
    from pick_face.service.config_service import (
        PathValidationError,
        validate_candidate,
    )

    with pytest.raises(PathValidationError) as exc:
        validate_candidate("")
    assert exc.value.code == PathValidationError.NOT_FOUND


def test_validate_candidate_rejects_missing(tmp_pure: Path) -> None:
    from pick_face.service.config_service import (
        PathValidationError,
        validate_candidate,
    )

    with pytest.raises(PathValidationError) as exc:
        validate_candidate(str(tmp_pure / "nonexistent"))
    assert exc.value.code == PathValidationError.NOT_FOUND


def test_validate_candidate_rejects_file(tmp_pure: Path) -> None:
    from pick_face.service.config_service import (
        PathValidationError,
        validate_candidate,
    )

    f = tmp_pure / "regular.txt"
    f.write_text("hi")
    with pytest.raises(PathValidationError) as exc:
        validate_candidate(str(f))
    assert exc.value.code == PathValidationError.NOT_A_DIRECTORY


def test_validate_candidate_accepts_directory(tmp_pure: Path) -> None:
    from pick_face.service.config_service import validate_candidate

    d = tmp_pure / "photos"
    d.mkdir()
    resolved = validate_candidate(d)
    assert resolved.is_absolute()
    assert resolved.is_dir()


def test_is_under_any_whitelisted_basic(tmp_pure: Path) -> None:
    from pick_face.service.config_service import is_under_any_whitelisted

    root = tmp_pure / "photos"
    root.mkdir()
    nested = root / "2024" / "jan" / "img.jpg"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    assert is_under_any_whitelisted(nested, [root])
    assert not is_under_any_whitelisted(tmp_pure / "other" / "a.jpg", [root])


def test_is_under_any_whitelisted_sibling_not_matched(tmp_pure: Path) -> None:
    """A path with the same prefix but a different parent must NOT match.

    e.g. ``/tmp/photos`` must not match whitelist ``/tmp/photos-old``.
    """
    from pick_face.service.config_service import is_under_any_whitelisted

    a = tmp_pure / "photos"
    b = tmp_pure / "photos-old"
    a.mkdir()
    b.mkdir()
    inside_b = b / "a.jpg"
    inside_b.write_bytes(b"x")
    assert not is_under_any_whitelisted(inside_b, [a])


def test_write_default_config_idempotent(tmp_pure: Path) -> None:
    from pick_face.service.config_service import write_default_config

    layout = _make_layout(tmp_pure)
    path = write_default_config(layout, scan_path=tmp_pure / "photos")
    assert path.exists()
    body1 = path.read_text()
    # Calling again is a no-op.
    write_default_config(layout, scan_path=tmp_pure / "photos")
    assert path.read_text() == body1


def test_add_path_dedupes(tmp_pure: Path) -> None:
    from pick_face.service.config_service import (
        ConfigService,
        PathValidationError,
    )

    layout = _make_layout(tmp_pure)
    d = tmp_pure / "photos"
    d.mkdir()
    svc = ConfigService(layout)
    sp = svc.add_path(str(d), notes="first")
    assert sp.path == d.resolve()
    with pytest.raises(PathValidationError) as exc:
        svc.add_path(str(d), notes="dup")
    assert exc.value.code == PathValidationError.DUPLICATE


def test_add_remove_toggle(tmp_pure: Path) -> None:
    from pick_face.service.config_service import ConfigService

    layout = _make_layout(tmp_pure)
    a, b = tmp_pure / "a", tmp_pure / "b"
    a.mkdir()
    b.mkdir()
    svc = ConfigService(layout)
    spa = svc.add_path(str(a), notes="a")
    spb = svc.add_path(str(b), notes="b")
    listed = {sp.path for sp in svc.list_paths()}
    assert listed == {a.resolve(), b.resolve()}
    # Toggle off
    assert svc.set_enabled(spb.id, False)
    enabled = svc.enabled_paths()
    assert a.resolve() in enabled
    assert b.resolve() not in enabled
    # Remove
    assert svc.remove_path(spa.id)
    assert {sp.id for sp in svc.list_paths()} == {spb.id}
    # Remove non-existent returns False
    assert not svc.remove_path(9999)
    # Toggle non-existent returns False
    assert not svc.set_enabled(9999, True)


def test_persistence_across_instances(tmp_pure: Path) -> None:
    """Two ConfigService instances must see the same data."""
    from pick_face.service.config_service import ConfigService

    layout = _make_layout(tmp_pure)
    d = tmp_pure / "photos"
    d.mkdir()
    ConfigService(layout).add_path(str(d), notes="x")
    reloaded = ConfigService(layout)
    listed = reloaded.list_paths()
    assert len(listed) == 1
    assert listed[0].path == d.resolve()
    assert listed[0].notes == "x"


def test_persisted_config_drops_initial_placeholder(tmp_pure: Path) -> None:
    """`write_default_config` without scan_path must not keep the placeholder."""
    from pick_face.service.config_service import write_default_config

    layout = _make_layout(tmp_pure)
    p = write_default_config(layout, scan_path=None)
    body = p.read_text()
    assert "__SCAN_PATH__" not in body
    assert "[[scan_paths]]" not in body


def test_toml_writer_round_trip(tmp_pure: Path) -> None:
    """save_config must produce a file that tomllib can re-read."""
    import tomllib

    from pick_face.service.config_service import save_config

    layout = _make_layout(tmp_pure)
    data = {
        "server": {"host": "0.0.0.0", "port": 9000},
        "scan": {"default_pack": "yunet-arcface", "incremental_interval_sec": 60},
        "scan_paths": [
            {"id": 1, "path": str(tmp_pure), "enabled": True, "notes": "n1"},
        ],
    }
    save_config(layout, data)
    with (layout.config_file).open("rb") as f:
        roundtripped = tomllib.load(f)
    assert roundtripped["server"]["host"] == "0.0.0.0"
    assert roundtripped["server"]["port"] == 9000
    assert roundtripped["scan"]["default_pack"] == "yunet-arcface"
    assert roundtripped["scan_paths"][0]["path"] == str(tmp_pure)
