"""FastAPI app factory — `docs/03 §2` + `docs/06 §1`.

`create_app()` builds the FastAPI app with:

- All v3 routers mounted under ``/api/...``
- ScanRunner attached to ``app.state`` (started/stopped via
  lifespan hooks)
- ``AppLayout`` stashed on ``app.state.layout`` so request handlers
  don't recompute paths
- The React SPA static bundle mounted at ``/`` (M6 ships an
  ``index.html`` placeholder; M7 mounts the real Vite build)

The factory is the *only* public surface — ``web_cli.py`` imports
``create_app`` and hands it to ``uvicorn.run``.

M8 — additional background services wired in the lifespan:
- :class:`pick_face.service.file_watcher.FileWatcher` (watchdog → asyncio.Queue → ``ScanService.start(kind='path_only')``)
- :class:`pick_face.service.polling_scheduler.PollingScheduler` (APScheduler fallback every ``incremental_interval_sec`` seconds)
- :class:`pick_face.worker.cluster_worker.ClusterWorker` (periodic full recluster + incremental trigger on ``recluster_threshold`` new faces)
- HNSW index preloaded via :func:`pick_face.worker.cluster_worker.ensure_hnsw_loaded`

Any individual subsystem failure degrades that component to
``status() == "disabled"``; the rest of the service still serves
HTTP. This is what keeps a missing optional dep (hnswlib, hdbscan,
watchdog) from taking down the Web UI.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pick_face.api import config, health, persons, photos, scan
from pick_face.service.file_watcher import FileWatcher
from pick_face.service.paths import get_layout
from pick_face.service.polling_scheduler import PollingScheduler
from pick_face.worker.cluster_worker import ClusterWorker, ensure_hnsw_loaded
from pick_face.worker.runner import make_runner

log = logging.getLogger(__name__)


def create_app(
    *,
    layout=None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build and return the FastAPI app.

    Args:
        layout: optional pre-built ``AppLayout`` (used in tests to
            point at a temp dir). Defaults to :func:`get_layout`.
        static_dir: optional override for SPA static bundle path.
            Defaults to ``src/pick_face/web/static``.
    """
    layout = layout or get_layout()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        import asyncio

        app.state.layout = layout
        # ---- M6: scan runner ------------------------------------------------
        runner = make_runner(layout=layout)
        app.state.runner = runner
        runner.start()

        # ---- M8: HNSW preload (M8-T-5) --------------------------------------
        embedding_dim = _resolve_embedding_dim(runner)
        hnsw_index = None
        if embedding_dim is not None:
            try:
                hnsw_index = ensure_hnsw_loaded(layout, embedding_dim=embedding_dim)
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("ensure_hnsw_loaded failed: %s", exc)
        app.state.hnsw = hnsw_index
        app.state.embedding_dim = embedding_dim

        # ---- M8: cluster worker (M8-T-3 / T-4) -------------------------------
        cluster_worker: ClusterWorker | None = None
        if embedding_dim is not None:
            try:
                cluster_worker = ClusterWorker(
                    layout,
                    embedding_dim=embedding_dim,
                    hnsw_index=hnsw_index,
                )
                # Register on the runner so DONE scans feed the
                # unclustered-count trigger (M8-T-4).
                runner._on_scan_complete = cluster_worker.note_scan_complete  # noqa: SLF001
                cluster_worker.start()
                app.state.cluster_worker = cluster_worker
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("cluster_worker init failed: %s", exc)

        # ---- M8: file watcher (M8-T-1) --------------------------------------
        file_watcher: FileWatcher | None = None
        try:
            file_watcher = FileWatcher(
                layout,
                loop=asyncio.get_running_loop(),
                runner=runner,
            )
            file_watcher.start()
            app.state.file_watcher = file_watcher
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("file_watcher init failed: %s", exc)

        # ---- M8: polling scheduler (M8-T-2) ---------------------------------
        polling: PollingScheduler | None = None
        try:
            polling = PollingScheduler(layout, runner=runner)
            polling.start()
            app.state.polling_scheduler = polling
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("polling_scheduler init failed: %s", exc)

        try:
            yield
        finally:
            # Stop in reverse order. Polling first so no new jobs
            # land while the file watcher drains.
            for stop_fn in (
                (polling.stop if polling is not None else None),
                (file_watcher.stop if file_watcher is not None else None),
                (cluster_worker.stop if cluster_worker is not None else None),
            ):
                if stop_fn is None:
                    continue
                try:
                    res = stop_fn()
                    if hasattr(res, "__await__"):
                        await res
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("lifespan stop error: %s", exc)
            await runner.stop()

    app = FastAPI(
        title="pick-face Web Service",
        version="3.0.0",
        description=(
            "v3.0 Web service — the successor to the v2.x CLI. "
            "All v2.x algorithm code (scanner, detector, embedder, "
            "SQLite store) is reused; v3 adds a FastAPI transport "
            "and a React SPA frontend."
        ),
        lifespan=lifespan,
    )

    # Routers — order doesn't matter; FastAPI matches by exact path.
    app.include_router(health.router)
    app.include_router(config.router)
    app.include_router(scan.router)
    app.include_router(persons.router)
    app.include_router(photos.router)

    # SPA mount — always last so it acts as a catch-all.
    static_dir = static_dir or (Path(__file__).parent.parent / "web" / "static")
    if static_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="spa",
        )
    else:
        log.warning("SPA static dir not found at %s; UI not served", static_dir)

    return app


# Default app instance for `uvicorn pick_face.api.app:app` reload.
app = create_app()


def _resolve_embedding_dim(runner: object) -> int | None:
    """Read ``embedder.dim`` off the runner if a pack is loaded.

    Returns ``None`` when no embedder is loaded (test environments,
    pre-init state). The cluster worker is skipped in that case.
    """
    embedder = getattr(runner, "_embedder", None)
    if embedder is None:
        return None
    dim = getattr(embedder, "dim", None)
    if not isinstance(dim, int) or dim <= 0:
        return None
    return dim


__all__ = ["create_app", "app"]
