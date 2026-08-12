"""Photo streaming HTTP surface — `docs/03 §2.4`.

Routes:

- ``GET /api/photos/{id}``        original photo (HTTP Range supported)
- ``GET /api/photos/{id}/thumb``  256×256 JPEG thumbnail (cached)
- ``GET /api/photos/{id}/meta``   metadata (path, mtime, size, hash)

The bottleneck for both streaming and thumbnail is the
``PhotoService`` — never read the file paths directly. The whitelist
check is enforced on every request.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from pick_face.api.deps import get_photo_service
from pick_face.service.photo_service import (
    PhotoAccessError,
    PhotoNotFoundError,
    PhotoService,
)

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.get("/{photo_id}")
def get_photo(
    photo_id: int,
    request: Request,
    svc: PhotoService = Depends(get_photo_service),
) -> FileResponse:
    """Stream the original photo. Supports HTTP Range via Starlette."""
    try:
        path = svc.get_photo_path(photo_id)
    except PhotoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PhotoAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{photo_id}/thumb")
def get_photo_thumb(
    photo_id: int,
    svc: PhotoService = Depends(get_photo_service),
) -> FileResponse:
    """Stream the 256×256 JPEG thumbnail (generated on first request)."""
    try:
        thumb = svc.thumbnail(photo_id)
    except PhotoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PhotoAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(
        thumb,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{photo_id}/meta")
def get_photo_meta(
    photo_id: int,
    svc: PhotoService = Depends(get_photo_service),
) -> dict[str, Any]:
    try:
        rec = svc.get_photo(photo_id)
    except PhotoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": rec.id,
        "path": str(rec.path),
        "mtime": rec.mtime,
        "size": rec.size,
        "content_hash": rec.content_hash,
    }


__all__ = ["router"]
