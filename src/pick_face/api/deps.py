"""FastAPI dependency provider — singleton service handles per request.

The services (`ConfigService`, `ScanService`, `PersonService`,
`PhotoService`) are stateless apart from their `AppLayout`: each call
re-reads the config.toml / DB. This means we can construct one per
request and stay safe under concurrency. We hoist the `AppLayout` into
``app.state`` at startup so the request scope doesn't recompute it.
"""

from __future__ import annotations

from fastapi import Request

from pick_face.service.config_service import ConfigService
from pick_face.service.paths import AppLayout
from pick_face.service.person_service import PersonService
from pick_face.service.photo_service import PhotoService
from pick_face.service.scan_service import ScanService


def get_layout(request: Request) -> AppLayout:
    layout = getattr(request.app.state, "layout", None)
    if layout is None:  # pragma: no cover — startup hook should always set this
        from pick_face.service.paths import get_layout as _resolve

        return _resolve()
    return layout


def get_config_service(request: Request) -> ConfigService:
    return ConfigService(get_layout(request))


def get_scan_service(request: Request) -> ScanService:
    return ScanService(get_layout(request))


def get_person_service(request: Request) -> PersonService:
    return PersonService(get_layout(request))


def get_photo_service(request: Request) -> PhotoService:
    return PhotoService(get_layout(request))


__all__ = [
    "get_config_service",
    "get_layout",
    "get_person_service",
    "get_photo_service",
    "get_scan_service",
]
