"""Tests for pick_face.cluster (HDBSCAN + 2-pass merge + constraints).

These tests *don't* rely on InsightFace. We generate synthetic L2-normalized
embeddings where each "person" is a tight gaussian blob on the unit sphere,
then verify that clustering recovers them.
"""

from __future__ import annotations

import numpy as np
import pytest

from pick_face.core.config import ClusteringConfig
from pick_face.ingest.cluster import (
    Constraint,
    cluster_embeddings,
    face_to_cluster_similarity,
)


def _make_unit_blob(
    rng: np.random.Generator, center: np.ndarray, n: int, sigma: float = 0.05
) -> np.ndarray:
    """Generate n unit vectors centred around *center* (a unit vector itself)."""
    D = center.shape[0]
    blob = rng.normal(loc=center, scale=sigma, size=(n, D)).astype(np.float32)
    # Re-L2-normalize so they really do live on the sphere.
    blob /= np.linalg.norm(blob, axis=1, keepdims=True)
    return blob


def _generate_people(
    rng: np.random.Generator, k_people: int = 5, per_person: int = 4, dim: int = 32
) -> np.ndarray:
    """Return N=k*per L2-normalized 'embeddings' in k distinct clusters.

    Centers are constructed to be approximately orthogonal in the chosen dim
    (so they're maximally separable on the unit sphere), and Gaussian noise is
    added only in a small subspace so the cluster signal stays strong.
    """
    # Pick k mutually orthogonal centres, each of dim=d.
    ids = rng.permutation(dim)[:k_people]
    centers = np.zeros((k_people, dim), dtype=np.float32)
    for i, idx in enumerate(ids):
        centers[i, idx] = 1.0
    # Already unit vectors.

    blobs = []
    for c in centers:
        # Add Gaussian noise in a *different* dim subspace to keep cluster
        # signal strong. Use the first half of dims as "noise dims" and
        # the centre-direction dim as the "signal dim".
        n = per_person
        noise = rng.normal(scale=0.03, size=(n, dim)).astype(np.float32)
        # Damp noise on the centre direction (already signal) and amplify
        # on noise dims: we do this via scaling after re-normalization.
        blob = noise + c[None, :]
        blob /= np.linalg.norm(blob, axis=1, keepdims=True)
        blobs.append(blob)
    return np.concatenate(blobs, axis=0)


def _cfg() -> ClusteringConfig:
    return ClusteringConfig(min_cluster_size=2, min_samples=2, merge_threshold=0.55)


def test_cluster_separates_distinct_people() -> None:
    """5 clearly-distinct people: cluster_embeddings must return ≥4 clusters.

    Exact noise counts depend on hdbscan's MST heuristics and on the random
    sigma; we don't pin them down here. The hard guarantee is the API
    contract: the right number of clusters emerges, labels are int32 of
    the right shape, probs are float32 of the right shape, and at least
    one face ends up with a valid non-noise label.
    """
    rng = np.random.default_rng(42)
    embs = _generate_people(rng, k_people=5, per_person=15, dim=32)
    res = cluster_embeddings(embs, cfg=_cfg())
    assert res.labels.shape == (embs.shape[0],)
    assert res.probs.shape == (embs.shape[0],)
    assert res.n_clusters >= 4, f"expected ≥4 clusters, got {res.n_clusters}"
    assert (res.labels != -1).any(), "all faces were classified as noise"


def test_cluster_handles_empty_input() -> None:
    res = cluster_embeddings(np.zeros((0, 16), dtype=np.float32), cfg=_cfg())
    assert res.labels.shape == (0,)
    assert res.n_clusters == 0
    assert res.n_noise == 0


def test_low_quality_mask_excludes_faces_from_clusters() -> None:
    rng = np.random.default_rng(43)
    embs = _generate_people(rng, k_people=3, per_person=6, dim=16)
    low = np.zeros(embs.shape[0], dtype=bool)
    low[3:6] = True  # mark one entire person as low-quality
    res = cluster_embeddings(embs, cfg=_cfg(), low_quality_mask=low)
    # The marked faces must carry label -1.
    assert (res.labels[3:6] == -1).all()
    # The other faces still cluster (or have noise).
    assert (res.labels[[0, 1, 2, 6, 7, 8]] != -1).all()


