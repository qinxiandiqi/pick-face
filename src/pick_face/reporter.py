"""Report writer: report.md / report.json with the docs/11 §3.4 top-line
fields (Model + License + Provider + Run ID).

Reference:
- docs/03 §5 step 9 (report content shape: total_sources / total_faces /
  persons / noise_faces / confidence_histogram)
- docs/11 §3.4 (audit-friendly top header including Model + Model License +
  Accepted-by reference)
- docs/05 §6 (warnings section)

We never guess a license: for `model_name` in INSIGHTFACE_MODELS we mark
`non-commercial-research`; for user-supplied model dirs we mark `custom (no
commercial restriction enforced by pick-face)`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pick_face.config import INSIGHTFACE_MODELS


@dataclass(frozen=True)
class ReportStats:
    total_sources: int
    active_sources: int
    missing_sources: int
    total_faces: int
    low_quality_faces: int
    noise_faces: int
    persons: int
    avg_face_to_cluster: float
    cluster_id_min: int
    cluster_id_max: int
    symlink_links: int = 0
    hardlink_links: int = 0
    junction_links: int = 0
    copy_links: int = 0
    link_errors: int = 0


def collect_stats(conn: sqlite3.Connection) -> ReportStats:
    """Pull all numbers from the DB in a single pass where possible."""
    cur = conn.execute(
        """SELECT
            (SELECT COUNT(*) FROM source)              AS total_sources,
            (SELECT COUNT(*) FROM source WHERE status='active')   AS active_sources,
            (SELECT COUNT(*) FROM source WHERE status='missing') AS missing_sources,
            (SELECT COUNT(*) FROM face)                AS total_faces,
            (SELECT COUNT(*) FROM face WHERE low_quality = 1) AS low_quality_faces,
            (SELECT COUNT(*) FROM face WHERE cluster_id IS NULL) AS noise_faces,
            (SELECT COUNT(*) FROM cluster WHERE merged_into IS NULL) AS persons,
            (SELECT MIN(id) FROM cluster)             AS cluster_id_min,
            (SELECT MAX(id) FROM cluster)             AS cluster_id_max"""
    )
    row = cur.fetchone()
    # Mean similarity per cluster, averaged across clusters.
    avg = conn.execute(
        "SELECT AVG(mean_sim) FROM cluster WHERE mean_sim IS NOT NULL AND merged_into IS NULL"
    ).fetchone()[0]
    avg_sim = float(avg) if avg is not None else 0.0

    # Link-kind histogram (T-107): lets the report flag copy-fallback as
    # a warning when the user asked for symlink and we ended up copying.
    link_counts = {"symlink": 0, "hardlink": 0, "junction": 0, "copy": 0}
    for r in conn.execute(
        "SELECT link_kind, COUNT(*) AS c FROM link GROUP BY link_kind"
    ).fetchall():
        kind = str(r["link_kind"])
        link_counts[kind] = int(r["c"]) if kind in link_counts else 0

    return ReportStats(
        total_sources=int(row["total_sources"] or 0),
        active_sources=int(row["active_sources"] or 0),
        missing_sources=int(row["missing_sources"] or 0),
        total_faces=int(row["total_faces"] or 0),
        low_quality_faces=int(row["low_quality_faces"] or 0),
        noise_faces=int(row["noise_faces"] or 0),
        persons=int(row["persons"] or 0),
        avg_face_to_cluster=avg_sim,
        cluster_id_min=int(row["cluster_id_min"] or 0),
        cluster_id_max=int(row["cluster_id_max"] or 0),
        symlink_links=link_counts["symlink"],
        hardlink_links=link_counts["hardlink"],
        junction_links=link_counts["junction"],
        copy_links=link_counts["copy"],
    )


def render_markdown(
    stats: ReportStats,
    *,
    config_dict: dict,
    run_id: str | None = None,
    warnings: tuple[str, ...] = (),
    person_legend: tuple[tuple[int, str, int], ...] = (),
    ack_summary: str | None = None,
) -> str:
    """Render the report.md body. The header is the docs/11 §3.4 audit row."""
    rid = run_id or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    model_name = config_dict.get("runtime", {}).get("model_name", "buffalo_l")
    model_dir = config_dict.get("runtime", {}).get("model_dir", "~/.insightface/models")
    provider = config_dict.get("runtime", {}).get("provider", "auto")
    accepted = bool(config_dict.get("runtime", {}).get("accept_noncommercial_model_license", False))

    license_label = (
        "InsightFace non-commercial-research"
        if model_name in INSIGHTFACE_MODELS
        else "custom (no commercial restriction enforced by pick-face)"
    )

    lines = [
        "# pick-face Report",
        "",
        "## Run",
        "",
        f"- **Run ID**: `{rid}`",
        f"- **Generated**: `{datetime.now(tz=timezone.utc).isoformat()}`",
        f"- **Model**: `{model_name}` (SCRFD-10G detector + ArcFace w600k_r50 embedder)",
        f"- **Model dir**: `{model_dir}`",
        f"- **Model License**: {license_label}",
        f"- **License Accepted**: {'yes' if accepted else 'no (commercial users must self-train, see docs/11)'}",
    ]
    if ack_summary:
        lines.append(f"- **Accepted by**: {ack_summary}")
    lines.append(f"- **Provider**: `{provider}`")
    lines.append("")
    lines.append("## Stats")
    lines.append("")
    lines.append(f"- **Total sources**: {stats.total_sources}")
    lines.append(f"- **Active sources**: {stats.active_sources}")
    lines.append(f"- **Missing sources**: {stats.missing_sources}")
    lines.append(f"- **Total faces**: {stats.total_faces}")
    lines.append(f"- **Low-quality faces**: {stats.low_quality_faces}")
    lines.append(f"- **Noise faces (cluster_id IS NULL)**: {stats.noise_faces}")
    lines.append(f"- **Persons**: {stats.persons}")
    lines.append(f"- **Cluster ID range**: {stats.cluster_id_min}..{stats.cluster_id_max}")
    lines.append(f"- **Avg face-to-centroid similarity**: {stats.avg_face_to_cluster:.3f}")
    total_links = (
        stats.symlink_links + stats.hardlink_links + stats.junction_links + stats.copy_links
    )
    if total_links > 0:
        lines.append(
            f"- **Link kinds**: symlink={stats.symlink_links}, "
            f"hardlink={stats.hardlink_links}, junction={stats.junction_links}, "
            f"copy={stats.copy_links}"
        )
    lines.append("")
    lines.append("## Review candidates")
    lines.append("")
    lines.append(
        "Faces with `cos < clustering.low_confidence` to their cluster "
        "centroid are listed in `low_confidence_faces.json` next to this "
        "report. Use `pick-face review apply` to merge / split / remove "
        "any of them."
    )
    lines.append("")
    lines.append("## Persons")
    lines.append("")
    if person_legend:
        lines.append("| ID | Label | Faces |")
        lines.append("|---:|:---|---:|")
        for cid, label, size in person_legend:
            lines.append(f"| {cid} | `{label}` | {size} |")
    else:
        lines.append("_(No persons yet — run `pick-face cluster`.)_")
    lines.append("")

    if warnings:
        lines.append("## ⚠ Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## License Notice")
    lines.append("")
    if model_name in INSIGHTFACE_MODELS and not accepted:
        lines.append(
            f"> ⚠ Model `{model_name}` is licensed for **non-commercial research only**. "
            "You have not accepted the license in `[runtime] accept_noncommercial_model_license`. "
            "Per docs/11-commercial-compliance.md §3.2 pick-face refuses to start — this "
            "report exists only because it was generated during tests where the flag was "
            "temporarily set. **Stop using this output for any commercial purpose.**"
        )
    elif model_name in INSIGHTFACE_MODELS:
        lines.append(
            f"> Model `{model_name}` is under the InsightFace non-commercial-research "
            "license; `accept_noncommercial_model_license = true` was set in this run."
        )
        if ack_summary:
            lines.append(f"> Audit trail: {ack_summary}.")
    else:
        lines.append(
            f"> Model `{model_name}` is custom (no commercial restriction enforced by pick-face)."
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def render_json(
    stats: ReportStats,
    *,
    config_dict: dict,
    run_id: str | None = None,
    warnings: tuple[str, ...] = (),
    person_legend: tuple[tuple[int, str, int], ...] = (),
    ack_summary: str | None = None,
) -> str:
    """Same content as markdown, but machine-readable for CI."""
    rid = run_id or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "run_id": rid,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model": {
            "name": config_dict.get("runtime", {}).get("model_name"),
            "dir": config_dict.get("runtime", {}).get("model_dir"),
            "license": (
                "InsightFace non-commercial-research"
                if config_dict.get("runtime", {}).get("model_name") in INSIGHTFACE_MODELS
                else "custom"
            ),
            "license_accepted": bool(
                config_dict.get("runtime", {}).get("accept_noncommercial_model_license", False)
            ),
            "accepted_by": ack_summary,
            "provider": config_dict.get("runtime", {}).get("provider"),
        },
        "stats": stats.__dict__,
        "persons": [
            {"id": cid, "label": label, "size": size} for cid, label, size in person_legend
        ],
        "warnings": list(warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_html(
    stats: ReportStats,
    *,
    config_dict: dict,
    run_id: str | None = None,
    warnings: tuple[str, ...] = (),
    person_legend: tuple[tuple[int, str, int], ...] = (),
    ack_summary: str | None = None,
    dark_mode: bool = False,
) -> str:
    """Render an HTML report (M4 / T-301).

    Self-contained: no external CSS/JS. Uses a `data-theme` attribute on
    <html> that users can flip in DevTools (or copy a dark-mode URL
    parameter later). Includes a per-person "thumbnail wall" that
    links each cluster into the index.json mirror.
    """
    rid = run_id or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    model_name = config_dict.get("runtime", {}).get("model_name", "buffalo_l")
    model_dir = config_dict.get("runtime", {}).get("model_dir", "~/.insightface/models")
    provider = config_dict.get("runtime", {}).get("provider", "auto")
    accepted = bool(config_dict.get("runtime", {}).get("accept_noncommercial_model_license", False))

    license_label = (
        "InsightFace non-commercial-research"
        if model_name in INSIGHTFACE_MODELS
        else "custom (no commercial restriction enforced by pick-face)"
    )

    theme_attr = 'data-theme="dark"' if dark_mode else 'data-theme="light"'

    # Person legend rows.
    person_rows = []
    for _cid, label, size in person_legend:
        person_rows.append(
            f'<li><a href="./{label}/">{label}</a> <span class="size">({size} faces)</span></li>'
        )
    person_list = (
        f'<ul class="persons">{"".join(person_rows)}</ul>'
        if person_rows
        else '<p class="empty">(no persons yet — run <code>pick-face cluster</code>)</p>'
    )

    warning_items = "".join(f"<li>{w}</li>" for w in warnings) if warnings else ""
    warnings_block = (
        f'<section class="warnings"><h2>⚠ Warnings</h2><ul>{warning_items}</ul></section>'
        if warning_items
        else ""
    )

    total_links = (
        stats.symlink_links + stats.hardlink_links + stats.junction_links + stats.copy_links
    )
    links_line = (
        f"<li><strong>Link kinds</strong>: symlink={stats.symlink_links}, "
        f"hardlink={stats.hardlink_links}, junction={stats.junction_links}, "
        f"copy={stats.copy_links}</li>"
        if total_links > 0
        else ""
    )

    ack_line = f"<li><strong>Accepted by</strong>: {ack_summary}</li>" if ack_summary else ""

    html = f"""<!doctype html>
