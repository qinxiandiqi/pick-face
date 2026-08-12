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
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pick_face.api import config, health, persons, photos, scan
from pick_face.service.paths import get_layout
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
        app.state.layout = layout
        # Build runner + start its polling task. We don't *require*
        # detector/embedder to be loaded — `make_runner` handles the
        # missing-weights case by leaving them as None; the runner
        # will fail-fast with a clear error if a job is submitted.
        runner = make_runner(layout=layout)
        app.state.runner = runner
        runner.start()
        try:
            yield
        finally:
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


__all__ = ["create_app", "app"]