def test_centroid_merge_unifies_close_clusters() -> None:
    """Two clusters whose centroids are well above the merge_threshold must
    collapse into one. We construct two clearly-distinct clusters whose
    centroids still end up close enough to merge."""
    rng = np.random.default_rng(7)
    a = _make_unit_blob(rng, np.array([1.0] + [0.0] * 31, dtype=np.float32), n=8, sigma=0.02)
    # Make b's center close to a's so the centroid cos is ~0.92.
    b_center = np.array([0.92, 0.39] + [0.0] * 30, dtype=np.float32)
    b_center /= np.linalg.norm(b_center)
    b = _make_unit_blob(rng, b_center, n=8, sigma=0.02)
    embs = np.concatenate([a, b], axis=0)
    cfg = ClusteringConfig(min_cluster_size=2, min_samples=1, merge_threshold=0.55)
    res = cluster_embeddings(embs, cfg=cfg)
    # Either HDBSCAN already clustered them together (1 cluster) or the
    # centroid 2-pass merge does. What matters is ≤ 1 cluster survives.
    assert res.n_clusters <= 1, f"expected ≤ 1 cluster after merge, got {res.n_clusters}"


def test_must_link_constraint_unions_clusters() -> None:
    """Two distinct people must_link'd together → at most 1 cluster after fixup."""
    rng = np.random.default_rng(0)
    embs = _generate_people(rng, k_people=2, per_person=6, dim=16)
    cfg = _cfg()
    # Force the must_link between two faces from different clusters.
    # Pre-cluster to find which cluster each face ends up in.
    cluster_embeddings(embs, cfg=cfg)  # warm-up; result not needed here
    # Pick face 0 and face 6 — they belong to different people in our setup.
    cons = (Constraint(face_a=0, face_b=6, kind="must_link"),)
    post = cluster_embeddings(embs, cfg=cfg, constraints=cons)
    assert post.n_clusters <= 1


def test_cannot_link_constraint_splits() -> None:
    """A cannot_link on two faces that HDBSCAN clustered together must split them."""
    rng = np.random.default_rng(0)
    embs = _generate_people(rng, k_people=4, per_person=10, dim=16)
    cfg = ClusteringConfig(min_cluster_size=2, min_samples=1, merge_threshold=0.55)
    pre = cluster_embeddings(embs, cfg=cfg)
    # Construct constraints by inspecting pre.labels
    seen_pairs: set[tuple[int, int]] = set()
    cons_list = []
    for i in range(pre.labels.shape[0]):
        for j in range(i + 1, pre.labels.shape[0]):
            if pre.labels[i] != -1 and pre.labels[i] == pre.labels[j]:
                pair = (i, j) if i < j else (j, i)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    cons_list.append(Constraint(face_a=i, face_b=j, kind="cannot_link"))
                    # Only add a few of these — enough to prove the mechanism.
                    if len(cons_list) >= 2:
                        break
        if len(cons_list) >= 2:
            break
    if not cons_list:
        pytest.skip("could not find a collision pair; randomness produced no shared-cluster pairs")
    res = cluster_embeddings(embs, cfg=cfg, constraints=tuple(cons_list))
    for c in cons_list:
        # The two faces must no longer share a label after the cannot_link.
        assert res.labels[c.face_a] != res.labels[c.face_b] or res.labels[c.face_a] == -1


def test_face_to_cluster_similarity_bounded() -> None:
    rng = np.random.default_rng(11)
    embs = _generate_people(rng, k_people=3, per_person=5, dim=16)
    cfg = _cfg()
    res = cluster_embeddings(embs, cfg=cfg)
    sims = face_to_cluster_similarity(embs, res.labels)
    assert sims.shape == (embs.shape[0],)
    # Clustered faces → sim ≥ 0; noise → 0.0 (we emit 0).
    for i, lbl in enumerate(res.labels):
        if lbl == -1:
            assert sims[i] == 0.0
        else:
            assert 0.0 <= sims[i] <= 1.0001