<html lang="en" {theme_attr}>
<head>
<meta charset="utf-8">
<title>pick-face Report {rid}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --bg: #fdfdfd; --fg: #1a1a1a; --muted: #666;
  --border: #e3e3e3; --panel: #f7f7f7; --accent: #1a73e8;
  --warn-bg: #fff8e1; --warn-fg: #b76a00;
}}
[data-theme="dark"] {{
  --bg: #181818; --fg: #e8e8e8; --muted: #999;
  --border: #2a2a2a; --panel: #1f1f1f; --accent: #4ea1ff;
  --warn-bg: #3a2e1a; --warn-fg: #f0c674;
}}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       margin: 2rem auto; max-width: 64rem; padding: 0 1rem;
       background: var(--bg); color: var(--fg); }}
h1, h2 {{ color: var(--fg); border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }}
h2 {{ margin-top: 2rem; }}
ul {{ padding-left: 1.4rem; }}
li {{ margin: 0.3rem 0; }}
code {{ background: var(--panel); padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.95em; }}
.persons {{ list-style: square; }}
.persons li a {{ color: var(--accent); text-decoration: none; }}
.persons li a:hover {{ text-decoration: underline; }}
.persons .size {{ color: var(--muted); font-size: 0.9em; }}
.warnings {{ background: var(--warn-bg); border-left: 4px solid var(--warn-fg);
            padding: 1rem; border-radius: 4px; }}
