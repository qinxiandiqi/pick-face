"""pick-face Web service entry points (v3).

* `web_cli` — Typer CLI: `pick-face-web init / serve / migrate`
* `app`     — FastAPI application factory (mounted by `web_cli serve`)
* `static/` — placeholder for the SPA build output
"""

from __future__ import annotations
