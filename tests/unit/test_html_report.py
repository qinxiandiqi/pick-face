"""Tests for the HTML report renderer (M4 / T-301)."""

from __future__ import annotations

from pick_face.reporter import (
    ReportStats,
    render_html,
    write_report,
)


def _empty_stats(**overrides) -> ReportStats:
    base = dict(
        total_sources=0, active_sources=0, missing_sources=0,
        total_faces=0, low_quality_faces=0, noise_faces=0,
        persons=0, avg_face_to_cluster=0.0,
        cluster_id_min=0, cluster_id_max=0,
    )
    base.update(overrides)
    return ReportStats(**base)


def test_html_basic_structure() -> None:
    stats = _empty_stats()
    html = render_html(stats, config_dict={"runtime": {}})
    assert html.startswith("<!doctype html>")
    assert "<html" in html
    assert "</html>" in html
    assert "pick-face Report" in html


def test_html_contains_run_id() -> None:
    stats = _empty_stats()
    html = render_html(stats, config_dict={"runtime": {}}, run_id="2026-08-03T12-00-00")
    assert "2026-08-03T12-00-00" in html


def test_html_includes_person_legend() -> None:
    stats = _empty_stats(persons=2)
    legend = ((1, "person-0001", 10), (2, "person-0002", 5))
    html = render_html(stats, config_dict={"runtime": {}}, person_legend=legend)
    assert "person-0001" in html
    assert "person-0002" in html
    # Wall grid is rendered too.
    assert "class=\"wall\"" in html


def test_html_empty_persons_message() -> None:
    stats = _empty_stats()
    html = render_html(stats, config_dict={"runtime": {}})
    assert "(no persons yet" in html


def test_html_warnings_section() -> None:
    stats = _empty_stats()
    html = render_html(
        stats, config_dict={"runtime": {}},
        warnings=("Bad model state", "Disk space low"),
    )
    assert "Bad model state" in html
    assert "Disk space low" in html
    assert "class=\"warnings\"" in html


def test_html_dark_mode_attribute() -> None:
    stats = _empty_stats()
    html_dark = render_html(stats, config_dict={"runtime": {}}, dark_mode=True)
    html_light = render_html(stats, config_dict={"runtime": {}}, dark_mode=False)
    assert 'data-theme="dark"' in html_dark
    assert 'data-theme="light"' in html_light
    # Dark CSS variables are present in dark mode.
    assert "[data-theme=\"dark\"]" in html_dark


def test_html_license_label_insightface() -> None:
    stats = _empty_stats()
    html = render_html(
        stats,
        config_dict={"runtime": {"model_name": "buffalo_l"}},
    )
    assert "non-commercial-research" in html


def test_html_license_label_custom() -> None:
    stats = _empty_stats()
    html = render_html(
        stats,
        config_dict={"runtime": {"model_name": "arcface_r50_webface4m"}},
    )
    assert "custom" in html


def test_html_ack_summary_appears() -> None:
    stats = _empty_stats()
    html = render_html(
        stats, config_dict={"runtime": {}},
        ack_summary="alice@corp 2026-08-03",
    )
    assert "alice@corp 2026-08-03" in html
    assert "Accepted by" in html


def test_html_includes_review_candidates_pointer() -> None:
    stats = _empty_stats()
    html = render_html(stats, config_dict={"runtime": {}})
    assert "low_confidence_faces.json" in html
    assert "review apply" in html


def test_html_link_kinds_appear() -> None:
    stats = _empty_stats(symlink_links=10, copy_links=3)
    html = render_html(stats, config_dict={"runtime": {}})
    assert "Link kinds" in html
    assert "symlink=10" in html


def test_html_self_contained_no_external_resources() -> None:
    """No <link>, <script src=...>, or external URLs in CSS."""
    stats = _empty_stats()
    html = render_html(stats, config_dict={"runtime": {}})
    # Inline styles only.
    assert "<link " not in html
    assert "<script " not in html
    # But inline <style> is fine.
    assert "<style>" in html


def test_write_report_html_format(tmp_pure: Path) -> None:
    """write_report supports fmt='html' (M4 / T-301)."""
    from pick_face.index import open_db

    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    con = open_db(db)
    # Seed one cluster so the legend isn't empty.
    con.execute(
        "INSERT INTO cluster(label, size, created_at, updated_at) "
        "VALUES ('person-0001', 1, 0, 0)"
    )
    con.commit()
    con.close()

    con = open_db(db)
    target = write_report(
        con,
        out_dir=tmp_pure,
        config_dict={"runtime": {"model_name": "buffalo_l"}},
        fmt="html",
    )
    con.close()
    assert target.suffix == ".html"
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert "<!doctype html>" in body
    assert "person-0001" in body


def test_write_report_rejects_unknown_fmt(tmp_pure: Path) -> None:
    from pick_face.index import open_db

    db = tmp_pure / ".cache" / "index.sqlite"
    db.parent.mkdir(parents=True)
    con = open_db(db)
    try:
        with __import__("pytest").raises(ValueError):
            write_report(
                con, out_dir=tmp_pure,
                config_dict={"runtime": {}}, fmt="xml",
            )
    finally:
        con.close()