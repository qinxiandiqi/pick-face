"""SQLite schema, PRAGMAs, and versioned migrations.

Reference:
- docs/05 §2 (PRAGMA + schema_migrations + 主表)
- docs/08 §6.4 (face 表已增 embedding BLOB / model_version TEXT / norm REAL)
- ADR-009 (SQLite 唯一权威)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1  # 当前 schema 版本号 (bump on every migration)

# Valid values for `source.status`. M6 shipped `active` and `missing` (file
# vanished from disk). M8 adds `removed` for user-driven soft-delete via
# `DELETE /api/photos/{id}` (`docs/06 §3.1 M8-T-6`).
#
# The column has no CHECK constraint, so this is enforced at the write
# sites (`_mark_missing`, `_mark_removed`, the scan DEL pass). Existing
# DBs with `status='active'` rows continue to work — new soft-delete
# operations simply transition active → removed.
VALID_SOURCE_STATUSES: frozenset[str] = frozenset({"active", "missing", "removed"})

# Default status applied to newly-discovered sources by `run_scan`.
DEFAULT_SOURCE_STATUS = "active"

# PRAGMAs applied on every connection open.
# Reference: docs/05 §2.1.
PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode = WAL",  # 并发读 / 单写
    "PRAGMA synchronous  = NORMAL",  # WAL 下可放宽
    "PRAGMA foreign_keys = ON",  # 启用外键
    "PRAGMA temp_store    = MEMORY",
    "PRAGMA mmap_size     = 268435456",  # 256 MB
)

# Init schema for schema_version=1.
# After 08 §6.4 amendment, face table includes embedding / model_version / norm.
SCHEMA_V1_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER PRIMARY KEY,
        applied_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source (
        id          INTEGER PRIMARY KEY,
        path        TEXT NOT NULL UNIQUE,    -- 绝对路径
        rel_path    TEXT NOT NULL,           -- 相对第一个 src root 的路径
        size        INTEGER NOT NULL,
        mtime       REAL NOT NULL,
        hash_algo   TEXT NOT NULL DEFAULT 'xxh3_64',
        hash        TEXT NOT NULL,           -- 16 chars (xxh3_64)
        status      TEXT NOT NULL,           -- active / missing
        first_seen  REAL NOT NULL,
        last_seen   REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_source_hash   ON source(hash)",
    "CREATE INDEX IF NOT EXISTS idx_source_status ON source(status)",
    """
    CREATE TABLE IF NOT EXISTS face (
        id            INTEGER PRIMARY KEY,
        source_id     INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
        bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL,
        det_score     REAL,
        lmk_x0 REAL, lmk_y0 REAL, lmk_x1 REAL, lmk_y1 REAL, lmk_x2 REAL,
        lmk_y2 REAL, lmk_x3 REAL, lmk_y3 REAL, lmk_x4 REAL, lmk_y4 REAL,
        quality       REAL,
        cluster_id    INTEGER,                    -- 当前聚类 ID (NULL=未分配/噪声)
        cluster_prob  REAL,
        low_quality   INTEGER NOT NULL DEFAULT 0,
        review_state  TEXT NOT NULL DEFAULT 'auto',  -- auto / confirmed / removed
        -- ====== 实施关键字段 (10 §5 / 09 §6 / 05 §3 HNSW 重建) ======
        embedding     BLOB NOT NULL,             -- 512 维 float32 = 2048 bytes
        model_version TEXT NOT NULL,             -- e.g. "buffalo_l@2023-11"
        norm          REAL                       -- 可选: MagFace 范数信号 (10 §2.3)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_face_source    ON face(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_face_cluster   ON face(cluster_id)",
    "CREATE INDEX IF NOT EXISTS idx_face_model     ON face(model_version)",  # 升级过滤
    """
    CREATE TABLE IF NOT EXISTS cluster (
        id           INTEGER PRIMARY KEY,        -- 1..N, 与 person-XXXX 对应
        label        TEXT UNIQUE NOT NULL,       -- 'person-0001'
        size         INTEGER NOT NULL,
        mean_sim     REAL,
        merged_into  INTEGER REFERENCES cluster(id),  -- 二级合并后留痕
        created_at   REAL NOT NULL,
        updated_at   REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_decision (
        id          INTEGER PRIMARY KEY,
        kind        TEXT NOT NULL,              -- must_link / cannot_link / remove / rename
        face_a      INTEGER REFERENCES face(id) ON DELETE CASCADE,
        face_b      INTEGER REFERENCES face(id) ON DELETE CASCADE,    -- must/cannot_link
        cluster_id  INTEGER REFERENCES cluster(id) ON DELETE CASCADE, -- rename
        payload     TEXT,                       -- JSON 扩展
        created_at  REAL NOT NULL,
        applied_at  REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_review_kind ON review_decision(kind)",
    """
    CREATE TABLE IF NOT EXISTS link (
        id            INTEGER PRIMARY KEY,
        cluster_id    INTEGER NOT NULL REFERENCES cluster(id) ON DELETE CASCADE,
        source_id     INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
        rel_path      TEXT NOT NULL,                 -- 相对 cluster 目录的路径
        link_kind     TEXT NOT NULL,                 -- symlink/hardlink/junction/copy
        actual_target TEXT,                          -- 解析后的目标 (用于 GC)
        created_at    REAL NOT NULL,
        UNIQUE(cluster_id, source_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_link_cluster ON link(cluster_id)",
    "CREATE INDEX IF NOT EXISTS idx_link_source  ON link(source_id)",
    """
    CREATE TABLE IF NOT EXISTS run (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at   REAL NOT NULL,
        finished_at  REAL,                          -- NULL = interrupted
        mode         TEXT NOT NULL,                 -- full / incremental / rebuild
        config_hash  TEXT NOT NULL,
        stats_json   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS error_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      INTEGER REFERENCES run(id) ON DELETE CASCADE,
        ts          REAL NOT NULL,
        path        TEXT,
        stage       TEXT NOT NULL,                  -- scan / decode / detect / embed / cluster / link
        kind        TEXT NOT NULL,                  -- exception class name
        message     TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_error_run ON error_log(run_id)",
)


def open_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database at *path* and apply all PRAGMAs.

    Caller is responsible for closing; use as context manager if convenient.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all v1 tables if they do not exist; record schema_version=1.

    We must CREATE the tables before SELECTing from them. The schema check
    therefore runs twice on a fresh DB (once the CREATE TABLE IF NOT EXISTS
    rows have created the `schema_version` table, then a SELECT to see
    whether v1 has already been recorded). On subsequent runs (>= v1),
    CREATE IF NOT EXISTS is a no-op and we re-read MAX(version) to skip the
    re-insert.
    """
    # First pass: ensure all tables exist (idempotent).
    with conn:
        for sql in SCHEMA_V1_SQL:
            conn.execute(sql)

    # Second pass: record the schema version exactly once.
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cur.fetchone()
    current = row[0] if row and row[0] is not None else 0
    if current < SCHEMA_VERSION:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _now()),
            )


def _now() -> float:
    """Monotonic-clock-ish; in seconds."""
    import time

    return time.time()
