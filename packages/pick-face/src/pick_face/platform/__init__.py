"""Platform & ops: ONNX provider probe, model management, benchmarks.

Concerns that don't fit ingest/store/output: figuring out which GPU
runtime to use, downloading model weights under strict licence gates,
and measuring performance. Depend on core/ and ingest/.
"""

from __future__ import annotations

__all__: list[str] = []
