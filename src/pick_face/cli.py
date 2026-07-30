"""pick-face CLI entry point.

14 subcommands per docs/03 §7 / docs/08 §6.5:
    init / init-models / scan / index / cluster / link / run / report /
    review / review apply / gc / prune / rollback / rebuild
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import numpy as np
import typer
from rich.console import Console
from rich.panel import Panel

from pick_face import __version__
from pick_face.config import write_default_config
from pick_face.errors import (
    CliArgError,
    CommercialLicenseError,
    ConfigError,
    ModelLoadError,
    ModelNotFoundError,
    PickFaceError,
)
from pick_face.index import open_db

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


def _exit(exc: BaseException) -> None:
    """Print + exit with the error's contract exit code (docs/03 §9)."""
    _errprint(exc)
    code = exc.exit_code if isinstance(exc, PickFaceError) else 1
    raise typer.Exit(code=code)


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
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite if exists.")
    ] = False,
) -> None:
    """Generate a default pick-face.toml at --output (default: ./pick-face.toml)."""
    if output.exists() and not force:
        _exit(CliArgError(f"{output} exists; pass --force to overwrite."))
    write_default_config(output)
    console.print(f"[green]Wrote[/green] {output}")


@app.command()
def init_models(
    allow_network: Annotated[
        bool,
        typer.Option(
            "--allow-network",
            help="Required to actually contact InsightFace model servers.",
        ),
    ] = False,
    config_file: Annotated[
        Path, typer.Option("--config", "-c", help="Path to pick-face.toml.")
    ] = Path("pick-face.toml"),
) -> None:
    """Download the configured model pack (requires --allow-network + I AGREE)."""
    if not allow_network:
        _exit(
            CliArgError(
                "Refusing to download models without --allow-network. "
                "See docs/11 §3.3 for the License Notice."
            )
        )
    # Full notice printing + .license_ack emission is implemented in T-013 (M1).
    # Stub: refuse if not implemented yet.
    raise NotImplementedError(
        "T-013 init-models License Notice + .license_ack is M1 follow-up. "
        "See docs/11-commercial-compliance.md §3.3 for the full text to print."
    )


# ---------------------------------------------------------------------------
# scan / index / cluster / link
# ---------------------------------------------------------------------------


