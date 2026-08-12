"""pick-face Web service entry points (v3).

* ``web_cli``      — ``pick-face-web {init,serve,migrate}`` CLI
                      (see :mod:`pick_face.web_cli`).
* ``static/``      — placeholder for the SPA build output. The real
                      React + Vite build from the ``apps/web/`` repo
                      (M7) lands here at install time; M6 ships a
                      simple ``index.html`` so the static mount is
                      observable end-to-end.
"""

from __future__ import annotations