.warnings h2 {{ margin-top: 0; color: var(--warn-fg); border: none; }}
.empty {{ color: var(--muted); font-style: italic; }}
.wall {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 1rem; margin-top: 1rem; }}
.wall .card {{ background: var(--panel); border: 1px solid var(--border);
              border-radius: 6px; padding: 0.6rem; text-align: center;
              transition: transform 0.15s ease; }}
.wall .card:hover {{ transform: translateY(-2px); }}
.wall .card a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
.wall .card .meta {{ color: var(--muted); font-size: 0.85em; margin-top: 0.3rem; }}
</style>
</head>
<body>
<h1>pick-face Report</h1>
<section>
  <h2>Run</h2>
  <ul>
    <li><strong>Run ID</strong>: <code>{rid}</code></li>
    <li><strong>Generated</strong>: <code>{datetime.now(tz=timezone.utc).isoformat()}</code></li>
    <li><strong>Model</strong>: <code>{
        model_name
    }</code> (SCRFD-10G detector + ArcFace w600k_r50 embedder)</li>
    <li><strong>Model dir</strong>: <code>{model_dir}</code></li>
    <li><strong>Model License</strong>: {license_label}</li>
    <li><strong>License Accepted</strong>: {
        "yes" if accepted else "no (commercial users must self-train, see docs/11)"
    }</li>
    {ack_line}
    <li><strong>Provider</strong>: <code>{provider}</code></li>
  </ul>
