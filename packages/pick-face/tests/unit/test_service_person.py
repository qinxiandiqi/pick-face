"""Tests for service/person_service.py — virtual album (cluster) read API."""

from __future__ import annotations

from pathlib import Path


def _layout(tmp_pure: Path):
    from pick_face.service.paths import get_layout

    return get_layout(data_dir=tmp_pure / "app")


def _seed_db(tmp_pure: Path):
    """Insert a handful of clusters/faces/sources for the read tests."""
    from pick_face.store.index import open_db

    db_path = _layout(tmp_pure).db_path
    conn = open_db(db_path)
    cur = conn.cursor()
    # Three sources (photos)
    cur.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (str(tmp_pure / "a.jpg"), "a.jpg", 1, 1.0, "xxh3_64", "h1", "active", 1.0, 1.0),
    )
    cur.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (str(tmp_pure / "b.jpg"), "b.jpg", 1, 2.0, "xxh3_64", "h2", "active", 2.0, 2.0),
    )
    cur.execute(
        "INSERT INTO source(path, rel_path, size, mtime, hash_algo, hash, status, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (str(tmp_pure / "c.jpg"), "c.jpg", 1, 3.0, "xxh3_64", "h3", "active", 3.0, 3.0),
    )
    # Two clusters: id=1 has 3 faces, id=2 has 1 face, id=3 is merged into 1
    cur.execute("INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('Alice', 3, 1.0, 1.0)")
    cur.execute("INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('Bob', 1, 1.0, 1.0)")
    cur.execute(
        "INSERT INTO cluster(label, size, merged_into, created_at, updated_at) "
        "VALUES ('Alice-merged', 0, 1, 1.0, 1.0)"
    )
    # 3 faces in cluster 1, 1 face in cluster 2
    faces = [
        (1, 1, 0, 0, 50, 50, 0.9, 0.9, 0.95, 0.1, 0.1, 0.5, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, b"e1", "v1"),
        (2, 1, 0, 0, 60, 60, 0.9, 0.9, 0.95, 0.1, 0.1, 0.5, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, b"e2", "v1"),
        (3, 1, 0, 0, 70, 70, 0.9, 0.9, 0.95, 0.1, 0.1, 0.5, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, b"e3", "v1"),
        (2, 2, 0, 0, 80, 80, 0.9, 0.9, 0.95, 0.1, 0.1, 0.5, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, b"e4", "v1"),
    ]
    for f in faces:
        cur.execute(
            "INSERT INTO face(source_id, cluster_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, det_score, "
            "lmk_x0, lmk_y0, lmk_x1, lmk_y1, lmk_x2, lmk_y2, lmk_x3, lmk_y3, lmk_x4, lmk_y4, "
            "quality, embedding, model_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            f,
        )
    conn.commit()
    conn.close()
    return db_path


def test_list_persons_orders_by_face_count(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    persons = svc.list_persons()
    # Two non-merged clusters; Alice has 3 faces, Bob has 1.
    assert len(persons) == 2
    assert persons[0].label == "Alice"
    assert persons[0].face_count == 3
    assert persons[1].label == "Bob"
    assert persons[1].face_count == 1


def test_list_persons_merged_clusters_excluded(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    persons = svc.list_persons()
    labels = {p.label for p in persons}
    assert "Alice-merged" not in labels


def test_count_persons(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    assert svc.count_persons() == 2


def test_get_person_returns_sources(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    detail = svc.get_person(1)
    assert detail is not None
    assert detail.label == "Alice"
    assert detail.face_count == 3
    assert detail.photo_count == 3
    assert len(detail.sources) == 3


def test_get_person_returns_none_for_missing(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    assert svc.get_person(999) is None


def test_get_person_photos_distinct(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    photos = svc.get_person_photos(1)
    assert len(photos) == 3
    assert {p["path"] for p in photos} == {
        str(tmp_pure / "a.jpg"),
        str(tmp_pure / "b.jpg"),
        str(tmp_pure / "c.jpg"),
    }


def test_get_person_photos_pagination(tmp_pure: Path) -> None:
    _seed_db(tmp_pure)
    from pick_face.service.person_service import PersonService

    svc = PersonService(_layout(tmp_pure))
    page1 = svc.get_person_photos(1, limit=2, offset=0)
    page2 = svc.get_person_photos(1, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert {p["photo_id"] for p in page1}.isdisjoint({p["photo_id"] for p in page2})


def test_get_person_cover_prefers_highest_quality(tmp_pure: Path) -> None:
    """Cover = highest quality → det_score → bbox area (docs/01 §1.3 AC-5)."""
    from pick_face.store.index import open_db

    layout = _layout(tmp_pure)
    _seed_db(tmp_pure)
    conn = open_db(layout.db_path)
    # Mutate qualities: face on source c.jpg (id=3) should win
    conn.execute("UPDATE face SET quality = 0.99, det_score = 0.5, "
                 "bbox_x1=0, bbox_y1=0, bbox_x2=10, bbox_y2=10 "
                 "WHERE source_id = 1")
    conn.commit()
    conn.close()
    from pick_face.service.person_service import PersonService

    svc = PersonService(layout)
    cover = svc.get_person_cover(1)
    assert cover is not None
    path, face_id = cover
    # Should pick the high-quality face on a.jpg (source 1)
    assert path == tmp_pure / "a.jpg"


def test_get_person_cover_tiebreak_by_det_score(tmp_pure: Path) -> None:
    from pick_face.store.index import open_db

    layout = _layout(tmp_pure)
    _seed_db(tmp_pure)
    conn = open_db(layout.db_path)
    # Equalize quality across all faces, then bump one to high det_score.
    conn.execute("UPDATE face SET quality = 0.5, det_score = 0.5")
    conn.execute("UPDATE face SET det_score = 0.99 WHERE source_id = 2")
    conn.commit()
    conn.close()
    from pick_face.service.person_service import PersonService

    svc = PersonService(layout)
    cover = svc.get_person_cover(1)
    assert cover[0] == tmp_pure / "b.jpg"


def test_get_person_cover_tiebreak_by_bbox_area(tmp_pure: Path) -> None:
    from pick_face.store.index import open_db

    layout = _layout(tmp_pure)
    _seed_db(tmp_pure)
    conn = open_db(layout.db_path)
    # Equalize quality + det_score; ensure the largest bbox wins.
    conn.execute("UPDATE face SET quality = 0.5, det_score = 0.5")
    conn.execute(
        "UPDATE face SET bbox_x1=0, bbox_y1=0, bbox_x2=200, bbox_y2=200 "
        "WHERE source_id = 3"
    )
    conn.commit()
    conn.close()
    from pick_face.service.person_service import PersonService

    svc = PersonService(layout)
    cover = svc.get_person_cover(1)
    assert cover[0] == tmp_pure / "c.jpg"


def test_get_person_cover_returns_none_for_empty_cluster(tmp_pure: Path) -> None:
    from pick_face.store.index import open_db

    layout = _layout(tmp_pure)
    conn = open_db(layout.db_path)
    conn.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) "
        "VALUES ('Empty', 0, 1.0, 1.0)"
    )
    conn.commit()
    conn.close()
    from pick_face.service.person_service import PersonService

    svc = PersonService(layout)
    cluster_id_row = open_db(layout.db_path).execute(
        "SELECT id FROM cluster WHERE label = 'Empty'"
    ).fetchone()
    assert svc.get_person_cover(cluster_id_row[0]) is None
