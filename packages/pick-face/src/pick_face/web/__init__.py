"""pick-face Web service entry points (v3).

* ``web_cli``      — ``pick-face-web {init,serve,migrate}`` CLI
                      (see :mod:`pick_face.web_cli`).
* ``static/``      — SPA build output (gitignored; rebuilt by CI via
                      ``pnpm --dir src/pick_face/web/app build``).
                      FastAPI mounts it at ``/`` — see
                      :mod:`pick_face.api.app`. Hatchling wheel
                      packaging picks the directory up automatically
                      as package data.
* ``app/``         — Vite + React + TypeScript + Tailwind + shadcn/ui
                      SPA source tree. Excluded from sdist
                      (``pyproject.toml`` ``[tool.hatch.build.targets.sdist]``)
                      so PyPI consumers don't need Node; the wheel
                      ships the pre-built ``static/`` bundle instead.
                      See ``README.md`` §Development for ``pnpm`` workflow.
"""

from __future__ import annotations
