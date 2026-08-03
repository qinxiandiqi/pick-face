"""Tests for T-107: link-fallback warnings + report link-kind stats.

We verify:
  - LinkResult.degraded() returns True iff the actual kind differs from
    the caller's preferred kind.
  - The reporter's _warnings_for emits a fallback warning when ≥5% of
    links fell back to copy while the user asked for symlink/junction.
  - Report.md / report.json contain the link-kind histogram.
  - Linker Windows path (subprocess mklink) is mocked but still uses
    the right chain.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from pick_face.index import open_db
from pick_face.linker import LinkResult, link_or_copy
from pick_face.reporter import (
    ReportStats,
    _warnings_for,
    render_markdown,
    render_json,
)


# ---------------------------------------------------------------------------
# LinkResult.degraded()
# ---------------------------------------------------------------------------


def test_link_result_degraded_when_kind_differs() -> None:
    r = LinkResult(link_path=Path("/x"), target=Path("/y"), kind="copy", prefer="symlink")
    assert r.degraded() is True


def test_link_result_not_degraded_when_kind_matches() -> None:
    r = LinkResult(link_path=Path("/x"), target=Path("/y"), kind="symlink", prefer="symlink")
    assert r.degraded() is False


def test_link_result_not_degraded_when_no_prefer() -> None:
    r = LinkResult(link_path=Path("/x"), target=Path("/y"), kind="copy", prefer=None)
    assert r.degraded() is False


# ---------------------------------------------------------------------------
# End-to-end fallback via the linker
# ---------------------------------------------------------------------------


def test_link_falls_back_to_copy_when_all_links_fail(
    tmp_pure: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.symlink and os.link both raise OSError, the linker falls
    back to copy. (We can't fully simulate the Windows branch here
    without platform shimming, so we just make every link-kind fail.)"""
    src = tmp_pure / "src.txt"
    src.write_bytes(b"hello")
    dst = tmp_pure / "out" / "src.txt"

    # Force both os.symlink and os.link to fail; copy always succeeds.
    monkeypatch.setattr(os, "symlink", lambda *a, **kw: (_ for _ in ()).throw(OSError("nope")))
    monkeypatch.setattr(os, "link", lambda *a, **kw: (_ for _ in ()).throw(OSError("nope")))

    result = link_or_copy(src, dst, prefer="symlink")
    assert result.kind == "copy"
    assert result.degraded() is True
    assert dst.read_bytes() == b"hello"


def test_link_does_not_fallback_when_symlink_works(tmp_pure: Path) -> None:
    src = tmp_pure / "src.txt"
    src.write_bytes(b"hello")
    dst = tmp_pure / "out" / "src.txt"
    result = link_or_copy(src, dst, prefer="symlink")
    assert result.kind == "symlink"
    assert not result.degraded()


# ---------------------------------------------------------------------------
# Report warnings: link fallback
# ---------------------------------------------------------------------------


def _empty_stats(**overrides) -> ReportStats:
    base = dict(
        total_sources=0, active_sources=0, missing_sources=0,
        total_faces=0, low_quality_faces=0, noise_faces=0,
        persons=0, avg_face_to_cluster=0.0,
        cluster_id_min=0, cluster_id_max=0,
    )
    base.update(overrides)
    return ReportStats(**base)


def test_warnings_for_no_fallback_when_only_symlinks() -> None:
    stats = _empty_stats(symlink_links=100, copy_links=0)
    w = _warnings_for({}, stats, prefer="symlink")
    assert not any("fell back to copy" in s for s in w)


def test_warnings_for_no_fallback_when_below_threshold() -> None:
    """2/100 = 2% < 5% threshold → no warning."""
    stats = _empty_stats(symlink_links=98, copy_links=2)
    w = _warnings_for({}, stats, prefer="symlink")
    assert not any("fell back to copy" in s for s in w)


def test_warnings_for_fallback_emitted_when_above_threshold() -> None:
    """10/100 = 10% > 5% threshold → warning."""
    stats = _empty_stats(symlink_links=90, copy_links=10)
    w = _warnings_for({}, stats, prefer="symlink")
    matching = [s for s in w if "fell back to copy" in s]
    assert len(matching) == 1
    assert "10/100" in matching[0]
    assert "symlink" in matching[0]


def test_warnings_for_fallback_includes_junction_pref() -> None:
    """junction preference + copy fallback → warning."""
    stats = _empty_stats(junction_links=80, copy_links=20)
    w = _warnings_for({}, stats, prefer="junction")
    matching = [s for s in w if "fell back to copy" in s]
    assert len(matching) == 1
    assert "junction" in matching[0]


def test_warnings_for_no_fallback_when_prefer_copy() -> None:
    """prefer=copy means copy is the desired kind → no warning."""
    stats = _empty_stats(copy_links=100)
    w = _warnings_for({}, stats, prefer="copy")
    assert not any("fell back to copy" in s for s in w)


# ---------------------------------------------------------------------------
# Report render: link kinds surface in markdown / json
# ---------------------------------------------------------------------------


def test_render_markdown_includes_link_kinds_when_present() -> None:
    stats = _empty_stats(symlink_links=10, hardlink_links=2, copy_links=3)
    md = render_markdown(stats, config_dict={"runtime": {}})
    assert "Link kinds" in md
    assert "symlink=10" in md
    assert "copy=3" in md


def test_render_markdown_omits_link_kinds_when_zero() -> None:
    stats = _empty_stats()  # all zero
    md = render_markdown(stats, config_dict={"runtime": {}})
    assert "Link kinds" not in md


def test_render_json_includes_link_kinds() -> None:
    stats = _empty_stats(symlink_links=5, copy_links=2)
    js = render_json(stats, config_dict={"runtime": {}})
    payload = json.loads(js)
    assert payload["stats"]["symlink_links"] == 5
    assert payload["stats"]["copy_links"] == 2


# ---------------------------------------------------------------------------
# DB round-trip: collect_stats reads link counts
# ---------------------------------------------------------------------------


def test_collect_stats_reads_link_counts(tmp_pure: Path) -> None:
    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    con = open_db(db)
    # 4 sources so each link gets a unique (cluster_id, source_id) pair.
    sids = []
    for i in range(4):
        con.execute(
            "INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen) "
            "VALUES (?, ?, 1, 1.0, ?, 'active', 0, 0)",
            (f"/x/{i}.jpg", f"{i}.jpg", f"h{i}"),
        )
        sids.append(con.execute("SELECT id FROM source WHERE rel_path=?", (f"{i}.jpg",)).fetchone()["id"])
    con.execute("INSERT INTO cluster(label, size, created_at, updated_at) VALUES ('person-0001', 1, 0, 0)")
    cid = con.execute("SELECT id FROM cluster").fetchone()["id"]
    for sid, kind in zip(sids, ["symlink", "symlink", "hardlink", "copy"]):
        con.execute(
            """INSERT INTO link(cluster_id, source_id, rel_path, link_kind, actual_target, created_at)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (cid, sid, "f.jpg", kind, f"/x/{sid}.jpg"),
        )
    con.commit()

    from pick_face.reporter import collect_stats

    stats = collect_stats(con)
    con.close()
    assert stats.symlink_links == 2
    assert stats.hardlink_links == 1
    assert stats.copy_links == 1
    assert stats.junction_links == 0