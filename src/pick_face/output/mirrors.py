"""Mirror writers: meta.json per cluster + top-level index.json.

Reference:
- docs/05 §5 (output layout: <out>/index.json + <out>/<person-XXXX>/meta.json)
- docs/05 §6 (atomic staging: meta + index are written into staging-<run_id>)
- ADR-009 (SQLite is authoritative; JSON is a grep/debug mirror without embeddings)

Schema discipline:
  - Both files declare a `schema` field so future format changes can be
    detected by readers.
  - meta.json per cluster contains only DB-derived fields. No paths to
    embeddings, no thumbnails (M3 adds thumbs; we leave a placeholder).
  - index.json is the relationship mirror: cluster + link edges, no
    embedding BLOBs (those stay in SQLite).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

META_SCHEMA = "pick-face/meta@1"
INDEX_SCHEMA = "pick-face/index@1"


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def write_cluster_meta(conn: sqlite3.Connection, cluster_id: int, out_dir: Path) -> Path:
    """Write `<out_dir>/meta.json` for a single cluster.

    The cluster_dir is typically `<out>/<label>/` (e.g. `person-0001/`).
    The label is fetched from the DB so the caller doesn't need to know
    it ahead of time.
    """
    row = conn.execute(
        """SELECT id, label, size, mean_sim, created_at, updated_at, merged_into
           FROM cluster WHERE id = ?""",
        (int(cluster_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"cluster id={cluster_id} not in DB")

    # first/last seen come from face joins.
    seen_rows = conn.execute(
        """SELECT MIN(f.id) AS min_id, MAX(f.id) AS max_id,
                  MIN(s.first_seen) AS first_seen, MAX(s.last_seen) AS last_seen
           FROM face f JOIN source s ON s.id = f.source_id
           WHERE f.cluster_id = ?""",
        (int(cluster_id),),
    ).fetchone()

    payload = {
        "schema": META_SCHEMA,
        "schema_version": 1,
        "cluster_id": int(row["id"]),
        "label": str(row["label"]),
        "size": int(row["size"]),
        "mean_sim": float(row["mean_sim"]) if row["mean_sim"] is not None else None,
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "merged_into": int(row["merged_into"]) if row["merged_into"] is not None else None,
        "first_seen": _iso(seen_rows["first_seen"] if seen_rows else None),
        "last_seen": _iso(seen_rows["last_seen"] if seen_rows else None),
        "review_state": "auto",  # placeholder; per-cluster review_state lands in M3
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "meta.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def write_all_cluster_metas(conn: sqlite3.Connection, out_root: Path) -> list[Path]:
    """Write one meta.json per non-merged cluster under <out_root>/<label>/.

    Returns the list of written paths. Clusters whose `merged_into` is set
    are skipped — the merged_into pointer is enough audit trail; their
    old files (if any) get cleaned by `gc`.
    """
    out_root = Path(out_root)
    written: list[Path] = []
    rows = conn.execute(
        "SELECT id, label FROM cluster WHERE merged_into IS NULL ORDER BY id"
    ).fetchall()
    for r in rows:
        cid = int(r["id"])
        label = str(r["label"])
        target = write_cluster_meta(conn, cid, out_root / label)
        written.append(target)
    return written


def write_index_json(conn: sqlite3.Connection, out_dir: Path, *, run_id: str | None = None) -> Path:
    """Write top-level `<out_dir>/index.json` — a mirror of cluster + link.

    Schema (docs/05 §5):
        {
          "schema": "pick-face/index@1",
          "schema_version": 1,
          "run_id": "...",
          "generated_at": "...",
          "totals": { "clusters": N, "persons": N, "links": N, "faces": N,
                      "active_sources": N, "missing_sources": N },
          "clusters": [ {"id": 1, "label": "person-0001", "size": 12,
                          "mean_sim": 0.62, "merged_into": null}, ... ],
          "links": [ {"cluster_id": 1, "source_id": 5, "rel_path": "...",
                       "link_kind": "symlink", "actual_target": "..."}, ... ]
        }

    Embeddings are NEVER included (ADR-009).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rid = run_id or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    generated = datetime.now(tz=timezone.utc).isoformat()

    cluster_rows = conn.execute(
        """SELECT id, label, size, mean_sim, merged_into
           FROM cluster ORDER BY id"""
    ).fetchall()
    link_rows = conn.execute(
        """SELECT cluster_id, source_id, rel_path, link_kind, actual_target
           FROM link"""
    ).fetchall()

    totals = {
        "clusters": int(conn.execute("SELECT COUNT(*) FROM cluster").fetchone()[0]),
        "persons": int(
            conn.execute("SELECT COUNT(*) FROM cluster WHERE merged_into IS NULL").fetchone()[0]
        ),
        "links": int(conn.execute("SELECT COUNT(*) FROM link").fetchone()[0]),
        "faces": int(conn.execute("SELECT COUNT(*) FROM face").fetchone()[0]),
        "active_sources": int(
            conn.execute("SELECT COUNT(*) FROM source WHERE status = 'active'").fetchone()[0]
        ),
        "missing_sources": int(
            conn.execute("SELECT COUNT(*) FROM source WHERE status = 'missing'").fetchone()[0]
        ),
    }

    payload = {
        "schema": INDEX_SCHEMA,
        "schema_version": 1,
        "run_id": rid,
        "generated_at": generated,
        "totals": totals,
        "clusters": [
            {
                "id": int(r["id"]),
                "label": str(r["label"]),
                "size": int(r["size"]),
                "mean_sim": float(r["mean_sim"]) if r["mean_sim"] is not None else None,
                "merged_into": int(r["merged_into"]) if r["merged_into"] is not None else None,
            }
            for r in cluster_rows
        ],
        "links": [
            {
                "cluster_id": int(r["cluster_id"]),
                "source_id": int(r["source_id"]),
                "rel_path": str(r["rel_path"]),
                "link_kind": str(r["link_kind"]),
                "actual_target": str(r["actual_target"])
                if r["actual_target"] is not None
                else None,
            }
            for r in link_rows
        ],
    }
    target = out_dir / "index.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target
