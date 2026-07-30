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
            {"id": cid, "label": label, "size": size}
            for cid, label, size in person_legend
        ],
        "warnings": list(warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


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

    runtime_cfg = config_dict.get("runtime", {})
    warnings = _warnings_for(runtime_cfg, stats)
    ack_summary = _license_ack_line(config_dict)

    if fmt == "md":
        body = render_markdown(
            stats, config_dict=config_dict, run_id=run_id,
            warnings=warnings, person_legend=person_legend,
            ack_summary=ack_summary,
        )
        target = out_dir / "report.md"
    elif fmt == "json":
        body = render_json(
            stats, config_dict=config_dict, run_id=run_id,
            warnings=warnings, person_legend=person_legend,
            ack_summary=ack_summary,
        )
        target = out_dir / "report.json"
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
        from pick_face.models import license_ack_summary
        from pick_face.config import PickFaceConfig

        cfg = PickFaceConfig.model_validate(config_dict)
        return license_ack_summary(cfg)
    except Exception:
        return None


def _warnings_for(runtime_cfg: dict, stats: ReportStats) -> tuple[str, ...]:
    """Compute the ⚠ Warnings list (docs/05 §6 + docs/11 §3.4)."""
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
    return tuple(out)
