"""pick-face service layer (v3 Web service).

The service layer sits between the FastAPI routers (`api/`) and the
algorithm core (`ingest/`, `store/`, `platform/`). It holds:

* application root resolution (`paths`) — PICK_FACE_HOME / ~/.pick-face
* path-whitelist CRUD (`config_service`)
* scan task orchestration (`scan_service`, `worker/scan_worker`)
* person-album read API (`person_service`)
* photo streaming + thumbnail cache (`photo_service`)

Service layer never imports FastAPI — that's the api/ package's job.
"""

from __future__ import annotations