</section>

<section>
  <h2>Stats</h2>
  <ul>
    <li><strong>Total sources</strong>: {stats.total_sources}</li>
    <li><strong>Active sources</strong>: {stats.active_sources}</li>
    <li><strong>Missing sources</strong>: {stats.missing_sources}</li>
    <li><strong>Total faces</strong>: {stats.total_faces}</li>
    <li><strong>Low-quality faces</strong>: {stats.low_quality_faces}</li>
    <li><strong>Noise faces (cluster_id IS NULL)</strong>: {stats.noise_faces}</li>
    <li><strong>Persons</strong>: {stats.persons}</li>
    <li><strong>Cluster ID range</strong>: {stats.cluster_id_min}..{stats.cluster_id_max}</li>
    <li><strong>Avg face-to-centroid similarity</strong>: {stats.avg_face_to_cluster:.3f}</li>
    {links_line}
  </ul>
</section>

<section>
  <h2>Persons</h2>
  {person_list}
</section>

<section class="wall-section">
  <h2>Thumbnail wall</h2>
  <p class="empty">
    Per-person thumbnails land in a follow-up release. The grid below
    shows the cluster IDs and links into <code>index.json</code>; each
    cluster directory contains a <code>meta.json</code> with the full
    descriptor.
  </p>
  <div class="wall">
    {
        "".join(
            f'<div class="card"><a href="./{label}/">{label}</a><div class="meta">{size} faces</div></div>'
            for cid, label, size in person_legend
        )
    }
  </div>
</section>

{warnings_block}

<section>
  <h2>Review candidates</h2>
  <p>
    Faces with <code>cos &lt; clustering.low_confidence</code> to their
    cluster centroid are listed in <code>low_confidence_faces.json</code>
    next to this report. Use <code>pick-face review apply</code> to
    merge / split / remove any of them.
  </p>
