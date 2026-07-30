"""Tests for pick_face.index: schema bootstrap + idempotency."""

from __future__ import annotations

from pathlib import Path


def test_open_db_creates_schema_on_fresh_db(tmp_pure: Path) -> None:
    from pick_face.index import SCHEMA_VERSION, open_db

    db_path = tmp_pure / ".cache" / "index.sqlite"
    conn = open_db(db_path)

    tables = sorted(
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    )
    # schema_version + the 7 main tables. sqlite_sequence is auto-created
    # on first AUTOINCREMENT insert and may be absent here, so we only
    # assert our 8 names are a subset.
    required = sorted(
        [
            "cluster", "error_log", "face", "link",
            "review_decision", "run", "schema_version", "source",
        ]
    )
    for t in required:
        assert t in tables, f"missing table: {t}"

    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    conn.close()


def test_open_db_is_idempotent(tmp_pure: Path) -> None:
    """Re-opening an existing DB must not crash and must not bump version."""
    from pick_face.index import SCHEMA_VERSION, open_db

    db_path = tmp_pure / ".cache" / "index.sqlite"
    open_db(db_path).close()
    open_db(db_path).close()
    conn = open_db(db_path)
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    conn.close()


def test_open_db_insert_and_read_back_source(tmp_pure: Path) -> None:
    from pick_face.index import open_db

    db_path = tmp_pure / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    with conn:
        conn.execute(
            """INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, 'active', 0, 0)""",
            ("C:/x/a.jpg", "a.jpg", 100, 12345.0, "abcd" * 4),
        )
    rows = conn.execute("SELECT path, size, hash FROM source").fetchall()
    assert len(rows) == 1
    assert rows[0]["path"] == "C:/x/a.jpg"
    assert rows[0]["hash"] == "abcd" * 4
    conn.close()
