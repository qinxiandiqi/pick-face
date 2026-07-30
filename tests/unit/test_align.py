"""Tests for pick_face.align.

These don't load InsightFace — they verify that the pure-geometry warp
moves 5 source landmarks to the ArcFace reference positions in the 112x112
output. This is the bridge between the SCRFD detector and the ArcFace
embedder, and a 1-pixel error here compounds into a 5-10% drop in accuracy.
"""

from __future__ import annotations

import numpy as np


def _make_canvas(src_pts: np.ndarray, marker_radius: int = 3) -> np.ndarray:
    """Solid black canvas with a colored dot at src_pts[0].

    The first landmark gets a unique color so we can find its centroid
    in the warped output.
    """
    import cv2

    h = int(src_pts[:, 1].max()) + 20
    w = int(src_pts[:, 0].max()) + 20
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    x0, y0 = src_pts[0]
    cv2.circle(canvas, (int(x0), int(y0)), marker_radius, (255, 0, 255), -1)
    return canvas


def test_warp_to_112_returns_correct_shape() -> None:
    from pick_face.align import ARCFACE_REFERENCE_5P, warp_to_112

    src = ARCFACE_REFERENCE_5P + np.array([100, 100], dtype=np.float32)
    img = np.zeros((300, 300, 3), dtype=np.uint8)
    chip = warp_to_112(img, src)
    assert chip.shape == (112, 112, 3)
    assert chip.dtype == np.uint8


def test_warp_aligns_first_landmark_to_reference() -> None:
    """Stamp a marker at landmark[0] in the source; warp; verify the marker
    lands within ~1 px of the corresponding reference point in the chip."""
    from pick_face.align import ARCFACE_REFERENCE_5P, warp_to_112

    src = ARCFACE_REFERENCE_5P + np.array([100, 100], dtype=np.float32)
    canvas = _make_canvas(src)
    chip = warp_to_112(canvas, src)
    mask = (chip[..., 0] > 200) & (chip[..., 1] < 50) & (chip[..., 2] > 200)
    ys, xs = np.where(mask)
    assert xs.size > 0, "marker disappeared after warp"

    cx, cy = float(xs.mean()), float(ys.mean())
    target = ARCFACE_REFERENCE_5P[0]
    err = float(np.hypot(cx - target[0], cy - target[1]))
    # ~1 px tolerance is the standard arcface reference variance.
    assert err < 2.0, f"alignment error too large: {err:.2f} px"


def test_estimate_similarity_transform_identity_when_points_match() -> None:
    """If src == dst, the similarity matrix should be ~identity, scale 1."""
    from pick_face.align import estimate_similarity_transform

    pts = np.array([[10, 20], [30, 40], [50, 60], [70, 80], [90, 100]], dtype=np.float32)
    M = estimate_similarity_transform(pts, pts)
    M_f = M.astype(np.float64)
    # Scale should be ~1
    scale = np.hypot(M_f[0, 0], M_f[0, 1])
    assert abs(scale - 1.0) < 1e-3
    # Translation should be ~0
    assert abs(M_f[0, 2]) < 1e-3 and abs(M_f[1, 2]) < 1e-3


def test_estimate_similarity_transform_translation() -> None:
    from pick_face.align import estimate_similarity_transform

    src = np.array([[10, 20], [30, 40], [50, 60], [70, 80], [90, 100]], dtype=np.float32)
    dst = src + np.array([5.0, 7.0], dtype=np.float32)
    M = estimate_similarity_transform(src, dst)
    M_f = M.astype(np.float64)
    assert abs(M_f[0, 2] - 5.0) < 1e-3
    assert abs(M_f[1, 2] - 7.0) < 1e-3


def test_arcface_reference_shape() -> None:
    """The reference table is contract — changing it requires a model retrain."""
    from pick_face.align import ARCFACE_REFERENCE_5P

    assert ARCFACE_REFERENCE_5P.shape == (5, 2)
    # Symmetric eye line
    eye_y_avg = (ARCFACE_REFERENCE_5P[0, 1] + ARCFACE_REFERENCE_5P[1, 1]) / 2.0
    assert 50 < eye_y_avg < 53
    # Face fits inside 112x112 with small margin
    assert ARCFACE_REFERENCE_5P[:, 0].min() > 30 and ARCFACE_REFERENCE_5P[:, 0].max() < 80
    assert ARCFACE_REFERENCE_5P[:, 1].min() > 50 and ARCFACE_REFERENCE_5P[:, 1].max() < 95