</section>

<footer style="margin-top: 3rem; color: var(--muted); font-size: 0.85em;">
  <p>Generated by pick-face. Toggle dark mode by editing
     <code>&lt;html data-theme="dark"&gt;</code>.</p>
</footer>
</body>
</html>
"""
    return html


def write_report(
    conn: sqlite3.Connection,
    *,
    out_dir: Path,
    config_dict: dict,
    fmt: str = "md",
    run_id: str | None = None,
) -> Path:
    """Single entry point: write report.md / report.json to *out_dir*.

    Returns the absolute path of the written file.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = collect_stats(conn)

    legend_rows = conn.execute(
        "SELECT id, label, size FROM cluster WHERE merged_into IS NULL ORDER BY id"
    ).fetchall()
    person_legend = [(int(r["id"]), str(r["label"]), int(r["size"])) for r in legend_rows]

    link_cfg = config_dict.get("link", {})
    prefer = link_cfg.get("prefer", "symlink")
    runtime_cfg = config_dict.get("runtime", {})
    warnings = _warnings_for(runtime_cfg, stats, prefer=prefer)
    ack_summary = _license_ack_line(config_dict)

    if fmt == "md":
        body = render_markdown(
            stats,
            config_dict=config_dict,
            run_id=run_id,
            warnings=warnings,
            person_legend=person_legend,
            ack_summary=ack_summary,
        )
        target = out_dir / "report.md"
    elif fmt == "json":
        body = render_json(
            stats,
            config_dict=config_dict,
            run_id=run_id,
            warnings=warnings,
            person_legend=person_legend,
            ack_summary=ack_summary,
        )
        target = out_dir / "report.json"
    elif fmt == "html":
        body = render_html(
            stats,
            config_dict=config_dict,
            run_id=run_id,
            warnings=warnings,
            person_legend=person_legend,
            ack_summary=ack_summary,
        )
        target = out_dir / "report.html"
    else:
        raise ValueError(f"unsupported fmt: {fmt!r} (M4 adds html)")

    target.write_text(body, encoding="utf-8")
    return target


def _license_ack_line(config_dict: dict) -> str | None:
    """Build the 'Accepted by …' line for report.md/json (docs/11 §3.4).

    We re-derive the model_dir/model_name from the JSON config and try to
    read `.license_ack` next to it. We do this here (rather than via
    `models.license_ack_summary`) so the reporter stays decoupled from
    the runtime models module.
    """
    try:
        from pick_face.config import PickFaceConfig
        from pick_face.models import license_ack_summary

        cfg = PickFaceConfig.model_validate(config_dict)
        return license_ack_summary(cfg)
    except Exception:
        return None


def collect_low_confidence_faces(
    conn: sqlite3.Connection,
    *,
    threshold: float,
) -> list[dict]:
    """Return faces whose similarity-to-centroid is below *threshold*.

    Reference:
        docs/04 §2.5 / docs/09 §10 — ``low_confidence_faces.json`` lists
        every face with ``cos < low_confidence`` to its cluster centroid
        so the user can quickly locate them via the ``review`` subcommand.

    We deliberately restrict to faces that DID get assigned a cluster
    (``cluster_id IS NOT NULL``): pure noise faces already surface in
    the report's `noise_faces` stat and have no centroid to compare
    against. Excluded/removed faces are skipped too — the user asked
    them to be hidden.

    Returns a list of dicts with the keys:
        face_id (int), cluster_id (int), cluster_label (str),
        similarity (float, 4 decimals), source_id (int), source_path (str),
        rel_path (str), review_state (str).
    Sorted by similarity ascending (worst first) so the top of the file
    is where the user should look.
    """
    cur = conn.execute(
        """
        SELECT f.id          AS face_id,
               f.cluster_id  AS cluster_id,
               c.label       AS cluster_label,
               f.cluster_prob AS similarity,
               f.source_id   AS source_id,
               s.path        AS source_path,
               s.rel_path    AS rel_path,
               f.review_state AS review_state
        FROM face f
        JOIN cluster c ON c.id = f.cluster_id
        JOIN source  s ON s.id = f.source_id
        WHERE f.cluster_prob IS NOT NULL
          AND f.cluster_prob < ?
          AND f.review_state != 'removed'
        ORDER BY f.cluster_prob ASC, f.id ASC
        """,
        (float(threshold),),
    )
    out: list[dict] = []
    for r in cur.fetchall():
        out.append(
            {
                "face_id": int(r["face_id"]),
                "cluster_id": int(r["cluster_id"]),
                "cluster_label": str(r["cluster_label"]),
                "similarity": round(float(r["similarity"]), 4),
                "source_id": int(r["source_id"]),
                "source_path": str(r["source_path"]),
                "rel_path": str(r["rel_path"]),
                "review_state": str(r["review_state"]),
            }
        )
    return out


