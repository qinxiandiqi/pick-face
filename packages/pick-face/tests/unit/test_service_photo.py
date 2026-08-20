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


def _make_jpg_with_exif(path: Path, *, make="Canon", model="EOS R6",
                        taken_at="2024:06:15 14:30:00",
                        lens="RF 50mm F1.2 L USM",
                        exposure=(1, 200), f_number=(28, 10),
                        iso=400, focal_length=(50, 1),
                        gps_lat=None, gps_lon=None,
                        gps_lat_ref="N", gps_lon_ref="W") -> None:
    """Write a JPEG with EXIF tags via PIL. ``gps_lat``/``gps_lon`` are
    DMS tuples like ``(deg, min, sec)``."""
    from PIL import ExifTags

    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (640, 480), (10, 20, 30))
    exif = im.getexif()
    if make is not None:
        exif[ExifTags.Base.Make] = make
    if model is not None:
        exif[ExifTags.Base.Model] = model
    if taken_at is not None:
        exif[ExifTags.Base.DateTimeOriginal] = taken_at
    if lens is not None:
        exif[ExifTags.Base.LensModel] = lens
    if exposure is not None:
        exif[ExifTags.Base.ExposureTime] = exposure
    if f_number is not None:
        exif[ExifTags.Base.FNumber] = f_number
    if iso is not None:
        exif[ExifTags.Base.ISOSpeedRatings] = iso
    if focal_length is not None:
        exif[ExifTags.Base.FocalLength] = focal_length
    if gps_lat is not None and gps_lon is not None:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps[1] = gps_lat_ref
        gps[2] = gps_lat
        gps[3] = gps_lon_ref
        gps[4] = gps_lon
    im.save(path, "JPEG", exif=exif.tobytes())


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


def test_get_photo_metadata_includes_natural_dim_and_faces(tmp_pure: Path) -> None:
    """M7.5 — get_photo_metadata returns natural W/H + every face row."""
    from pick_face.service.photo_service import PhotoMetadata, PhotoService
    from pick_face.store.index import open_db

    layout = _layout(tmp_pure)
    p = tmp_pure / "p.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p, content_hash="z" * 16)
    conn = open_db(layout.db_path)
    conn.execute(
        "INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  cluster_id, det_score, quality, embedding, model_version) "
        "VALUES (?, 5, 10, 50, 60, 11, 0.9, 0.7, ?, \"test@x\")",
        (pid, b'placeholder-embedding-bytes-1234'),
    )
    conn.commit()
    conn.close()

    meta = PhotoService(layout).get_photo_metadata(pid)
    assert isinstance(meta, PhotoMetadata)
    assert meta.id == pid
    assert meta.path == p
    assert meta.natural_width == 640
    assert meta.natural_height == 480
    assert len(meta.faces) == 1
    f = meta.faces[0]
    assert f.bbox_x1 == 5.0 and f.bbox_y1 == 10.0
    assert f.bbox_x2 == 50.0 and f.bbox_y2 == 60.0
    assert f.cluster_id == 11
    assert f.det_score == 0.9
    assert f.quality == 0.7


def test_get_photo_metadata_no_faces(tmp_pure: Path) -> None:
    """M7.5 — empty faces list, not an error."""
    from pick_face.service.photo_service import PhotoService

    layout = _layout(tmp_pure)
    p = tmp_pure / "p.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p, content_hash="a" * 16)
    meta = PhotoService(layout).get_photo_metadata(pid)
    assert meta.faces == []
    assert meta.natural_width == 640


def test_get_photo_metadata_404(tmp_pure: Path) -> None:
    from pick_face.service.photo_service import PhotoNotFoundError, PhotoService

    layout = _layout(tmp_pure)
    with pytest.raises(PhotoNotFoundError):
        PhotoService(layout).get_photo_metadata(999)


# ---------------------------------------------------------------------------
# M7.6 — EXIF extraction (pick_face.service.photo_service.ExifRecord)
# ---------------------------------------------------------------------------


