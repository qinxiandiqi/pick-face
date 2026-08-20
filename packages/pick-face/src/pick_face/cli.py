"""pick-face CLI entry point.

14 subcommands per docs/03 §7 / docs/08 §6.5:
    init / init-models / scan / index / cluster / link / run / report /
    review / review apply / gc / prune / rollback / rebuild
"""

from __future__ import annotations

import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import numpy as np
import typer
from rich.console import Console
from rich.panel import Panel

from pick_face import __version__
from pick_face.core.config import write_default_config
from pick_face.core.errors import (
    CliArgError,
    CommercialLicenseError,
    ConfigError,
    ModelLoadError,
    ModelNotFoundError,
    OutputNotWritableError,
    PickFaceError,
    SourceNotFoundError,
)
from pick_face.store.index import open_db

app = typer.Typer(
    name="pick-face",
    help=(
        "Local offline image face recognition & organization CLI.\n\n"
        "See docs/AGENTS.md for the full doc index and "
        "docs/11-commercial-compliance.md for commercial deployment."
    ),
    no_args_is_help=True,
    add_completion=False,
    # Disable typer's Rich-traced pretty exceptions so PickFaceError subclasses
    # can propagate to main() with their exit_code intact (docs/03 §9).
    pretty_exceptions_enable=False,
)

review_app = typer.Typer(help="Review subcommands: interactive & batch apply.")
app.add_typer(review_app, name="review")

console = Console(stderr=True)


def _errprint(exc: BaseException) -> None:
    if isinstance(exc, CommercialLicenseError):
        console.print(
            Panel.fit(
                f"[red]Commercial license check failed[/red]\n\n{exc.message}\n\n"
                "See docs/11-commercial-compliance.md for the three legal paths:\n"
                "  (a) Self-train an MIT-licensed model (recommended)\n"
                "  (b) Obtain a commercial license from InsightFace\n"
                "  (c) Switch to another MIT/Apache-2.0 model family",
                title="AC-9 violation",
            )
        )
    elif isinstance(exc, (ConfigError, CliArgError)):
        console.print(f"[red]Config error:[/red] {exc.message}")
    elif isinstance(exc, PickFaceError):
        console.print(f"[red]Error ({exc.__class__.__name__}):[/red] {exc.message}")
    else:
        console.print(f"[red]Unhandled error:[/red] {exc}")


def _dry_run_panel(plan: list[str], title: str = "DRY-RUN") -> None:
    """Render a 'what would happen' panel for destructive commands (T-106).

    Used by gc / prune / rollback / rebuild when `--dry-run` is passed.
    The action list is rendered with [yellow] styling so the user can
    see at a glance that nothing actually changed.
    """
    if not plan:
        console.print(Panel.fit("[dim](nothing to do)[/dim]", title=title))
        return
    body = "\n".join(f"  • {step}" for step in plan)
    console.print(Panel.fit(body, title=title, border_style="yellow"))


def _exit(exc: BaseException) -> None:
    """Print + exit with the error's contract exit code (docs/03 §9).

    We raise `SystemExit` rather than `typer.Exit` because `typer.Exit` is
    caught internally by typer/click even when invoked with
    `standalone_mode=False`, so it never reaches our outer except in
    `main()` and the contract exit code would be lost.
    """
    _errprint(exc)
    code = exc.exit_code if isinstance(exc, PickFaceError) else 1
    raise SystemExit(code)


def _now() -> float:
    """Monotonic-clock-ish; seconds since epoch (UTC)."""
    return time.time()


