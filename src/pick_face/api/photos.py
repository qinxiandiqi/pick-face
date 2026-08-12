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
    """Photo metadata + face list — used by the SPA viewer overlay.

    Response shape::

        {
          "id": int,
          "path": str,
          "mtime": float,          # epoch seconds
          "size": int,             # bytes
          "content_hash": str,     # hex
          "natural_width": int | null,   # for SVG viewBox
          "natural_height": int | null,
          "faces": [
            {
              "id": int,
              "bbox": [x1, y1, x2, y2] | null,  # pixel space
              "cluster_id": int | null,
              "det_score": float | null,
              "quality": float | null
            },
            ...
          ]
        }

    M7.5: extended to include faces for the SVG bbox overlay (M7-T-6)
    and the PersonDetailPage EXIF side-sheet (M7-T-8).
    """
    try:
        meta = svc.get_photo_metadata(photo_id)
    except PhotoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": meta.id,
        "path": str(meta.path),
        "mtime": meta.mtime,
        "size": meta.size,
        "content_hash": meta.content_hash,
        "natural_width": meta.natural_width,
        "natural_height": meta.natural_height,
        "faces": [
            {
                "id": f.id,
                "bbox": (
                    [f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2]
                    if f.bbox_x1 is not None
                    and f.bbox_y1 is not None
                    and f.bbox_x2 is not None
                    and f.bbox_y2 is not None
                    else None
                ),
                "cluster_id": f.cluster_id,
                "det_score": f.det_score,
                "quality": f.quality,
            }
            for f in meta.faces
        ],
    }


__all__ = ["router"]
