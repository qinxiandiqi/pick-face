"""pick-face FastAPI routers (v3 Web service).

Thin HTTP layer over `service/`. Routes follow `docs/03 §2` HTTP API contract.

* `api/config.py`  — /api/config (path whitelist CRUD)
* `api/scan.py`    — /api/scan (start/pause/cancel + SSE progress)
* `api/persons.py` — /api/persons (virtual albums + cover)
* `api/photos.py`  — /api/photos (Range streaming + thumbnails)
* `api/review.py`  — /api/review (rename/merge — M6 placeholder)
* `api/health.py`  — /api/health (liveness + worker state)
"""

from __future__ import annotations