def _now_run_id() -> str:
    """UTC timestamp suitable for naming .prev-<run_id> snapshots."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def _on_sigterm(signum, frame):
    """Translate SIGTERM/SIGBREAK into exit code 5 (InterruptedError contract)."""
    console.print(f"[yellow]received signal {signum}; exiting rc=5[/yellow]")
    sys.exit(5)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"pick-face {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """pick-face root callback (shared --version)."""


# ---------------------------------------------------------------------------
# init / init-models
# ---------------------------------------------------------------------------


@app.command()
def init(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Where to write pick-face.toml."),
    ] = Path("pick-face.toml"),
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite if exists.")] = False,
) -> None:
    """Generate a default pick-face.toml at --output (default: ./pick-face.toml)."""
    if output.exists() and not force:
        _exit(CliArgError(f"{output} exists; pass --force to overwrite."))
    write_default_config(output)
    console.print(f"[green]Wrote[/green] {output}")


@app.command()
def init_models(
    pack: Annotated[
        str | None,
        typer.Option(
            "--pack",
            help=(
                "Model pack id to download (e.g. 'yunet-sface', 'yunet-arcface', "
                "'buffalo_l'). Defaults to `[runtime].pack` in pick-face.toml."
            ),
        ),
    ] = None,
    allow_network: Annotated[
        bool,
        typer.Option(
            "--allow-network",
            help="Required to actually contact the model-pack download URLs.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip the interactive 'I AGREE' confirmation prompt (NC packs only).",
        ),
    ] = False,
    quant: Annotated[
        str,
        typer.Option(
            "--quant",
            help=(
                "Embedder quant for packs that ship multiple variants "
                "(e.g. yunet-arcface ships fp32 and int8). Default: fp32. "
                "Ignored for single-variant packs."
            ),
        ),
    ] = "fp32",
    config_file: Annotated[
        Path, typer.Option("--config", "-c", help="Path to pick-face.toml.")
    ] = Path("pick-face.toml"),
) -> None:
    """Download the configured model pack (requires --allow-network + I AGREE).

    Per docs/14 §4 the active pack is resolved by ``--pack`` (CLI) →
    ``[runtime].pack`` (toml) → legacy ``[runtime].model_name`` (v1.x
    compat) → default ``yunet-mfn``. The License Notice is rendered
    from the installed ``PackDescriptor`` (LicenseClass-driven), and for
    NC-research packs we additionally require an interactive
    ``I AGREE`` confirmation unless ``--yes`` is passed. A
    ``.license_ack`` JSON file is written next to the weights so the
    audit trail is preserved (docs/11 §3.4).
    """
    if not allow_network:
        _exit(
            CliArgError(
                "Refusing to download models without --allow-network. "
                "See docs/11 §3.3 for the License Notice."
            )
        )

    from pick_face.core.config import PickFaceConfig, load_config
    from pick_face.platform.models import license_notice_for, write_license_ack
    from pick_face.platform.pack import LicenseClass, discover_packs

    if config_file.exists():
        cfg = load_config(config_file)
    else:
        cfg = PickFaceConfig()
        console.print(
            f"[yellow]No config at {config_file}; using defaults "
            f"(pack={cfg.runtime.pack!r}).[/yellow]"
        )

    pack_id = pack or cfg.runtime.effective_pack_id()
    packs = discover_packs()
    if pack_id not in packs:
        installed = ", ".join(sorted(packs)) or "(none)"
        _exit(
            CliArgError(
                f"model pack {pack_id!r} not installed. Installed: {installed}. "
                f"Install with: uv pip install pick-face-modelpack-{pack_id}"
            )
        )
    selected = packs[pack_id]

    notice = license_notice_for(pack_id)
    console.print(notice)

    if selected.descriptor.license_class is LicenseClass.NC_RESEARCH and not yes:
        try:
            reply = input("Type 'I AGREE' to continue (or 'NO' to abort): ").strip()
        except EOFError:
            reply = ""
        if reply != "I AGREE":
            _exit(CliArgError("Aborted by user (no 'I AGREE' typed)."))

    # Hand off the actual download to the pack plugin; we only write the
    # .license_ack for NC packs (PERMISSIVE packs self-license).
    target_dir = cfg.runtime.model_dir / pack_id
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        selected.download_to(target_dir, quant=quant)
    except Exception as e:
        _exit(ModelLoadError(f"download failed for pack {pack_id!r}: {e}"))

    if selected.descriptor.license_class is LicenseClass.NC_RESEARCH:
        ack_path = write_license_ack(target_dir, pack_id)
        console.print(f"[green]wrote[/green] {ack_path}")
    else:
        console.print(
            f"[green]downloaded[/green] {pack_id} into {target_dir} "
            f"(license: {selected.descriptor.license_name}, no ack required)"
        )
        # N-4: tip for high-precision ArcFace users.
        if (
            selected.descriptor.embedder_alternates
            and pack_id == "yunet-arcface"
        ):
            console.print(
                "[yellow]Tip:[/yellow] for high-precision 512-D clustering, "
                "set `clustering.merge_threshold = 0.55` in pick-face.toml "
                "(the SFace default of 0.0 under-merges at 512-D)."
            )


# ---------------------------------------------------------------------------
# scan / index / cluster / link
# ---------------------------------------------------------------------------


@app.command()
def scan(
    src: Annotated[list[Path], typer.Option("--src", "-s", help="Source dir(s).")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output dir.")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    include: Annotated[list[str] | None, typer.Option("--include", help="Glob include(s).")] = None,
    exclude: Annotated[list[str] | None, typer.Option("--exclude", help="Glob exclude(s).")] = None,
) -> None:
    """Scan --src and write the source table (incremental diff)."""
    from pick_face.ingest.scanner import scan as scanner_scan

    if not src:
        _exit(CliArgError("--src must be provided at least once."))
    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        cur = conn.execute("SELECT path, size, mtime, hash FROM source WHERE status = 'active'")
        db_rows: dict[str, tuple[int, float, str]] = {
            r["path"]: (int(r["size"]), float(r["mtime"]), r["hash"] or "") for r in cur.fetchall()
        }
    finally:
        conn.close()

    rows, stats = scanner_scan(src, db_rows=db_rows, include=include, exclude=exclude)

    # Persist the new diff back into the source table.
    now = time.time()
    conn = open_db(db_path)
    try:
        with conn:
            for r in rows:
                rel = str(r.rel_path)
                if r.kind.value in ("add", "mod"):
                    conn.execute(
                        """
                        INSERT INTO source(path, rel_path, size, mtime, hash, status, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            rel_path = excluded.rel_path,
                            size = excluded.size,
                            mtime = excluded.mtime,
                            hash = excluded.hash,
                            status = 'active',
                            last_seen = excluded.last_seen
                        """,
                        (str(r.abs_path.resolve()), rel, r.size, r.mtime, r.hash or "", now, now),
                    )
                elif r.kind.value == "unchanged":
                    # Bump last_seen so GC doesn't drop us.
                    conn.execute(
                        "UPDATE source SET last_seen = ? WHERE path = ?",
                        (now, str(r.abs_path.resolve())),
                    )
                elif r.kind.value == "del":
                    conn.execute(
                        "UPDATE source SET status = 'missing' WHERE path = ?",
                        (str(r.abs_path.resolve()),),
                    )
    finally:
        conn.close()

    summary = stats.as_dict()
    console.print(
        f"[bold]scan[/bold]  +{summary['add']}  ~{summary['mod']}  "
        f"={summary['unchanged']}  -{summary['del']}  !{summary['errors']}"
    )


@app.command()
def index(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    provider: Annotated[
        str | None, typer.Option("--provider", help="cpu/cuda/directml/auto")
    ] = None,
) -> None:
    """Detect & embed faces for ADD/MOD sources (writes face table)."""
    from pick_face.core.config import load_config
    from pick_face.core.errors import ImageDecodeError, PipelineFailureError
    from pick_face.core.images import decode as decode_image
    from pick_face.platform.runtime import load_pack_runner

    cfg = load_config(config_file)
    if provider is not None:
        cfg.runtime.provider = provider  # CLI override

    try:
        runner = load_pack_runner(cfg)
    except (CommercialLicenseError, ModelNotFoundError, ModelLoadError):
        raise  # let _errprint surface it cleanly

    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        run_id = _record_run_start(conn, "index")
        try:
            sources = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, path, status FROM source WHERE status = 'active'"
                ).fetchall()
            ]
            faces_total = 0
            errors = 0
            for s in sources:
                try:
                    decoded = decode_image(Path(s["path"]))
                except ImageDecodeError as e:
                    errors += 1
                    conn.execute(
                        "INSERT INTO error_log(run_id, ts, path, stage, kind, message) "
                        "VALUES (?, ?, ?, 'decode', ?, ?)",
                        (run_id, time.time(), s["path"], e.__class__.__name__, str(e)),
                    )
                    continue

                try:
                    detections = runner.detect(decoded.bgr)
                except Exception as e:
                    errors += 1
                    conn.execute(
                        "INSERT INTO error_log(run_id, ts, path, stage, kind, message) "
                        "VALUES (?, ?, ?, 'detect', ?, ?)",
                        (run_id, time.time(), s["path"], e.__class__.__name__, str(e)),
                    )
                    continue

                for det, emb in detections:
                    if emb is None:
                        continue
                    bx1, by1, bx2, by2 = det.bbox
                    kx = det.landmarks
                    conn.execute(
                        """INSERT INTO face(
                            source_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                            det_score, lmk_x0, lmk_y0, lmk_x1, lmk_y1, lmk_x2,
                            lmk_y2, lmk_x3, lmk_y3, lmk_x4, lmk_y4,
                            quality, low_quality, embedding, model_version, norm
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            int(s["id"]),
                            bx1,
                            by1,
                            bx2,
                            by2,
                            det.det_score,
                            float(kx[0, 0]),
                            float(kx[0, 1]),
                            float(kx[1, 0]),
                            float(kx[1, 1]),
                            float(kx[2, 0]),
                            float(kx[2, 1]),
                            float(kx[3, 0]),
                            float(kx[3, 1]),
                            float(kx[4, 0]),
                            float(kx[4, 1]),
                            det.quality,
                            0,
                            emb.tobytes(),
                            runner.model_version,
                            float(np.linalg.norm(emb)),
                        ),
                    )
                    faces_total += 1

            _record_run_finish(
                conn,
                run_id,
                {
                    "faces_added": faces_total,
                    "errors": errors,
                    "sources_seen": len(sources),
                },
            )
            console.print(
                f"[bold]index[/bold]  sources={len(sources)}  faces={faces_total}  errors={errors}"
            )
        except Exception as e:
            _record_run_finish(conn, run_id, {"error": str(e)}, finished=False)
            if isinstance(e, PipelineFailureError):
                raise
            raise PipelineFailureError(f"index pipeline failed: {e}") from e
    finally:
        conn.close()


