"""Tests for pick_face.reporter.

Exercises the docs/11 §3.4 top-line header (Model + License + Accepted-by)
plus the stats/legend rendering. We don't render via SQLite against a real
DB here; instead we use the in-memory DB built by open_db() and assert
that the rendered markdown contains every required field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pick_face.config import PickFaceConfig
from pick_face.index import open_db
from pick_face.reporter import collect_stats, render_json, render_markdown, write_report


@pytest.fixture()
def populated_db(tmp_pure: Path):
    """An open SQLite with 3 sources, 5 faces across 2 clusters, 1 noise face."""
    db_path = tmp_pure / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    import time

    now = time.time()
    sources = [
        ("C:/x/a.jpg", "a.jpg", 100, 1.0, "a1", "active"),
        ("C:/x/b.png", "b.png", 200, 2.0, "b2", "active"),
        ("C:/x/c.jpg", "c.jpg", 300, 3.0, "c3", "missing"),
    ]
    for path, rel, size, mtime, h, status in sources:
        conn.execute(
            """INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (path, rel, size, mtime, h, status, now, now),
        )
    clusters = []
    for i in range(2):
        cur = conn.execute(
            "INSERT INTO cluster(label, size, mean_sim, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (f"person-{i + 1:04d}", 0, 0.7, now, now),
        )
        clusters.append(int(cur.lastrowid))

    embeddings = [b"\x00\x01" * 1024] * 6  # 6 faces × 2048 bytes
    face_assign = [clusters[0], clusters[0], clusters[0], clusters[1], clusters[1], None]
    for i, (e, cid) in enumerate(zip(embeddings, face_assign)):
        conn.execute(
            """INSERT INTO face(
                source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2, det_score,
                embedding, model_version, norm, low_quality, cluster_id
            ) VALUES (?, 0, 0, 10, 10, 0.9, ?, 'test@0', 1.0, ?, ?)""",
            ((i % 3) + 1, e, 0, cid),
        )
    # Mark one face low-quality.
    conn.execute("UPDATE face SET low_quality = 1 WHERE id = 1")
    conn.commit()
    yield conn
    conn.close()


def test_collect_stats_counts(populated_db) -> None:
    s = collect_stats(populated_db)
    assert s.total_sources == 3
    assert s.active_sources == 2
    assert s.missing_sources == 1
    assert s.total_faces == 6
    assert s.low_quality_faces == 1
    assert s.noise_faces == 1
    assert s.persons == 2


def test_render_markdown_top_header(populated_db) -> None:
    cfg = PickFaceConfig()  # default: buffalo_l, license=false
    body = render_markdown(
        collect_stats(populated_db),
        config_dict=_config_dict(cfg),
        run_id="2026-07-30T00-00-00Z",
        warnings=(
            "Model `buffalo_l` is non-commercial-research-licensed. Set "
            "`[runtime] accept_noncommercial_model_license = true` "
            "(only if your use case qualifies).",
            "Provider=auto; on Windows, this probes DirectML → CPU in that order.",
        ),
    )
    # Per docs/11 §3.4 every audit field must be in the header.
    assert "**Run ID**" in body
    assert "**Model**" in body and "`buffalo_l`" in body
    assert "**Model License**" in body
    assert "**License Accepted**" in body
    assert "**Provider**" in body
    assert "2026-07-30T00-00-00Z" in body
    # And the Warning + License Notice sections are present.
    assert "⚠ Warnings" in body
    assert "License Notice" in body
    # The fact that user has not accepted the license → strong warning text.
    assert "non-commercial" in body.lower()


def test_render_markdown_no_warnings_omits_section(populated_db) -> None:
    cfg = PickFaceConfig(runtime={"provider": "cpu"})
    body = render_markdown(
        collect_stats(populated_db),
        config_dict=_config_dict(cfg),
    )
    # No warnings supplied → no Warnings heading.
    assert "⚠ Warnings" not in body
    # License Notice is always present.
    assert "License Notice" in body


