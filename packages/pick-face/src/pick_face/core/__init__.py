"""Core infrastructure: config, errors, hashing, paths, image decoding.

Lowest layer of the dependency DAG. Other sub-packages may depend on
this, but this layer never imports from any other pick_face sub-package.
"""

from __future__ import annotations

__all__: list[str] = []