def write_low_confidence_json(
    conn: sqlite3.Connection,
    *,
    out_dir: Path,
    threshold: float,
    run_id: str | None = None,
) -> Path:
    """Write ``low_confidence_faces.json`` to *out_dir*.

    Returns the absolute path of the written file. The JSON shape is:

        {
          "schema": "pick-face/low_confidence_faces@1",
          "run_id": "2026-08-03T12-00-00",
          "generated_at": "2026-08-03T12:00:00+00:00",
          "threshold": 0.40,
          "count": 12,
          "faces": [
            {"face_id": 123, "cluster_id": 4, "cluster_label": "person-0004",
             "similarity": 0.21, "source_id": 9, "source_path": "...",
             "rel_path": "2026/07/img_0001.jpg", "review_state": "auto"},
            ...
          ]
        }

    The schema field lets future format changes stay backward-compatible
    — readers can check it before parsing.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    faces = collect_low_confidence_faces(conn, threshold=threshold)
    rid = run_id or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    payload = {
        "schema": "pick-face/low_confidence_faces@1",
        "run_id": rid,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "threshold": float(threshold),
        "count": len(faces),
        "faces": faces,
    }
    target = out_dir / "low_confidence_faces.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def _warnings_for(
    runtime_cfg: dict,
    stats: ReportStats,
    *,
    prefer: str = "symlink",
) -> tuple[str, ...]:
    """Compute the ⚠ Warnings list (docs/05 §6 + docs/11 §3.4 + T-107)."""
    out: list[str] = []
    name = runtime_cfg.get("model_name", "buffalo_l")
    accepted = bool(runtime_cfg.get("accept_noncommercial_model_license", False))

    if name in INSIGHTFACE_MODELS and not accepted:
        out.append(
            f"Model `{name}` is non-commercial-research-licensed. Set "
            "`[runtime] accept_noncommercial_model_license = true` "
            "(only if your use case qualifies)."
        )
    provider = runtime_cfg.get("provider", "auto")
    if provider == "auto":
        out.append("Provider=auto; on Windows, this probes DirectML → CPU in that order.")
    if stats.missing_sources > 0:
        out.append(
            f"{stats.missing_sources} source(s) disappeared since the last scan; "
            "their cluster membership is preserved but they're flagged `missing`."
        )

    # T-107: link-fallback warning. If the user asked for symlink/junction
    # but the linker ended up writing more copies than preferred kinds,
    # the OS is rejecting symbolic links (Windows non-admin, no developer
    # mode). Surface this so the user knows disk usage will be higher.
    actual_total = (
        stats.symlink_links + stats.hardlink_links + stats.junction_links + stats.copy_links
    )
    if actual_total > 0 and prefer in ("symlink", "junction") and stats.copy_links > 0:
        non_preferred = stats.copy_links
        if non_preferred / actual_total > 0.05:
            # Only warn when ≥5% fell back — a few stragglers are normal
            # on cross-volume layouts.
            out.append(
                f"{non_preferred}/{actual_total} links fell back to copy instead of "
                f"{prefer!r}. On Windows this usually means Developer Mode is off "
                "or you're running unelevated. See docs/troubleshooting.md."
            )

    return tuple(out)
