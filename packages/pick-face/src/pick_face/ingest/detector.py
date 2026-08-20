"""Detector interface + Protocol (docs/03 §3 + docs/09 §4).

A Detector consumes a BGR image and returns one Detection per detected face,
plus the aligned 112x112 RGB chip used as input to the Embedder. InsightFace's
`FaceAnalysis.get()` does detect+align+embed in one shot, so the canonical
implementation collapses all three steps into a single struct. We keep the
three Protocols separate so unit tests / alternative embedders (e.g. face.evoLVe
+ WebFace4M with a permissive license) can plug in cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class Detection:
    """One detected face, plus the aligned chip ready for embedding."""

    bbox: tuple[float, float, float, float]  # (x1, y1, x2, y2) in image pixels
    det_score: float  # 0..1, post det_thresh
    landmarks: np.ndarray  # (5, 2) float32: eye-L, eye-R, nose, mouth-L, mouth-R
    chip: np.ndarray  # (112, 112, 3) RGB uint8 — the aligned face
    quality: float = 0.0  # optional sharpness/blur score (0..1)


@runtime_checkable
class Detector(Protocol):
    """Detect faces in a BGR image and produce aligned chips."""

    name: str
    model_version: str

    def detect(self, bgr: np.ndarray) -> list[Detection]: ...
    def warmup(self, det_size: tuple[int, int]) -> None:
        """Optional: pre-allocate internal buffers with a zero-image pass.
        Implementations may no-op; declared in the Protocol so the caller
        doesn't need isinstance checks.
        """
        ...


@runtime_checkable
class Embedder(Protocol):
    """Map a 112x112 RGB chip → 512-D L2-normalized embedding."""

    dim: int  # 512 for ArcFace w600k_r50
    model_version: str

    def embed(self, chip_rgb: np.ndarray) -> np.ndarray:
        """Returns shape (dim,) float32, L2-normalized."""
        ...


def detection_from_insightface(face: object, chip: np.ndarray) -> Detection:
    """Adapter: InsightFace's `Face` NamedTuple → our Detection.

    Lives here (not in the insightface impl module) so unit tests can use it
    with mock faces without importing onnxruntime.
    """
    bbox = tuple(map(float, face.bbox))  # type: ignore[attr-defined]
    return Detection(
        bbox=bbox,  # type: ignore[arg-type]
        det_score=float(face.det_score),  # type: ignore[attr-defined]
        landmarks=np.asarray(face.kps, dtype=np.float32),  # type: ignore[attr-defined]
        chip=chip,
        quality=_rough_quality(chip),
    )


# v1.x re-export: Aligner moved to pick_face.ingest.align in route B.
# Keep the old import path working so third-party plugins built against
# v1.x keep loading.
from pick_face.ingest.align import Aligner  # noqa: E402, F401


def _rough_quality(chip: np.ndarray) -> float:
    """Variance-of-Laplacian blur score, normalised to [0, 1] heuristically.

    InsightFace doesn't expose a quality model; the cluster stage only uses
    this as a *relative* signal (low_quality thresholding in docs/04 §3.1).
    The constants were eyeballed on a few real photos — they're not magic,
    just enough to separate "blurry" from "obviously sharp".
    """
    import cv2

    if chip.ndim == 3:
        gray = cv2.cvtColor(chip, cv2.COLOR_RGB2GRAY)
    else:
        gray = chip
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # 100 ≈ sharp; 5 ≈ very blurry. Soft-knee squash keeps it bounded.
    import math

    if lap_var <= 0:
        return 0.0
    score = 1.0 - math.exp(-lap_var / 100.0)
    return max(0.0, min(1.0, score))


def chip_path_for(detection_id: int, out_dir: Path | None = None) -> Path:
    """Stable cache path for saving aligned chips to disk (used by debug)."""
    if out_dir is None:
        from pick_face.core.paths import cache_dir

        out_dir = cache_dir() / "chips"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{detection_id:08d}.jpg"
