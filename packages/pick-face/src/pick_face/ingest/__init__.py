"""Ingest pipeline: scan, detect, align, embed, cluster.

Turns a directory of photos into a SQLite table of face embeddings
clustered into persons. Depend on core/.
"""

from __future__ import annotations

__all__: list[str] = []
