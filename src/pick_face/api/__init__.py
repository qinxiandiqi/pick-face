"""pick-face FastAPI routers (v3 Web service).

Thin HTTP layer over :mod:`pick_face.service`. Routes follow the
``docs/03 §2`` HTTP API contract.

Public routers in this package (mounted by :func:`pick_face.api.app.create_app`):

* :mod:`pick_face.api.config`   — ``/api/config``   (path whitelist CRUD)
* :mod:`pick_face.api.scan`     — ``/api/scan``     (start/pause/cancel + SSE progress)
* :mod:`pick_face.api.persons`  — ``/api/persons``  (virtual albums + cover)
* :mod:`pick_face.api.photos`   — ``/api/photos``   (Range streaming + thumbnails)
* :mod:`pick_face.api.health`   — ``/api/health`` + ``/api/ready`` (liveness)

``/api/review`` (rename/merge/delete) lands in M9; the route table
is wired in :mod:`pick_face.api.app` once the review service exists.
"""

from __future__ import annotations
