"""Aligner: 5-point landmarks → 112x112 RGB chip.

Reference: docs/09 §5 (ArcFace-style alignment, 5 landmarks).

We avoid hard-importing onnxruntime/insightface; this module is pure-numpy +
OpenCV, so the unit-test suite never needs the 100+ MB InsightFace pack.
"""

from __future__ import annotations

import numpy as np

# ArcFace reference 5 points (canonical 112x112 face):
#  - left eye, right eye, nose, left mouth corner, right mouth corner.
ARCFACE_REFERENCE_5P: np.ndarray = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def estimate_similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Estimate 2x3 similarity (rotation + uniform scale + translation) from
    5 src points to 5 dst points.

    Closed-form via Umeyama on a square matrix reduction; for 5 points with
    the same shape this is exactly the InsightFace `FaceAnalysis` reference
    pipeline (skipping the yaw/pitch normalization that ArcFace ships with).
    """
    assert src.shape == dst.shape and src.shape[1] == 2 and src.shape[0] >= 2
    src = src.astype(np.float64)
    dst = dst.astype(np.float64)

    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_c = src - src_mean
    dst_c = dst - dst_mean

    # Centroid variance → uniform scale factor.
    src_var = (src_c**2).sum() / src.shape[0]
    if src_var <= 0:
        # Degenerate: src is a single point, fall back to identity similarity.
        return np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)

    # Cross-covariance matrix for rotation estimation.
    h = src_c.T @ dst_c / src.shape[0]
    u, s, vt = np.linalg.svd(h)
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0:
        vt[-1] *= -1
        rot = vt.T @ u.T

    scale = (s.sum()) / src_var
    t = dst_mean - scale * (rot @ src_mean)
    M = np.empty((2, 3), dtype=np.float32)  # noqa: N806 — affine matrix
    M[:2, :2] = scale * rot
    M[:, 2] = t
    return M


def warp_to_112(bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """Warp *bgr* so that *landmarks* aligns with ARCFACE_REFERENCE_5P.

    Returns the 112x112 RGB chip ready for ArcFace ingestion. Input image
    must be uint8 BGR (or RGB — we treat channels opaquely).
    """
    import cv2

    affine = estimate_similarity_transform(landmarks.astype(np.float32), ARCFACE_REFERENCE_5P)
    chip_bgr = cv2.warpAffine(
        bgr,
        affine,
        (112, 112),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return chip_bgr[..., ::-1].copy()  # BGR → RGB contiguous


def warp_affine_batch(bgrs: list[np.ndarray], landmarks_list: list[np.ndarray]) -> list[np.ndarray]:
    """Apply warp_to_112 to many faces; returns list of 112x112 RGB chips."""
    return [warp_to_112(b, kps) for b, kps in zip(bgrs, landmarks_list, strict=False)]
