"""Person-album HTTP surface — `docs/03 §2.3` + `docs/01 §1.3`.

Routes:

- ``GET /api/persons``            list persons (paginated, by face_count desc)
- ``GET /api/persons/count``      total non-merged cluster count
- ``GET /api/persons/{id}``       detail incl. distinct scan roots
- ``GET /api/persons/{id}/photos`` distinct photos in this cluster
- ``GET /api/persons/{id}/cover``  cover path + face bbox

The cover route returns the (path, face_id) tuple consumed by the
chip pipeline in M7. For M6 we just hand the SPA the file path so
it can render a stub "cover" until chips are generated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from pick_face.api.deps import get_person_service
from pick_face.service.person_service import PersonService

router = APIRouter(prefix="/api/persons", tags=["persons"])


@router.get("")
def list_persons(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    svc: PersonService = Depends(get_person_service),
) -> dict[str, Any]:
    persons = svc.list_persons(limit=limit, offset=offset)
    return {
        "count": svc.count_persons(),
        "limit": limit,
        "offset": offset,
        "persons": [
            {
                "id": p.id,
                "label": p.label,
                "face_count": p.face_count,
                "photo_count": p.photo_count,
            }
            for p in persons
        ],
    }


@router.get("/count")
def count_persons(
    svc: PersonService = Depends(get_person_service),
) -> dict[str, int]:
    return {"count": svc.count_persons()}


@router.get("/{person_id}")
def get_person(
    person_id: int,
    svc: PersonService = Depends(get_person_service),
) -> dict[str, Any]:
    detail = svc.get_person(person_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="person not found")
    return {
        "id": detail.id,
        "label": detail.label,
        "face_count": detail.face_count,
        "photo_count": detail.photo_count,
        "sources": list(detail.sources),
    }


@router.get("/{person_id}/photos")
def get_person_photos(
    person_id: int,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    svc: PersonService = Depends(get_person_service),
) -> dict[str, Any]:
    detail = svc.get_person(person_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="person not found")
    return {
        "person_id": person_id,
        "limit": limit,
        "offset": offset,
        "photos": svc.get_person_photos(person_id, limit=limit, offset=offset),
    }


@router.get("/{person_id}/cover")
def get_person_cover(
    person_id: int,
    svc: PersonService = Depends(get_person_service),
) -> dict[str, Any]:
    cover = svc.get_person_cover(person_id)
    if cover is None:
        raise HTTPException(status_code=404, detail="person has no cover")
    path, face_id = cover
    return {
        "person_id": person_id,
        "face_id": face_id,
        "path": str(path),
        # M7: also return chip_path once the chip worker lands.
        "chip_path": None,
    }


__all__ = ["router"]