def _record_run_start(conn, mode: str) -> int:
    cur = conn.execute(
        "INSERT INTO run(started_at, mode, config_hash, stats_json) VALUES (?, ?, ?, '{}')",
        (time.time(), mode, "no-hash-yet"),
    )
    return int(cur.lastrowid)


def _record_run_finish(conn, run_id: int, stats: dict, *, finished: bool = True) -> None:
    import json

    if finished:
        conn.execute(
            "UPDATE run SET finished_at = ?, stats_json = ? WHERE id = ?",
            (time.time(), json.dumps(stats), run_id),
        )
    else:
        conn.execute(
            "UPDATE run SET stats_json = ? WHERE id = ?",
            (json.dumps(stats), run_id),
        )


@app.command()
def cluster(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Full recluster (drop labels).")
    ] = False,
    no_low_confidence: Annotated[
        bool,
        typer.Option(
            "--no-low-confidence",
            help="Skip writing low_confidence_faces.json (T-105).",
        ),
    ] = False,
) -> None:
    """HDBSCAN + 2-pass centroid merge (docs/04 §2.4)."""
    from pick_face.core.config import load_config
    from pick_face.ingest.cluster import (
        Constraint as _Constraint,  # noqa: F401  (placeholder for review consts)
    )
    from pick_face.ingest.cluster import (
        cluster_embeddings,
        face_to_cluster_similarity,
    )

    cfg = load_config(config_file)
    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        faces = [
            dict(r) for r in conn.execute("SELECT id, embedding, low_quality FROM face").fetchall()
        ]
        if not faces:
            console.print("[yellow]No faces in DB yet. Run `pick-face index` first.[/yellow]")
            return

        import numpy as np

        face_ids = [f["id"] for f in faces]
        embeddings = np.stack(
            [np.frombuffer(f["embedding"], dtype=np.float32).copy() for f in faces]
        )
        low_quality = np.array([bool(f["low_quality"]) for f in faces], dtype=bool)

        constraints: tuple = ()  # review constraints wired in T-104 (M2)

        result = cluster_embeddings(
            embeddings,
            cfg=cfg.clustering,
            low_quality_mask=low_quality,
            constraints=constraints,
        )

        # Per-face similarity to its cluster centroid (docs/04 §2.5). This
        # populates face.cluster_prob so downstream report / low-confidence
        # writers have the data they need.
        sims = face_to_cluster_similarity(embeddings, result.labels)

        # Write face.cluster_id back.
        # If rebuild, drop existing cluster rows (and their images); reuse IDs
        # where possible to keep person-XXXX paths stable (docs/04 §2.4).
        if rebuild:
            conn.execute("UPDATE cluster SET merged_into = NULL")
            conn.execute("DELETE FROM cluster")
            conn.execute("DELETE FROM link")
            conn.execute("UPDATE face SET cluster_id = NULL")

        # Reconcile existing cluster rows / ids with the new labels.
        existing = [
            row["id"] for row in conn.execute("SELECT id FROM cluster ORDER BY id").fetchall()
        ]
        max_existing = max(existing) if existing else 0
        with conn:
            for new_lbl in range(result.n_clusters):
                cid = (
                    (new_lbl + 1)
                    if not existing
                    else (
                        existing[new_lbl]
                        if new_lbl < len(existing)
                        else (max_existing + (new_lbl - len(existing)) + 1)
                    )
                )
                cnt = int((result.labels == new_lbl).sum())
                # Cluster-level mean similarity (excluding noise).
                member_mask = result.labels == new_lbl
                cluster_mean = float(sims[member_mask].mean()) if member_mask.any() else 0.0
                conn.execute(
                    """INSERT INTO cluster(id, label, size, mean_sim, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           size = excluded.size,
                           mean_sim = excluded.mean_sim,
                           updated_at = excluded.updated_at""",
                    (
                        int(cid),
                        f"person-{int(cid):04d}",
                        cnt,
                        cluster_mean,
                        time.time(),
                        time.time(),
                    ),
                )
            for i, fid in enumerate(face_ids):
                sim_i = float(sims[i])
                if result.labels[i] == -1:
                    conn.execute(
                        "UPDATE face SET cluster_id = NULL, cluster_prob = NULL WHERE id = ?",
                        (int(fid),),
                    )
                else:
                    cid = (
                        (result.labels[i] + 1)
                        if not existing
                        else (
                            existing[result.labels[i]]
                            if result.labels[i] < len(existing)
                            else (max_existing + (result.labels[i] - len(existing)) + 1)
                        )
                    )
                    conn.execute(
                        "UPDATE face SET cluster_id = ?, cluster_prob = ? WHERE id = ?",
                        (int(cid), sim_i, int(fid)),
                    )

        # T-105: emit low_confidence_faces.json next to the report so users
        # can quickly see which faces need review (docs/04 §2.5 + docs/09 §10).
        if not no_low_confidence:
            from pick_face.output.reporter import write_low_confidence_json

            lc_path = write_low_confidence_json(
                conn,
                out_dir=out,
                threshold=cfg.clustering.low_confidence,
            )
            console.print(
                f"  low_confidence_faces.json  "
                f"(threshold<{cfg.clustering.low_confidence:.2f})  → {lc_path}"
            )

        # T-108: write meta.json per cluster + top-level index.json (docs/05 §5).
        # These are grep/debug mirrors; SQLite remains authoritative.
        from pick_face.output.mirrors import write_all_cluster_metas, write_index_json

        meta_paths = write_all_cluster_metas(conn, out)
        idx_path = write_index_json(conn, out)
        console.print(f"  mirrors  index.json → {idx_path}  ({len(meta_paths)} cluster meta.json)")

        console.print(
            f"[bold]cluster[/bold]  clusters={result.n_clusters}  noise={result.n_noise}  "
            f"faces={len(face_ids)}"
        )
    finally:
        conn.close()


