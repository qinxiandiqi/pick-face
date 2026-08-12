"""Health endpoints — `docs/03 §2.5`.

Two routes:

- ``GET /api/health`` — liveness: just answers 200 OK. Used by the
  desktop wrapper / k8s liveness probe.
- ``GET /api/ready`` — readiness: returns the layout summary, a
  per-subsystem status (DB reachable, config readable, jobs dir
  writable), and the **active model pack** with its ``LicenseClass``
  so the SPA Model tab can render an NC-research Badge (M7-T-13).
  Used as the desktop wrapper's "is the Web service up?" poll
  target.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from pick_face.api.deps import get_layout
from pick_face.core.config import load_config
from pick_face.service.paths import AppLayout

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — always 200 OK if the process is alive."""
    return {"status": "ok"}


def _resolve_active_pack(layout: AppLayout) -> dict[str, Any] | None:
    """Best-effort lookup of the active pack descriptor + license.

    Returns ``None`` if the config can't be loaded, no pack plugin is
    registered, or the configured pack id doesn't match any plugin.
    The Model tab falls back to a static placeholder in that case.
    """
    from pick_face.platform.pack import discover_packs

    try:
        cfg = load_config(layout.config_file)
    except Exception:
        return None
    try:
        packs = discover_packs()
    except Exception:
        return None

    pack_id = cfg.runtime.effective_pack_id()
    pack = packs.get(pack_id)
    if pack is None:
        return None
    desc = pack.descriptor
    return {
        "id": desc.pack_id,
        "display_name": desc.display_name,
        "license_class": desc.license_class.value,
        "license_name": desc.license_name,
        "license_spdx": desc.license_spdx,
        # Surface the AC-9 ack flag so the badge can render the "not
        # acknowledged" warning in addition to the NC-research label.
        "nc_research_acknowledged": (
            desc.license_class.value != "nc-research"
            or cfg.runtime.accept_noncommercial_model_license
        ),
    }


@router.get("/ready")
def ready(layout: AppLayout = Depends(get_layout)) -> dict[str, Any]:
    """Readiness probe — checks DB connectivity + config presence."""
    db_ok = False
    db_error: str | None = None
    try:
        conn = sqlite3.connect(str(layout.db_path))
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        db_error = str(exc)

    config_ok = layout.config_file.exists()
    cache_ok = layout.cache_dir.is_dir()
    jobs_ok = layout.jobs_dir.is_dir()

    overall = db_ok and config_ok and cache_ok and jobs_ok
    return {
        "status": "ready" if overall else "degraded",
        "layout": {
            "root": str(layout.root),
            "config_dir": str(layout.config_dir),
            "data_dir": str(layout.data_dir),
            "cache_dir": str(layout.cache_dir),
        },
        "checks": {
            "db": {"ok": db_ok, "error": db_error},
            "config": {"ok": config_ok},
            "cache_dir": {"ok": cache_ok},
            "jobs_dir": {"ok": jobs_ok},
        },
        "active_pack": _resolve_active_pack(layout),
    }


__all__ = ["router"]
