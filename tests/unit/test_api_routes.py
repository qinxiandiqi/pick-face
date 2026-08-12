"""Tests for the FastAPI routers — health, config, scan, persons, photos.

Uses ``TestClient`` to exercise the full app. Per the docs/03 contract,
each test gets a fresh temp ``AppLayout`` via the ``client`` fixture
and a populated v2.x schema where needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def _make_jpg_with_exif(path: Path, **tags) -> None:
    """Same shape as the helper in test_service_photo — keep them in sync."""
    from PIL import ExifTags

    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (640, 480), (10, 20, 30))
    exif = im.getexif()
    if tags.get("make") is not None:
        exif[ExifTags.Base.Make] = tags["make"]
    if tags.get("model") is not None:
        exif[ExifTags.Base.Model] = tags["model"]
    if tags.get("taken_at") is not None:
        exif[ExifTags.Base.DateTimeOriginal] = tags["taken_at"]
    if tags.get("lens") is not None:
        exif[ExifTags.Base.LensModel] = tags["lens"]
    if tags.get("exposure") is not None:
        exif[ExifTags.Base.ExposureTime] = tags["exposure"]
    if tags.get("f_number") is not None:
        exif[ExifTags.Base.FNumber] = tags["f_number"]
    if tags.get("iso") is not None:
        exif[ExifTags.Base.ISOSpeedRatings] = tags["iso"]
    if tags.get("focal_length") is not None:
        exif[ExifTags.Base.FocalLength] = tags["focal_length"]
    if tags.get("gps_lat") is not None and tags.get("gps_lon") is not None:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps[1] = tags.get("gps_lat_ref", "N")
        gps[2] = tags["gps_lat"]
        gps[3] = tags.get("gps_lon_ref", "W")
        gps[4] = tags["gps_lon"]
    im.save(path, "JPEG", exif=exif.tobytes())


@pytest.fixture()
def client(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch):
    """A FastAPI TestClient pointed at a fresh temp layout.

    The app module imports the layout at import time, so we patch
    ``pick_face.api.app.get_layout`` to return the temp layout.
    """
    from fastapi.testclient import TestClient

    layout = _layout(tmp_pure)
    from pick_face.api import app as app_mod
    from pick_face.service import paths as paths_mod

    monkeypatch.setattr(app_mod, "get_layout", lambda: layout)
    monkeypatch.setattr(paths_mod, "get_layout", lambda: layout)
    # The module-level `app` was already built with the old layout;
    # rebuild it now that the monkeypatch is in effect.
    new_app = app_mod.create_app(layout=layout, static_dir=None)
    with TestClient(new_app) as c:
        yield c
    # Reset the module-level default too so other tests aren't affected.
    monkeypatch.undo()
    app_mod.app = app_mod.create_app(layout=layout, static_dir=None)


# -- health -------------------------------------------------------------


def test_health_ok(client) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_includes_layout(client) -> None:
    r = client.get("/api/ready")
    assert r.status_code == 200
    body = r.json()
    assert "layout" in body
    assert body["layout"]["root"]
    assert body["layout"]["config_dir"].endswith("config")


def test_ready_degraded_when_db_missing(client) -> None:
    layout = client.app.state.layout
    layout.db_path.unlink(missing_ok=True)
    r = client.get("/api/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"


# -- config paths --------------------------------------------------------


def test_config_paths_lifecycle(client, tmp_pure: Path) -> None:
    d = tmp_pure / "photos"
    d.mkdir()

    # Initial: empty
    r = client.get("/api/config/paths")
    assert r.status_code == 200
    assert r.json()["paths"] == []

    # Add
    r = client.post("/api/config/paths", json={"path": str(d), "notes": "n1"})
    assert r.status_code == 201
    sp = r.json()
    assert sp["path"] == str(d.resolve())
    pid = sp["id"]

    # List
    r = client.get("/api/config/paths")
    assert len(r.json()["paths"]) == 1

    # Enabled
    r = client.get("/api/config/paths/enabled")
    assert str(d.resolve()) in r.json()["paths"]

    # Toggle
    r = client.patch(f"/api/config/paths/{pid}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = client.get("/api/config/paths/enabled")
    assert str(d.resolve()) not in r.json()["paths"]

    # Remove
    r = client.delete(f"/api/config/paths/{pid}")
    assert r.status_code == 204
    r = client.get("/api/config/paths")
    assert r.json()["paths"] == []


def test_config_paths_add_rejects_traversal(client, tmp_pure: Path) -> None:
    r = client.post(
        "/api/config/paths",
        json={"path": str(tmp_pure / "a" / ".." / "b")},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "PATH_TRAVERSAL"


def test_config_paths_add_rejects_missing(client) -> None:
    r = client.post("/api/config/paths", json={"path": "/nonexistent/path/xyz"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"


def test_config_paths_add_rejects_duplicate(client, tmp_pure: Path) -> None:
    d = tmp_pure / "dup"
    d.mkdir()
    client.post("/api/config/paths", json={"path": str(d)})
    r = client.post("/api/config/paths", json={"path": str(d)})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DUPLICATE"


def test_config_paths_remove_missing(client) -> None:
    r = client.delete("/api/config/paths/9999")
    assert r.status_code == 404


# -- scan jobs -----------------------------------------------------------


def test_scan_jobs_empty(client) -> None:
    r = client.get("/api/scan/jobs")
    assert r.status_code == 200
    assert r.json()["jobs"] == []


def test_scan_jobs_active_none(client) -> None:
    r = client.get("/api/scan/jobs/active")
    assert r.status_code == 200
    assert r.json() is None


def test_scan_start_requires_paths(client) -> None:
    r = client.post("/api/scan/jobs", json={})
    assert r.status_code == 400


def test_scan_start_with_explicit_path(client, tmp_pure: Path) -> None:
    d = tmp_pure / "scan-target"
    d.mkdir()
    r = client.post("/api/scan/jobs", json={"paths": [str(d)], "kind": "full"})
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "queued"
    assert body["kind"] == "full"
    job_id = body["id"]
    # GET by id
    r = client.get(f"/api/scan/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["id"] == job_id
    # PATCH to cancelled
    r = client.patch(f"/api/scan/jobs/{job_id}", json={"target": "cancelled"})
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"


def test_scan_get_missing_job(client) -> None:
    r = client.get("/api/scan/jobs/does-not-exist")
    assert r.status_code == 404


def test_scan_invalid_kind_rejected(client, tmp_pure: Path) -> None:
    d = tmp_pure / "x"
    d.mkdir()
    r = client.post("/api/scan/jobs", json={"paths": [str(d)], "kind": "bogus"})
    assert r.status_code == 422  # pydantic validation


# -- persons -------------------------------------------------------------


def test_persons_empty(client) -> None:
    r = client.get("/api/persons")
    assert r.status_code == 200
    body = r.json()
    assert body["persons"] == []
    assert body["count"] == 0


def test_persons_count_endpoint(client) -> None:
    r = client.get("/api/persons/count")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


def test_person_404_for_missing(client) -> None:
    r = client.get("/api/persons/9999")
    assert r.status_code == 404


def test_person_cover_404_for_missing(client) -> None:
    r = client.get("/api/persons/9999/cover")
    assert r.status_code == 404


# -- photos --------------------------------------------------------------


def test_photo_404(client) -> None:
    r = client.get("/api/photos/9999")
    assert r.status_code == 404


def test_photo_meta_404(client) -> None:
    r = client.get("/api/photos/9999/meta")
    assert r.status_code == 404


def test_photo_meta_includes_faces(client, tmp_pure: Path) -> None:
    """M7.5 — /api/photos/{id}/meta returns bbox + cluster_id + scores.

    The SPA viewer overlay (M7-T-6) draws SVG rectangles over the image
    based on this payload. Without faces, the overlay is a no-op (which
    is why this endpoint must *return* faces, not 404 them).
    """
    # Seed a source row + two faces with known bboxes.
    from pick_face.store.index import open_db

    layout = client.app.state.layout
    img_path = tmp_pure / "x.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0fake")  # claimed JPEG bytes
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
        "                  first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, 'ok', 0, 0)",
        (str(img_path), "x.jpg", 12, 1.0, "abc"),
    )
    photo_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  cluster_id, det_score, quality, embedding, model_version) "
        "VALUES (?, 10, 20, 110, 220, 7, 0.93, 0.81, ?, 'test@sha')",
        (photo_id, b"\x00" * 16),
    )
    conn.execute(
        "INSERT INTO face(source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "                  cluster_id, det_score, quality, embedding, model_version) "
        "VALUES (?, 200, 30, 350, 180, NULL, 0.55, 0.40, ?, 'test@sha')",
        (photo_id, b"\x00" * 16),
    )
    conn.commit()
    conn.close()

    r = client.get(f"/api/photos/{photo_id}/meta")
    assert r.status_code == 200, r.text
    j = r.json()
    # Backwards-compat fields still present.
    assert j["id"] == photo_id
    assert j["path"] == str(img_path)
    assert j["mtime"] == 1.0
    assert j["size"] == 12
    assert j["content_hash"] == "abc"
    # New M7.5 fields.
    assert "natural_width" in j
    assert "natural_height" in j
    assert isinstance(j["faces"], list)
    assert len(j["faces"]) == 2
    face_with_cluster = next(f for f in j["faces"] if f["cluster_id"] is not None)
    assert face_with_cluster["bbox"] == [10.0, 20.0, 110.0, 220.0]
    assert face_with_cluster["cluster_id"] == 7
    assert face_with_cluster["det_score"] == 0.93
    assert face_with_cluster["quality"] == 0.81
    face_no_cluster = next(f for f in j["faces"] if f["cluster_id"] is None)
    assert face_no_cluster["bbox"] == [200.0, 30.0, 350.0, 180.0]
    assert face_no_cluster["cluster_id"] is None


def test_photo_meta_empty_faces(client, tmp_pure: Path) -> None:
    """A photo with no faces yet returns faces=[] (not 404)."""
    from pick_face.store.index import open_db

    layout = client.app.state.layout
    img_path = tmp_pure / "y.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0fake")
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
        "                  first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, 'ok', 0, 0)",
        (str(img_path), "y.jpg", 12, 1.0, "def"),
    )
    photo_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    r = client.get(f"/api/photos/{photo_id}/meta")
    assert r.status_code == 200
    assert r.json()["faces"] == []


# ---------------------------------------------------------------------------
# M7.6 — EXIF block in /api/photos/{id}/meta response
# ---------------------------------------------------------------------------


def test_photo_meta_includes_exif_block(client, tmp_pure: Path) -> None:
    """The /meta response carries an ``exif`` dict with the camera /
    GPS / exposure fields populated by the service layer's ``get_exif``."""
    from pick_face.store.index import open_db

    layout = client.app.state.layout
    img_path = tmp_pure / "exif.jpg"
    _make_jpg_with_exif(
        img_path,
        make="Canon",
        model="EOS R6",
        taken_at="2024:06:15 14:30:00",
        lens="RF 50mm F1.2 L USM",
        exposure=(1, 200),
        f_number=(28, 10),
        iso=400,
        focal_length=(50, 1),
        gps_lat=(37, 30, 0),
        gps_lon=(122, 5, 0),
        gps_lat_ref="N",
        gps_lon_ref="W",
    )
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
        "                  first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, 'ok', 0, 0)",
        (str(img_path), "exif.jpg", img_path.stat().st_size, 1.0, "exifhash"),
    )
    photo_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    r = client.get(f"/api/photos/{photo_id}/meta")
    assert r.status_code == 200, r.text
    j = r.json()
    assert "exif" in j
    exif = j["exif"]
    assert exif["make"] == "Canon"
    assert exif["model"] == "EOS R6"
    assert exif["lens"] == "RF 50mm F1.2 L USM"
    assert exif["iso"] == 400
    assert exif["exposure"] == pytest.approx(1 / 200, abs=1e-6)
    assert exif["f_number"] == pytest.approx(2.8, abs=1e-6)
    assert exif["focal_length"] == pytest.approx(50.0)
    assert exif["gps_lat"] == pytest.approx(37.5, abs=1e-3)
    # Longitude is West → negative decimal degrees.
    assert exif["gps_lon"] == pytest.approx(-(122 + 5 / 60), abs=1e-3)
    # taken_at → epoch seconds.
    assert exif["taken_at"] is not None
    assert exif["taken_at"] > 1_700_000_000  # 2024-ish


def test_photo_meta_exif_all_null_when_no_tags(client, tmp_pure: Path) -> None:
    """A photo with no EXIF tags returns exif with every field None
    (not 404 / not absent)."""
    from pick_face.store.index import open_db

    layout = client.app.state.layout
    img_path = tmp_pure / "plain.jpg"
    Image.new("RGB", (640, 480), (1, 2, 3)).save(img_path, "JPEG")
    conn = open_db(layout.db_path)
    cur = conn.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash, status, "
        "                  first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, 'ok', 0, 0)",
        (str(img_path), "plain.jpg", img_path.stat().st_size, 1.0, "plainhash"),
    )
    photo_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    r = client.get(f"/api/photos/{photo_id}/meta")
    assert r.status_code == 200
    exif = r.json()["exif"]
    assert exif == {
        "make": None,
        "model": None,
        "taken_at": None,
        "lens": None,
        "exposure": None,
        "f_number": None,
        "iso": None,
        "focal_length": None,
        "gps_lat": None,
        "gps_lon": None,
    }