@app.command()
def link(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    atomic: Annotated[
        bool,
        typer.Option(
            "--atomic/--no-atomic",
            help="Atomic swap via .staging-<ts> + .prev- (default: on)",
        ),
    ] = True,
) -> None:
    """Create symlinks/hardlinks/copies for each (cluster, source) pair."""
    import json

    from pick_face.core.config import load_config
    from pick_face.output.linker import (
        link_or_copy,
        staging_rename_atomic,
    )

    cfg = load_config(config_file)
    prefer = cfg.link.prefer

    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        # Build (cluster_id, source_path, rel_path) join.
        rows = conn.execute(
            """SELECT c.id AS cluster_id, c.label AS cluster_label,
                      s.path AS src_path, s.rel_path
               FROM face f
               JOIN cluster c ON f.cluster_id = c.id
               JOIN source  s ON f.source_id = s.id
               WHERE s.status = 'active'
               GROUP BY c.id, s.id"""
        ).fetchall()
    finally:
        conn.close()

    if atomic:
        staging = out.parent / f".staging-{out.name}-{int(time.time())}"
        staging.mkdir(parents=True, exist_ok=True)
        work_out = staging
    else:
        work_out = out

    counts = {"symlink": 0, "hardlink": 0, "junction": 0, "copy": 0, "errors": 0}
    fallbacks: list[str] = []
    for r in rows:
        cluster_label = r["cluster_label"]
        src = Path(r["src_path"])
        # rel_path inside the cluster dir preserves src layout.
        dst = work_out / cluster_label / Path(r["rel_path"])
        try:
            result = link_or_copy(src, dst, prefer=prefer)
            counts[result.kind] += 1
            if result.degraded() and (counts["copy"] == 1 or len(fallbacks) < 5):
                # Only surface a handful — the report aggregates the totals.
                fallbacks.append(f"{src.name}: requested {prefer!r} → fell back to {result.kind!r}")
        except OSError as e:
            counts["errors"] += 1
            console.print(f"[red]link fail:[/red] {src} → {dst}: {e}")
            continue

    if atomic:
        prev, run_id = staging_rename_atomic(staging, out)
        # In a real T-011 implementation we'd prune .prev- here.
        # Write a tiny marker for the new prev so `prune` can keep the most recent N.
        if prev is not None:
            (prev / ".pick-face.prev-of").write_text(json.dumps({"run_id": run_id}))
    else:
        prev, run_id = None, None

    summary = "  ".join(f"{k}={v}" for k, v in counts.items() if v)
    console.print(f"[bold]link[/bold]  {summary or 'no work'}")
    if atomic:
        console.print(f"  staged atomic swap; run_id={run_id}")
    if fallbacks:
        console.print(
            f"[yellow]⚠ {len(fallbacks)} link(s) fell back from {prefer!r} "
            f"to a slower mode. See report.md 'Warnings'.[/yellow]"
        )
        for line in fallbacks[:5]:
            console.print(f"  • {line}")


