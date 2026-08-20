"""pick-face background workers (v3 Web service).

* `scan_worker` — consume asyncio.Queue, run scanner+detector+embedder
* `cluster_worker` — periodic HDBSCAN re-cluster (M8; placeholder in M6)
"""

from __future__ import annotations
