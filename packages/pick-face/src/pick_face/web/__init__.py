"""pick-face Web service entry points (v3).

* ``web_cli``      — ``pick-face-web {init,serve,migrate}`` CLI
                      (see :mod:`pick_face.web_cli`).
* ``static/``      — SPA build output (gitignored; rebuilt by CI via
                      ``cd packages/web-ui && pnpm build``). FastAPI
                      mounts it at ``/`` — see
                      :mod:`pick_face.api.app`. Hatchling wheel
                      packaging picks the directory up automatically
                      as package data.
* SPA source      — Vite + React + TypeScript + Tailwind + shadcn/ui
                      tree lives at the monorepo root in
                      ``packages/web-ui/``. The wheel ships the
                      pre-built ``static/`` bundle; the SPA source
                      itself is excluded from sdist (see
                      ``pyproject.toml`` ``[tool.hatch.build.targets.sdist]``).
                      See the root ``README.md`` §Quick start for the
                      ``pnpm`` workflow.
"""

from __future__ import annotations