# ---------------------------------------------------------------------------
# run / report
# ---------------------------------------------------------------------------


@app.command()
def run(
    src: Annotated[list[Path], typer.Option("--src", "-s")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    provider: Annotated[
        str | None, typer.Option("--provider", help="cpu/cuda/directml/auto")
    ] = None,
    atomic: Annotated[
        bool,
        typer.Option(
            "--atomic/--no-atomic",
            help="Atomic swap via .staging-<ts> + .prev- (default: on)",
        ),
    ] = True,
) -> None:
    """scan + index + cluster + link in one shot (T-011).

    Each stage uses the same on-disk SQLite at `out/.cache/index.sqlite`,
    so this is just sequential invocation of the four stage subcommands.
    Stops on the first stage that raises (other than KeyboardInterrupt) so
    the user sees exactly which stage broke; `--no-atomic` is passed
    through to `link` for debugging.
    """

    # 1. scan — pure filesystem walk, no model needed.
    scan(src=src, out=out, config_file=config_file)
    # 2. index — runs InsightFace detector + embedder.
    index(out=out, config_file=config_file, provider=provider)
    # 3. cluster — HDBSCAN + 2-pass centroid merge.
    cluster(out=out, config_file=config_file)
    # 4. link — emit symlinks/hardlinks/copies per cluster.
    link(out=out, config_file=config_file, atomic=atomic)


@app.command()
def report(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    fmt: Annotated[str, typer.Option("--format", help="md / json / html (html M4)")] = "md",
    write_low_confidence: Annotated[
        bool,
        typer.Option(
            "--write-low-confidence/--no-low-confidence",
            help="Also regenerate low_confidence_faces.json (T-105).",
        ),
    ] = True,
    write_mirrors: Annotated[
        bool,
        typer.Option(
            "--write-mirrors/--no-mirrors",
            help="Also regenerate meta.json per cluster + index.json (T-108).",
        ),
    ] = True,
) -> None:
    """Render report.{md,json,html} with top-line Model+License header (T-009)."""
    import json as _json

    from pick_face.core.config import load_config
    from pick_face.output.reporter import write_low_confidence_json, write_report

    cfg = load_config(config_file)
    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        target = write_report(
            conn,
            out_dir=out,
            config_dict=_json.loads(_json.dumps(cfg.model_dump(mode="json"))),
            fmt=fmt,
        )
        if write_low_confidence:
            lc = write_low_confidence_json(
                conn,
                out_dir=out,
                threshold=cfg.clustering.low_confidence,
            )
            console.print(f"[green]wrote[/green] {lc}")
        if write_mirrors:
            from pick_face.output.mirrors import write_all_cluster_metas, write_index_json

            meta_paths = write_all_cluster_metas(conn, out)
            idx_path = write_index_json(conn, out)
            console.print(f"[green]wrote[/green] {idx_path} ({len(meta_paths)} cluster meta.json)")
    finally:
        conn.close()
    console.print(f"[green]wrote[/green] {target}")


# ---------------------------------------------------------------------------
# review (interactive + apply)
# ---------------------------------------------------------------------------


@review_app.command("interactive")
def review_interactive(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
) -> None:
    """Launch TUI for merge / split / remove / rename decisions (M2)."""
    raise NotImplementedError("T-104: TUI review (M2)")


@review_app.command("apply")
def review_apply(
    file: Annotated[Path, typer.Argument(help="JSON file with decisions.")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
) -> None:
    """Apply a pre-edited review.json (M2)."""
    from pick_face.store.review import apply_decisions, load_decisions

    out = out.resolve()
    db_path = out / ".cache" / "index.sqlite"
    if not db_path.exists():
        _exit(SourceNotFoundError(f"no DB at {db_path}; run scan+cluster first"))
    if not file.exists():
        _exit(SourceNotFoundError(f"review file not found: {file}"))

    decisions = load_decisions(file)
    conn = open_db(db_path)
    try:
        ml, cl, rm, rn = apply_decisions(conn, decisions)
    finally:
        conn.close()
    console.print(
        f"[bold]review[/bold] applied "
        f"must_link={ml} cannot_link={cl} remove={rm} rename={rn} "
        f"(re-run `pick-face link` to materialize changes on disk)"
    )


# ---------------------------------------------------------------------------
# gc / prune / rollback / rebuild
# ---------------------------------------------------------------------------


@app.command()
def gc(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="List what would be deleted; do not touch disk or DB (T-106).",
        ),
    ] = False,
) -> None:
    """Clean dangling links + expired thumbs (docs/03 §9 + docs/05 §6).

    Walks the cluster directories under *out*; for each entry that is a
    symlink or hardlink whose target no longer exists, we delete the
    dead entry from disk and remove the matching row in `link` and any
    faces whose source row was lost. Orphan rows in `source` are marked
    `missing` so the report still sees them.

    With `--dry-run` we only list the plan and exit 0 — nothing on disk
    or in the DB is modified.
    """
    out = out.resolve()
    if not out.exists():
        _exit(OutputNotWritableError(f"--out {out} does not exist"))

    db_path = out / ".cache" / "index.sqlite"
    if not db_path.exists():
        console.print(f"[yellow]no DB at {db_path}; nothing to gc.[/yellow]")
        return

    conn = open_db(db_path)
    try:
        rows = conn.execute(
            """SELECT l.id AS link_id, l.cluster_id, l.source_id,
                       l.rel_path, l.link_kind, l.actual_target,
                       s.path AS src_path, s.status AS src_status
               FROM link l JOIN source s ON s.id = l.source_id"""
        ).fetchall()

        dangling: list[tuple[int, Path, str]] = []
        orphans: list[tuple[int, str]] = []
        for r in rows:
            cluster_label = conn.execute(
                "SELECT label FROM cluster WHERE id=?", (r["cluster_id"],)
            ).fetchone()["label"]
            entry = out / cluster_label / Path(r["rel_path"])
            target = r["actual_target"] or r["src_path"]
            try:
                if entry.is_symlink() and not (entry.exists() or entry.resolve().exists()):
                    dangling.append((int(r["link_id"]), entry, "symlink-broken"))
                elif entry.exists() and not Path(target).exists():
                    dangling.append((int(r["link_id"]), entry, "target-missing"))
            except OSError:
                dangling.append((int(r["link_id"]), entry, "resolve-error"))
            if r["src_status"] == "active" and not Path(r["src_path"]).exists():
                orphans.append((int(r["source_id"]), str(r["src_path"])))

        plan: list[str] = []
        for link_id, entry, reason in dangling:
            plan.append(f"unlink {entry}  (link_id={link_id}, {reason})")
        for sid, path in orphans:
            plan.append(f"mark source missing: {path}  (id={sid})")

        if dry_run:
            _dry_run_panel(plan, title="gc (dry-run)")
            return

        cleaned = 0
        for link_id, entry, _reason in dangling:
            try:
                entry.unlink()
            except OSError:
                continue
            conn.execute("DELETE FROM link WHERE id=?", (link_id,))
            cleaned += 1

        now = _now()
        for sid, _path in orphans:
            conn.execute(
                "UPDATE source SET status='missing', last_seen=? WHERE id=?",
                (now, sid),
            )
        conn.commit()
    finally:
        conn.close()

    console.print(f"[bold]gc[/bold]  removed {cleaned} dangling link(s) out of {len(rows)}")