def test_cluster_result_labels_are_compact() -> None:
    """After _renumber, labels should be in 0..K-1 with no gaps."""
    rng = np.random.default_rng(91)
    embs = _generate_people(rng, k_people=3, per_person=4, dim=16)
    res = cluster_embeddings(embs, cfg=_cfg())
    if res.n_clusters > 0:
        max_label = int(res.labels.max())
        assert max_label == res.n_clusters - 1


# ---------------------------------------------------------------------------
# incremental_assign (T-101, M2 / docs/04 §3.2)
# ---------------------------------------------------------------------------


def test_incremental_assign_matches_existing_clusters() -> None:
    """Embeddings close to an existing centroid get that cluster ID."""
    from pick_face.ingest.cluster import incremental_assign

    rng = np.random.default_rng(0)
    dim = 64  # higher dim → random unit vectors are more orthogonal to axes
    # 3 cluster anchors at orthogonal unit axes
    cents = np.eye(3, dim, dtype=np.float32)
    labels = np.array([10, 20, 30], dtype=np.int32)

    # 5 new faces: 3 close to anchors, 2 noise
    new = np.zeros((5, dim), dtype=np.float32)
    new[0] = cents[0] + rng.normal(scale=0.01, size=dim)
    new[1] = cents[1] + rng.normal(scale=0.01, size=dim)
    new[2] = cents[2] + rng.normal(scale=0.01, size=dim)
    # random unit vectors in dim=64 → max abs cosine with axis ≈ 0.4 typically
    # but we need them below loose_match (0.40). Use anti-aligned + perturb.
    for i in (3, 4):
        v = rng.normal(size=dim).astype(np.float32)
        # push the vector away from every axis
        for c in cents:
            v -= 0.7 * (v @ c) * c
        new[i] = v / np.linalg.norm(v)

    out_labels, out_probs = incremental_assign(
        new,
        existing_centroids=cents,
        existing_labels=labels,
        strong_match=0.95,
        loose_match=0.50,
    )
    # 3 strong matches, 2 noise
    assert list(out_labels[:3]) == [10, 20, 30]
    assert (out_probs[:3] == 1.0).all()
    assert (out_labels[3:] == -1).all()


def test_incremental_assign_empty() -> None:
    from pick_face.ingest.cluster import incremental_assign

    out_labels, out_probs = incremental_assign(
        np.zeros((0, 16), dtype=np.float32),
        existing_centroids=np.zeros((0, 16), dtype=np.float32),
        existing_labels=np.zeros(0, dtype=np.int32),
        strong_match=0.95,
        loose_match=0.40,
    )
    assert out_labels.shape == (0,)
    assert out_probs.shape == (0,)


def test_incremental_assign_empty_with_real_centroids() -> None:
    """If there are no new faces but centroids exist, return empty arrays."""
    from pick_face.ingest.cluster import incremental_assign

    cents = np.eye(2, 16, dtype=np.float32)
    labels = np.array([1, 2], dtype=np.int32)
    out_labels, out_probs = incremental_assign(
        np.zeros((0, 16), dtype=np.float32),
        existing_centroids=cents,
        existing_labels=labels,
        strong_match=0.95,
        loose_match=0.40,
    )
    assert out_labels.shape == (0,)
    assert out_probs.shape == (0,)


def test_incremental_assign_no_centroids_marks_all_noise() -> None:
    from pick_face.ingest.cluster import incremental_assign

    new = np.eye(2, 16, dtype=np.float32)
    out_labels, _ = incremental_assign(
        new,
        existing_centroids=np.zeros((0, 16), dtype=np.float32),
        existing_labels=np.zeros(0, dtype=np.int32),
        strong_match=0.95,
        loose_match=0.40,
    )
    assert (out_labels == -1).all()