@app.command()
def scan(
    src: Annotated[list[Path], typer.Option("--src", "-s", help="Source dir(s).")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output dir.")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    include: Annotated[
        Optional[list[str]], typer.Option("--include", help="Glob include(s).")
    ] = None,
    exclude: Annotated[
        Optional[list[str]], typer.Option("--exclude", help="Glob exclude(s).")
    ] = None,
) -> None:
    """Scan --src and write the source table (incremental diff)."""
    from pick_face.scanner import scan as scanner_scan

    if not src:
        _exit(CliArgError("--src must be provided at least once."))
    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            "SELECT path, size, mtime, hash FROM source WHERE status = 'active'"
        )
        db_rows: dict[str, tuple[int, float, str]] = {
            r["path"]: (int(r["size"]), float(r["mtime"]), r["hash"] or "")
            for r in cur.fetchall()
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
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    provider: Annotated[
        Optional[str], typer.Option("--provider", help="cpu/cuda/directml/auto")
    ] = None,
) -> None:
    """Detect & embed faces for ADD/MOD sources (writes face table)."""
    from pick_face.config import load_config
    from pick_face.errors import ImageDecodeError, PipelineFailureError
    from pick_face.images import decode as decode_image
    from pick_face.runtime import load_insightface_runner

    cfg = load_config(config_file)
    if provider is not None:
        cfg.runtime.provider = provider  # CLI override

    try:
        runner = load_insightface_runner(cfg)
    except (CommercialLicenseError, ModelNotFoundError, ModelLoadError):
        raise  # let _errprint surface it cleanly

    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        run_id = _record_run_start(conn, "index")
        try:
            sources = [
                dict(r) for r in conn.execute(
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
                            int(s["id"]), bx1, by1, bx2, by2,
                            det.det_score,
                            float(kx[0, 0]), float(kx[0, 1]),
                            float(kx[1, 0]), float(kx[1, 1]),
                            float(kx[2, 0]), float(kx[2, 1]),
                            float(kx[3, 0]), float(kx[3, 1]),
                            float(kx[4, 0]), float(kx[4, 1]),
                            det.quality, 0,
                            emb.tobytes(),
                            runner.model_version,
                            float(np.linalg.norm(emb)),
                        ),
                    )
                    faces_total += 1

            _record_run_finish(conn, run_id, {
                "faces_added": faces_total, "errors": errors,
                "sources_seen": len(sources),
            })
            console.print(
                f"[bold]index[/bold]  sources={len(sources)}  "
                f"faces={faces_total}  errors={errors}"
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
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Full recluster (drop labels).")
    ] = False,
) -> None:
    """HDBSCAN + 2-pass centroid merge (docs/04 §2.4)."""
    from pick_face.cluster import (
        Constraint as _Constraint,  # noqa: F401  (placeholder for review consts)
        cluster_embeddings,
    )
    from pick_face.config import load_config

    cfg = load_config(config_file)
    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        faces = [
            dict(r) for r in conn.execute(
                "SELECT id, embedding, low_quality FROM face"
            ).fetchall()
        ]
        if not faces:
            console.print("[yellow]No faces in DB yet. Run `pick-face index` first.[/yellow]")
            return

        import numpy as np
        face_ids = [f["id"] for f in faces]
        embeddings = np.stack([
            np.frombuffer(f["embedding"], dtype=np.float32).copy() for f in faces
        ])
        low_quality = np.array([bool(f["low_quality"]) for f in faces], dtype=bool)

        constraints: tuple = ()  # review constraints wired in T-104 (M2)

        result = cluster_embeddings(
            embeddings,
            cfg=cfg.clustering,
            low_quality_mask=low_quality,
            constraints=constraints,
        )

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
            row["id"] for row in conn.execute(
                "SELECT id FROM cluster ORDER BY id"
            ).fetchall()
        ]
        max_existing = max(existing) if existing else 0
        with conn:
            for new_lbl in range(result.n_clusters):
                cid = (new_lbl + 1) if not existing else (existing[new_lbl] if new_lbl < len(existing) else (max_existing + (new_lbl - len(existing)) + 1))
                cnt = int((result.labels == new_lbl).sum())
                conn.execute(
                    """INSERT INTO cluster(id, label, size, mean_sim, created_at, updated_at)
                       VALUES (?, ?, ?, NULL, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           size = excluded.size,
                           updated_at = excluded.updated_at""",
                    (int(cid), f"person-{int(cid):04d}", cnt, time.time(), time.time()),
                )
            for i, fid in enumerate(face_ids):
                if result.labels[i] == -1:
                    conn.execute(
                        "UPDATE face SET cluster_id = NULL WHERE id = ?",
                        (int(fid),),
                    )
                else:
                    cid = (result.labels[i] + 1) if not existing else (
                        existing[result.labels[i]] if result.labels[i] < len(existing) else (
                            max_existing + (result.labels[i] - len(existing)) + 1
                        )
                    )
                    conn.execute(
                        "UPDATE face SET cluster_id = ? WHERE id = ?",
                        (int(cid), int(fid)),
                    )

        console.print(
            f"[bold]cluster[/bold]  clusters={result.n_clusters}  noise={result.n_noise}  "
            f"faces={len(face_ids)}"
        )
    finally:
        conn.close()