@app.command()
def prune(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    keep_n: Annotated[int, typer.Option("--keep", help="How many .prev- to keep.")] = 3,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; do not delete (T-106).")
    ] = False,
) -> None:
    """Clean _archive/ and old .prev- snapshots (docs/05 §6).

    Keeps the *keep_n* most recent .prev-<run_id> siblings of *out* and
    deletes the rest, plus any empty `_archive/` directories.

    With `--dry-run` we list what would be removed and exit 0.
    """
    out = out.resolve()
    parent = out.parent
    name = out.name
    if not parent.exists():
        _exit(OutputNotWritableError(f"--out parent {parent} does not exist"))

    prev_dirs = sorted(
        [p for p in parent.iterdir() if p.is_dir() and p.name.startswith(f"{name}.prev-")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    victims = prev_dirs[keep_n:]
    plan: list[str] = [f"rmtree {v}" for v in victims]
    archive = out / "_archive"
    if archive.exists():
        plan.append(f"rmdir (recursive) {archive}")

    if dry_run:
        _dry_run_panel(plan, title="prune (dry-run)")
        return

    deleted = 0
    for v in victims:
        try:
            shutil.rmtree(v)
            deleted += 1
        except OSError as e:
            console.print(f"[yellow]could not remove {v}: {e}[/yellow]")

    if archive.exists():
        for child in archive.rglob("*"):
            if child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            archive.rmdir()
        except OSError:
            pass

    console.print(
        f"[bold]prune[/bold]  removed {deleted} old .prev- snapshot(s) "
        f"(kept {min(keep_n, len(prev_dirs))})"
    )


@app.command()
def rollback(
    to: Annotated[str, typer.Option("--to", help="run_id (e.g. 2026-07-30T...)")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Describe the swap; do not rename anything (T-106).",
        ),
    ] = False,
) -> None:
    """Swap <out> with <out>/.prev-<run_id> (docs/05 §6 + ADR-008).

    The current *out* is moved to `.prev-<new_ts>` and the named
    snapshot becomes the live output. This is the user-visible
    "undo" affordance paired with the atomic link swap.

    With `--dry-run` we print the planned moves and exit 0.
    """
    out = out.resolve()
    parent = out.parent
    name = out.name
    target = parent / f"{name}.prev-{to}"
    if not target.exists():
        _exit(SourceNotFoundError(f"snapshot {target} does not exist"))

    new_ts = _now_run_id()
    plan = [
        f"move {out} → {parent / (name + '.prev-' + new_ts)}",
        f"move {target} → {out}",
    ]

    if dry_run:
        _dry_run_panel(plan, title="rollback (dry-run)")
        return

    if not yes:
        console.print(
            f"About to swap:\n"
            f"  current → {parent / (name + '.prev-' + new_ts)}\n"
            f"  restore ← {target}"
        )
        try:
            reply = input("Type 'rollback' to continue: ")
        except EOFError:
            reply = ""
        if reply.strip() != "rollback":
            _exit(CliArgError("Aborted by user"))

    current_backup = parent / f"{name}.prev-{new_ts}"
    if out.exists():
        out.rename(current_backup)
    target.rename(out)
    console.print(f"[green]rolled back to[/green] {out}  (current is now at {current_backup})")


@app.command()
def doctor(
    config_file: Annotated[
        Path, typer.Option("--config", "-c", help="Path to pick-face.toml.")
    ] = Path("pick-face.toml"),
) -> None:
    """Show runtime info: installed packs, model files, Python versions.

    Route B (docs/14 §6 / T-509): the canonical "what do I have on my
    machine?" command. Prints:
      * pick-face + Python + onnxruntime versions
      * Every installed ModelPack plugin (id, display name, license,
        tag set)
      * For the active pack: which weights are present / missing under
        ``[runtime].model_dir/<pack_id>/``
      * Whether `accept_noncommercial_model_license` is set when the
        active pack is NC-research
    """
    from pick_face.core.config import PickFaceConfig, load_config
    from pick_face.platform.pack import LicenseClass, discover_packs
    from pick_face.platform.runtime import (
        describe_provider_chain,
        resolve_providers,
    )

    try:
        cfg = load_config(config_file)
    except Exception:
        cfg = PickFaceConfig()
        console.print(f"[yellow]No/empty config at {config_file}; using defaults.[/yellow]")

    pack_id = cfg.runtime.effective_pack_id()
    model_dir = cfg.runtime.model_dir

    console.print("[bold]pick-face doctor[/bold]")
    console.print(f"  pick-face : {__version__}")
    console.print(f"  python    : {sys.version.split()[0]}")
    try:
        import onnxruntime as ort

        console.print(f"  onnxruntime: {ort.__version__}")
        console.print(
            f"  providers  : {describe_provider_chain(resolve_providers(cfg.runtime.provider))}"
        )
    except ImportError:
        console.print("  onnxruntime: [red]NOT INSTALLED[/red]")

    console.print("")
    console.print("[bold]Installed model packs[/bold]")
    packs = discover_packs()
    if not packs:
        console.print("  (none — only the bundled `yunet-sface` and `yunet-arcface` are shipped with core)")
    for pid in sorted(packs):
        p = packs[pid]
        d = p.descriptor
        marker = "[green]ACTIVE[/green]" if pid == pack_id else "[dim]available[/dim]"
        cls = d.license_class.value
        console.print(
            f"  {marker} {pid:20s}  {d.display_name}\n"
            f"     license={cls}/{d.license_name}  "
            f"size=~{(d.detector_size_bytes + d.embedder_size_bytes) // 1024} KiB  "
            f"tags={','.join(d.tags) or '-'}"
        )

    console.print("")
    console.print(f"[bold]Active pack:[/bold] `{pack_id}`")
    console.print(f"  model dir: {model_dir}")
    pack_dir = model_dir / pack_id
    if not pack_dir.exists():
        console.print(f"  [yellow]weights directory missing: {pack_dir}[/yellow]")
        console.print(f"  Run: pick-face init-models --pack {pack_id} --allow-network")
    else:
        if pack_id in packs:
            expected = set(packs[pack_id].expected_files())
            present = {p.name for p in pack_dir.iterdir() if p.is_file()}
            missing = expected - present
            for fname in sorted(expected):
                ok = fname in present
                mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
                console.print(f"  {mark} {fname}")
            if missing:
                console.print(
                    f"  [yellow]{len(missing)} file(s) missing — re-run "
                    f"`pick-face init-models --pack {pack_id} --allow-network`[/yellow]"
                )
        else:
            files = sorted(p.name for p in pack_dir.iterdir() if p.is_file())
            console.print(f"  files: {', '.join(files) or '(empty)'}")

    if pack_id in packs:
        cls = packs[pack_id].descriptor.license_class
        if cls is LicenseClass.NC_RESEARCH and not cfg.runtime.accept_noncommercial_model_license:
            console.print(
                f"\n[red]AC-9 gate will block this run.[/red] Pack `{pack_id}` "
                f"is {packs[pack_id].descriptor.license_name}; set "
                f"`[runtime] accept_noncommercial_model_license = true`."
            )


@app.command()
def rebuild(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[Path, typer.Option("--config", "-c")] = Path("pick-face.toml"),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; do not delete (T-106).")
    ] = False,
) -> None:
    """Wipe .cache/ and .prev-* and run from scratch.

    Removes `.cache/index.sqlite` plus all `.prev-*` siblings of *out*,
    then signals the caller (orchestrator) that the next scan/index/
    cluster/link cycle should be in `rebuild` mode.

    Reference: docs/05 §6.3 (rebuild mode is the same as running each
    stage with --rebuild where applicable).

    With `--dry-run` we list what would be removed and exit 0.
    """
    out = out.resolve()
    if not out.exists():
        _exit(OutputNotWritableError(f"--out {out} does not exist"))

    cache = out / ".cache"
    prevs = list(out.parent.glob(f"{out.name}.prev-*"))
    prevs = [p for p in prevs if p.is_dir()]
    plan: list[str] = []
    if cache.exists():
        plan.append(f"rmtree {cache}")
    for p in prevs:
        plan.append(f"rmtree {p}")

    if dry_run:
        _dry_run_panel(plan, title="rebuild (dry-run)")
        return

    if not yes:
        console.print(
            f"This will DELETE:\n"
            f"  - {out / '.cache'}/index.sqlite\n"
            f"  - all {out.parent / (out.name + '.prev-*')}\n"
            f"and re-run the next scan → index → cluster → link cycle."
        )
        try:
            reply = input("Type 'wipe' to continue: ")
        except EOFError:
            reply = ""
        if reply.strip() != "wipe":
            _exit(CliArgError("Aborted by user"))

    if cache.exists():
        shutil.rmtree(cache)
    for prev in prevs:
        shutil.rmtree(prev)
    console.print(
        "[bold]rebuild[/bold]  cache wiped; next `pick-face run` will start from a fresh scan."
    )


