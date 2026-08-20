"""Path-whitelist HTTP surface — `docs/03 §2.1`.

Five routes:

- ``GET    /api/config/paths``     list all whitelisted paths
- ``GET    /api/config/paths/enabled``  list only enabled paths (used by worker)
- ``POST   /api/config/paths``     add a new path (request body: path + notes)
- ``DELETE /api/config/paths/{id}``     remove a path by id
- ``PATCH  /api/config/paths/{id}``     toggle enabled flag

All mutating endpoints respond in JSON. Errors carry the stable
``code`` from :class:`PathValidationError` so the SPA can branch on
``code`` rather than parsing human-readable messages.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from pick_face.api.deps import get_config_service
from pick_face.service.config_service import (
    ConfigService,
    PathValidationError,
    ScanPath,
)

router = APIRouter(prefix="/api/config", tags=["config"])


class AddPathRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Absolute path to whitelist")
    notes: str = Field(default="", description="Optional human-readable note")


class TogglePathRequest(BaseModel):
    enabled: bool


def _serialize(sp: ScanPath) -> dict[str, object]:
    return sp.to_dict()


@router.get("/paths")
def list_paths(
    svc: ConfigService = Depends(get_config_service),
) -> dict[str, list[dict[str, object]]]:
    return {"paths": [_serialize(sp) for sp in svc.list_paths()]}


@router.get("/paths/enabled")
def list_enabled_paths(
    svc: ConfigService = Depends(get_config_service),
) -> dict[str, list[str]]:
    return {"paths": [str(p) for p in svc.enabled_paths()]}


@router.post(
    "/paths",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Path validation failed"},
        409: {"description": "Path already whitelisted"},
    },
)
def add_path(
    body: AddPathRequest,
    svc: ConfigService = Depends(get_config_service),
) -> dict[str, object]:
    try:
        sp = svc.add_path(body.path, notes=body.notes)
    except PathValidationError as exc:
        # Map stable codes to HTTP status. See docs/03 §2.1 error contract.
        status_map = {
            PathValidationError.NOT_FOUND: status.HTTP_404_NOT_FOUND,
            PathValidationError.NOT_A_DIRECTORY: status.HTTP_400_BAD_REQUEST,
            PathValidationError.NOT_READABLE: status.HTTP_403_FORBIDDEN,
            PathValidationError.PATH_TRAVERSAL: status.HTTP_400_BAD_REQUEST,
            PathValidationError.DUPLICATE: status.HTTP_409_CONFLICT,
            PathValidationError.NOT_WHITELISTED: status.HTTP_403_FORBIDDEN,
        }
        raise HTTPException(
            status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return _serialize(sp)


@router.delete("/paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_path(
    path_id: Annotated[int, ...],
    svc: ConfigService = Depends(get_config_service),
) -> None:
    if not svc.remove_path(path_id):
        raise HTTPException(status_code=404, detail="path id not found")


@router.patch("/paths/{path_id}")
def toggle_path(
    path_id: Annotated[int, ...],
    body: TogglePathRequest,
    svc: ConfigService = Depends(get_config_service),
) -> dict[str, object]:
    if not svc.set_enabled(path_id, body.enabled):
        raise HTTPException(status_code=404, detail="path id not found")
    # Find the now-toggled row and return it.
    for sp in svc.list_paths():
        if sp.id == path_id:
            return _serialize(sp)
    raise HTTPException(status_code=404, detail="path id not found")  # pragma: no cover


__all__ = ["router"]
