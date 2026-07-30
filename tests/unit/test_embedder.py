"""Tests for pick_face.embedder (pure-math helpers; no model load)."""

from __future__ import annotations

import math

import numpy as np


def test_l2_normalize_handles_zero_vector() -> None:
    from pick_face.embedder import l2_normalize

    z = np.zeros(8, dtype=np.float32)
    out = l2_normalize(z)
    assert np.array_equal(out, z)


def test_l2_normalize_unit_length_output() -> None:
    from pick_face.embedder import l2_normalize

    v = np.array([3.0, 4.0, 0.0, -12.0, 5.0, 0.0, 1.0, 1.0], dtype=np.float32)
    out = l2_normalize(v)
    norm = float(np.linalg.norm(out))
    assert abs(norm - 1.0) < 1e-6


def test_l2_normalize_batched() -> None:
    from pick_face.embedder import l2_normalize

    a = np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float32)
    out = l2_normalize(a)
    for row in out:
        norm = float(np.linalg.norm(row))
        if norm == 0:
            assert np.array_equal(row, np.zeros_like(row))
        else:
            assert abs(norm - 1.0) < 1e-6


def test_cosine_distance_diagonal_is_zero() -> None:
    from pick_face.embedder import cosine_distance_matrix, l2_normalize

    rng = np.random.default_rng(0)
    a = rng.standard_normal((5, 512)).astype(np.float32)
    a = l2_normalize(a)
    d = cosine_distance_matrix(a)
    diag = np.diag(d)
    assert np.allclose(diag, 0.0, atol=1e-5)


def test_cosine_distance_self_loop_is_zero_for_unit_vec() -> None:
    from pick_face.embedder import cosine_distance_matrix, l2_normalize

    rng = np.random.default_rng(1)
    a = rng.standard_normal((3, 16)).astype(np.float32)
    a = l2_normalize(a)
    d = cosine_distance_matrix(a)
    assert math.isclose(d[0, 0], 0.0, abs_tol=1e-5)
    # Off-diagonal is bounded in [0, 2]
    for i in range(3):
        for j in range(3):
            if i == j:
                continue
            assert 0.0 <= d[i, j] <= 2.0