# ---------------------------------------------------------------------------
# Top-level: translate exceptions to exit codes (docs/03 §9)
# ---------------------------------------------------------------------------


def main() -> None:
    """pick-face entrypoint: own all exit-code translation (docs/03 §9).

    We invoke the typer app with `standalone_mode=False` so any
    non-ClickException raised by a subcommand (i.e. any of our
    PickFaceError subclasses) propagates *out* of the typer chain and
    reaches our except clause here. From there we map PickFaceError →
    exit_code (per docs/03 §9 + docs/11 §3.6); everything else falls
    through to Python's default rc=1.
    """
    # SIGTERM (and SIGBREAK on Windows) should look the same to the
    # caller as a normal rc=5 exit (docs/03 §9 extension: "Interrupted").
    signal.signal(signal.SIGTERM, _on_sigterm)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_sigterm)
    try:
        try:
            app(standalone_mode=False)
        except typer.Exit as e:
            # typer.Exit is typer's "I want to leave with this code" signal;
            # honour it verbatim (used by --version, CliArgError → rc=2, etc.)
            code = e.exit_code if isinstance(e.exit_code, int) else 1
            sys.exit(code)
    except KeyboardInterrupt:
        console.print("[yellow]interrupted by user (Ctrl+C)[/yellow]")
        sys.exit(130)
    except SystemExit:
        raise
    except NotImplementedError as e:
        # During M1 scaffolding, subcommands are placeholders that raise this.
        # Show a clear "todo" hint and exit with code 4 (pipeline-not-ready).
        console.print(f"[yellow]M1 placeholder:[/yellow] {e}")
        sys.exit(4)
    except PickFaceError as e:
        # Single point of translation: docs/03 §9 + docs/11 §3.6 extension.
        _errprint(e)
        sys.exit(e.exit_code)


if __name__ == "__main__":
    main()
