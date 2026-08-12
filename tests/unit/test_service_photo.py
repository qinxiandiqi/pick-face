"""Tests for service/photo_service.py — thumbnail cache + whitelist enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def _make_jpg(path: Path, color=(255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), color).save(path, "JPEG")


def _insert_source(layout, path: Path, content_hash: str = "") -> int:
    from pick_face.store.index import open_db

    size = path.stat().st_size if path.exists() else 0
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(path),
            str(path.name),
            size,
            1.0,
            "xxh3_64",
            content_hash,
            "active",
            1.0,
            1.0,
        ),
    )
    conn.commit()
    conn.close()
    return int(cur.lastrowid)


def test_get_photo_round_trip(tmp_pure: Path) -> None:
    layout = _layout(tmp_pure)
    p = tmp_pure / "photo.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p, content_hash="")
    from pick_face.service.photo_service import PhotoService

    rec = PhotoService(layout).get_photo(pid)
    assert rec.id == pid
    assert rec.path == p
    assert rec.content_hash == ""


def test_get_photo_not_found(tmp_pure: Path) -> None:
    from pick_face.service.photo_service import PhotoNotFoundError, PhotoService

    layout = _layout(tmp_pure)
    with pytest.raises(PhotoNotFoundError):
        PhotoService(layout).get_photo(999)


def test_thumbnail_path_is_two_level_bucket(tmp_pure: Path) -> None:
    from pick_face.service.photo_service import PhotoService

    layout = _layout(tmp_pure)
    svc = PhotoService(layout)
    p = svc._thumbnail_path("abcdef0123456789")  # noqa: SLF001 — internal helper
    expected = layout.thumbnails_dir / "ab" / "cd" / "abcdef0123456789.jpg"
    assert p == expected


def test_thumbnail_generated_on_first_call(tmp_pure: Path) -> None:
    layout = _layout(tmp_pure)
    p = tmp_pure / "p.jpg"
    _make_jpg(p, color=(10, 20, 30))
    pid = _insert_source(layout, p)
    from pick_face.service.photo_service import PhotoService

    svc = PhotoService(layout)
    thumb = svc.thumbnail(pid)
    assert thumb.exists()
    # It's a valid JPEG
    with Image.open(thumb) as im:
        assert im.format == "JPEG"
        assert max(im.size) <= 256


def test_thumbnail_reused_on_second_call(tmp_pure: Path) -> None:
    layout = _layout(tmp_pure)
    p = tmp_pure / "p.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p)
    from pick_face.service.photo_service import PhotoService

    svc = PhotoService(layout)
    thumb1 = svc.thumbnail(pid)
    thumb2 = svc.thumbnail(pid)
    assert thumb1 == thumb2
    # Hash was computed and persisted on first call.
    rec = svc.get_photo(pid)
    assert rec.content_hash != ""


def test_thumbnail_marks_missing_photo(tmp_pure: Path) -> None:
    layout = _layout(tmp_pure)
    p = tmp_pure / "ghost.jpg"
    # Don't write the file
    pid = _insert_source(layout, p)
    from pick_face.service.photo_service import PhotoNotFoundError, PhotoService

    svc = PhotoService(layout)
    with pytest.raises(PhotoNotFoundError):
        svc.thumbnail(pid)
    # DB row should be marked 'missing'
    from pick_face.store.index import open_db
    conn = open_db(layout.db_path)
    status = conn.execute("SELECT status FROM source WHERE id = ?", (pid,)).fetchone()[0]
    conn.close()
    assert status == "missing"


def test_get_photo_path_whitelist_check(tmp_pure: Path) -> None:
    """Photo whose resolved path is not under any whitelisted root → 403."""
    from pick_face.service.config_service import ConfigService
    from pick_face.service.photo_service import (
        PhotoAccessError,
        PhotoService,
    )

    layout = _layout(tmp_pure)
    # Whitelist one directory
    allowed = tmp_pure / "allowed"
    allowed.mkdir()
    ConfigService(layout).add_path(str(allowed))
    # Photo lives in a *different* directory
    outside = tmp_pure / "outside"
    outside.mkdir()
    p = outside / "p.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p)
    svc = PhotoService(layout)
    with pytest.raises(PhotoAccessError):
        svc.get_photo_path(pid)


def test_get_photo_path_under_whitelist_succeeds(tmp_pure: Path) -> None:
    from pick_face.service.config_service import ConfigService
    from pick_face.service.photo_service import PhotoService

    layout = _layout(tmp_pure)
    allowed = tmp_pure / "allowed"
    allowed.mkdir()
    ConfigService(layout).add_path(str(allowed))
    p = allowed / "p.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p)
    svc = PhotoService(layout)
    assert svc.get_photo_path(pid) == p