def test_get_exif_full_payload(tmp_pure: Path) -> None:
    """All common tags: make, model, taken_at, lens, exposure, ISO,
    focal length, GPS."""
    from pick_face.service.photo_service import ExifRecord, PhotoService

    layout = _layout(tmp_pure)
    p = tmp_pure / "p.jpg"
    _make_jpg_with_exif(
        p,
        make="Canon",
        model="EOS R6",
        taken_at="2024:06:15 14:30:00",
        lens="RF 50mm F1.2 L USM",
        exposure=(1, 200),
        f_number=(28, 10),       # f/2.8
        iso=400,
        focal_length=(50, 1),    # 50mm
        gps_lat=(37, 30, 0),
        gps_lon=(122, 5, 0),
    )
    pid = _insert_source(layout, p)
    rec = PhotoService(layout).get_exif(pid)
    assert isinstance(rec, ExifRecord)
    assert rec.make == "Canon"
    assert rec.model == "EOS R6"
    assert rec.lens == "RF 50mm F1.2 L USM"
    # Date parsed as epoch seconds — 2024-06-15 14:30:00 UTC.
    import datetime as _dt
    expected_epoch = _dt.datetime(2024, 6, 15, 14, 30, 0, tzinfo=_dt.timezone.utc).timestamp()
    assert rec.taken_at == pytest.approx(expected_epoch, abs=1)
    # Exposure 1/200s = 0.005s
    assert rec.exposure == pytest.approx(1 / 200, abs=1e-6)
    assert rec.f_number == pytest.approx(2.8, abs=1e-6)
    assert rec.iso == 400
    assert rec.focal_length == pytest.approx(50.0)
    # GPS 37°30'00" N + 122°05'00" W → 37.5 / -122.0833
    assert rec.gps_lat == pytest.approx(37.5, abs=1e-3)
    assert rec.gps_lon == pytest.approx(-122 + (-5 / 60), abs=1e-3)


def test_get_exif_no_tags_returns_all_none(tmp_pure: Path) -> None:
    """A plain JPEG (no EXIF) returns an ExifRecord with every field None."""
    from pick_face.service.photo_service import ExifRecord, PhotoService

    layout = _layout(tmp_pure)
    p = tmp_pure / "plain.jpg"
    _make_jpg(p)
    pid = _insert_source(layout, p)
    rec = PhotoService(layout).get_exif(pid)
    assert rec == ExifRecord()


def test_get_exif_partial_tags(tmp_pure: Path) -> None:
    """A photo with only some tags returns just those (the rest stay None)."""
    from pick_face.service.photo_service import PhotoService

    layout = _layout(tmp_pure)
    p = tmp_pure / "partial.jpg"
    _make_jpg_with_exif(
        p,
        make=None, model=None, taken_at=None, lens=None,
        exposure=None, f_number=None, iso=None, focal_length=None,
    )
    pid = _insert_source(layout, p)
    rec = PhotoService(layout).get_exif(pid)
    assert rec.make is None
    assert rec.taken_at is None
    assert rec.exposure is None
    assert rec.gps_lat is None


def test_get_exif_missing_file_returns_all_none(tmp_pure: Path) -> None:
    """Source row exists but the file is gone → silent ExifRecord()."""
    from pick_face.service.photo_service import ExifRecord, PhotoService

    layout = _layout(tmp_pure)
    ghost = tmp_pure / "ghost.jpg"  # never written
    pid = _insert_source(layout, ghost)
    rec = PhotoService(layout).get_exif(pid)
    assert rec == ExifRecord()


def test_get_exif_404(tmp_pure: Path) -> None:
    from pick_face.service.photo_service import PhotoNotFoundError, PhotoService

    layout = _layout(tmp_pure)
    with pytest.raises(PhotoNotFoundError):
        PhotoService(layout).get_exif(999)


def test_get_exif_strips_trailing_nul(tmp_pure: Path) -> None:
    """Some cameras pad make/model with NULs — strip them."""
    from pick_face.service.photo_service import PhotoService

    layout = _layout(tmp_pure)
    p = tmp_pure / "nul.jpg"
    _make_jpg_with_exif(p, make="Canon\x00\x00", model="EOS R6\x00")
    pid = _insert_source(layout, p)
    rec = PhotoService(layout).get_exif(pid)
    assert rec.make == "Canon"
    assert rec.model == "EOS R6"