@app.command()
def link(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    atomic: Annotated[
        bool, typer.Option(
            "--atomic/--no-atomic",
            help="Atomic swap via .staging-<ts> + .prev- (default: on)",
        ),
    ] = True,
) -> None:
    """Create symlinks/hardlinks/copies for each (cluster, source) pair."""
    import shutil
    import json

    from pick_face.config import load_config
    from pick_face.linker import (
        link_or_copy,
        staging_rename_atomic,
        unlink_safely,
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
    for r in rows:
        cluster_label = r["cluster_label"]
        src = Path(r["src_path"])
        # rel_path inside the cluster dir preserves src layout.
        dst = work_out / cluster_label / Path(r["rel_path"])
        try:
            result = link_or_copy(src, dst, prefer=prefer)
            counts[result.kind] += 1
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


# ---------------------------------------------------------------------------
# run / report
# ---------------------------------------------------------------------------


@app.command()
def run(
    src: Annotated[list[Path], typer.Option("--src", "-s")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    provider: Annotated[
        Optional[str], typer.Option("--provider")
    ] = None,
    no_atomic: Annotated[
        bool, typer.Option("--no-atomic", help="Debug: skip staging+rename.")
    ] = False,
) -> None:
    """scan + index + cluster + link in one shot."""
    raise NotImplementedError("T-011: orchestrate scan→index→cluster→link→atomic")


@app.command()
def report(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    fmt: Annotated[
        str, typer.Option("--format", help="md / json / html (html M4)")
    ] = "md",
) -> None:
    """Render report.{md,json,html} with top-line Model+License header (T-009)."""
    import json as _json

    from pick_face.config import load_config
    from pick_face.reporter import write_report

    cfg = load_config(config_file)
    db_path = out / ".cache" / "index.sqlite"
    conn = open_db(db_path)
    try:
        target = write_report(conn, out_dir=out, config_dict=_json.loads(_json.dumps(cfg.model_dump(mode="json"))), fmt=fmt)
    finally:
        conn.close()
    console.print(f"[green]wrote[/green] {target}")


# ---------------------------------------------------------------------------
# review (interactive + apply)
# ---------------------------------------------------------------------------


@review_app.command("interactive")
def review_interactive(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
) -> None:
    """Launch TUI for merge / split / remove / rename decisions (M2)."""
    raise NotImplementedError("T-104: TUI review (M2)")


@review_app.command("apply")
def review_apply(
    file: Annotated[Path, typer.Argument(help="JSON file with decisions.")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
) -> None:
    """Apply a pre-edited review.json (M2)."""
    raise NotImplementedError("T-104: review apply (M2)")


# ---------------------------------------------------------------------------
# gc / prune / rollback / rebuild
# ---------------------------------------------------------------------------


@app.command()
def gc(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
) -> None:
    """Clean dangling links + expired thumbs (docs/03 §9 + docs/05 §6)."""
    raise NotImplementedError("T-011 GC: dangling link cleanup")


@app.command()
def prune(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    keep_n: Annotated[
        int, typer.Option("--keep", help="How many .prev- to keep.")
    ] = 3,
) -> None:
    """Clean _archive/ and old .prev- snapshots (docs/05 §6)."""
    raise NotImplementedError("T-011 prune: archive cleanup")


@app.command()
def rollback(
    to: Annotated[str, typer.Option("--to", help="run_id (e.g. 2026-07-30T...)")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
) -> None:
    """Swap <out> with <out>/.prev-<run_id> (docs/05 §6 + ADR-008)."""
    raise NotImplementedError("T-011 rollback: rename .prev- back to <out>")


@app.command()
def rebuild(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("."),
    config_file: Annotated[
        Path, typer.Option("--config", "-c")
    ] = Path("pick-face.toml"),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Wipe .cache/ and .prev-* and run from scratch."""
    raise NotImplementedError("T-011 rebuild: wipe + full scan/index/cluster")


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
    try:
        try:
            app(standalone_mode=False)
        except typer.Exit as e:
            # typer.Exit is typer's "I want to leave with this code" signal;
            # honour it verbatim (used by --version, CliArgError → rc=2, etc.)
            code = e.exit_code if isinstance(e.exit_code, int) else 1
            sys.exit(code)
    except KeyboardInterrupt:
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