def test_render_markdown_with_alternative_model_is_clean(populated_db) -> None:
    cfg = PickFaceConfig(runtime={"model_name": "arcface_webface4m"})
    body = render_markdown(
        collect_stats(populated_db),
        config_dict=_config_dict(cfg),
    )
    # No non-commercial warning for a non-InsightFace model.
    assert "custom" in body.lower()
    # The License Notice should be the "no commercial restriction" form.
    assert "no commercial restriction" in body.lower()


def test_render_json_shape(populated_db) -> None:
    cfg = PickFaceConfig()
    s = collect_stats(populated_db)
    j = render_json(s, config_dict=_config_dict(cfg), run_id="Z")
    parsed = json.loads(j)
    assert parsed["run_id"] == "Z"
    assert parsed["model"]["name"] == "buffalo_l"
    assert "InsightFace" in parsed["model"]["license"]
    assert parsed["model"]["license_accepted"] is False
    assert parsed["stats"]["total_faces"] == 6
    assert parsed["stats"]["persons"] == 2
    assert "warnings" in parsed


def test_write_report_populates_file(populated_db, tmp_pure: Path) -> None:
    target = write_report(
        populated_db,
        out_dir=tmp_pure,
        config_dict=_config_dict(PickFaceConfig()),
        fmt="md",
    )
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# pick-face Report")


def test_write_report_json_renders_to_json(populated_db, tmp_pure: Path) -> None:
    target = write_report(
        populated_db,
        out_dir=tmp_pure,
        config_dict=_config_dict(PickFaceConfig()),
        fmt="json",
    )
    assert target.name == "report.json"
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert "persons" in parsed


def test_write_report_rejects_unknown_fmt(populated_db, tmp_pure: Path) -> None:
    with pytest.raises(ValueError):
        write_report(
            populated_db, out_dir=tmp_pure, config_dict=_config_dict(PickFaceConfig()), fmt="xml"
        )


def test_warnings_for_acknowledged_compliance(populated_db) -> None:
    from pick_face.reporter import _warnings_for

    cfg = PickFaceConfig(runtime={"accept_noncommercial_model_license": True})
    d = _config_dict(cfg)
    msgs = _warnings_for(d["runtime"], collect_stats(populated_db))
    # With acknowledgment on, no non-commercial warning.
    assert not any("non-commercial-research" in m for m in msgs)


def test_render_markdown_includes_accepted_by_when_ack_present(
    populated_db, tmp_pure: Path
) -> None:
    from pick_face.models import write_license_ack

    model_dir = tmp_pure / "models" / "buffalo_l"
    write_license_ack(model_dir, "buffalo_l", acked_by="alice")
    cfg = PickFaceConfig(
        runtime={
            "model_name": "buffalo_l",
            "accept_noncommercial_model_license": True,
            "model_dir": tmp_pure / "models",
        }
    )
    body = render_markdown(
        collect_stats(populated_db),
        config_dict=_config_dict(cfg),
        ack_summary='user "alice" on 2026-07-30 (see `.cache/buffalo_l/.license_ack`)',
    )
    assert "**Accepted by**" in body
    assert "alice" in body


def test_render_json_includes_accepted_by(populated_db) -> None:
    cfg = PickFaceConfig()
    s = collect_stats(populated_db)
    j = render_json(
        s,
        config_dict=_config_dict(cfg),
        ack_summary='user "bob" on 2026-07-30',
    )
    parsed = json.loads(j)
    assert parsed["model"]["accepted_by"] == 'user "bob" on 2026-07-30'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config_dict(cfg: PickFaceConfig) -> dict:
    """Convert a Pydantic PickFaceConfig into a plain dict whose nested
    'model_dir' is JSON-safe (Path → str). The reporter runs from JSON-able
    config to keep markdown output serializable."""
    import json as _json

    raw = cfg.model_dump(mode="json")
    return _json.loads(_json.dumps(raw))
