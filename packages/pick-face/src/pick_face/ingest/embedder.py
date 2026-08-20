"""Embedder interface + L2-normalization helpers.

A minimal Embedder here is just `numpy`-based — face crops come in as
already-aligned 112x112 RGB chips, and the embedder returns a 512-D float32
vector. The InsightFace-backed implementation lives in
`pick_face.platform.runtime.face_runtime` so unit tests don't pay the 100+MB
model download cost to exercise the dataclass shape.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Embedder(Protocol):
    """Maps a 112x112 RGB uint8 chip → 512-D L2-normalized float32 vector."""

    dim: int
    model_version: str

    def embed(self, chip_rgb: np.ndarray) -> np.ndarray:
        """Returns shape (self.dim,) float32, L2-normalized."""
        ...


def l2_normalize(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """L2-normalize a 1-D or 2-D (N, D) array along the last axis."""
    if v.ndim == 1:
        n = np.linalg.norm(v)
        if n < eps:
            return v
        return v / n
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n = np.where(n < eps, 1.0, n)
    return (v / n).astype(v.dtype, copy=False)


def cosine_distance_matrix(embs: np.ndarray) -> np.ndarray:
    """Pairwise cosine *distance* (1 - cosine similarity) between rows of *embs*.

    Assumes *embs* is (N, D), already L2-normalized.
    """
    assert embs.ndim == 2
    sim = embs @ embs.T
    # Numerical jitter: clamp to [-1, 1] to keep sim diags sane.
    sim = np.clip(sim, -1.0, 1.0)
    return 1.0 - sim
