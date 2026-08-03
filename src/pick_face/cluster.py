"""Face clustering: HDBSCAN over L2-normalized embeddings + 2-pass centroid merge.

Reference:
- docs/04 §2.4 (HDBSCAN cosine + 2-pass centroid merge)
- docs/04 §3.1 (unified threshold table)
- docs/06 §review constraints (must_link / cannot_link)
- docs/09 §7 (confidence / low_confidence_faces.json)

The canonical pipeline:
  1. Build dense cosine distance matrix D (cosine_distance_matrix).
  2. HDBSCAN with metric='precomputed'. Initial labels include -1 for noise.
  3. Centroid-pass-1: compute L2-normalized cluster centroid per non-noise
     cluster; merge two clusters i, j iff cos(centroid_i, centroid_j) >=
     merge_threshold. Repeat until stable (O(passes² · N) worst-case but
     passes is small in practice).
  4. Apply must_link / cannot_link from review_decision as a final fix-up:
       must_link   — union their clusters
       cannot_link — pull one of them into a new dummy cluster if a peer
                     already occupies it.
  5. Reassign labels to integer IDs; write back to face.cluster_id.

For M1 we keep it pure-numpy + hdbscan; the HNSW optimization (n×n is large)
moves to docs/04 §2.4's top-k nearest-neighbour construct in M3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pick_face.config import ClusteringConfig
from pick_face.embedder import cosine_distance_matrix, l2_normalize


@dataclass(frozen=True)
class ClusterResult:
    labels: np.ndarray     # (N,) int32, cluster IDs in [0, K). -1 == noise.
    probs: np.ndarray      # (N,) float32, HDBSCAN cluster_probability
    n_clusters: int
    n_noise: int


@dataclass(frozen=True)
class Constraint:
    face_a: int
    face_b: int
    kind: str              # "must_link" or "cannot_link"


@dataclass(frozen=True)
class ReviewLink:
    cluster_id: int
    decision_payload: dict | None  # JSON blob from review_decision.payload


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def cluster_embeddings(
    embeddings: np.ndarray,
    *,
    cfg: ClusteringConfig,
    low_quality_mask: np.ndarray | None = None,
    constraints: tuple[Constraint, ...] = (),
) -> ClusterResult:
    """Cluster N face embeddings into ClusterResult.

    Args:
        embeddings: (N, 512) L2-normalized float32.
        cfg: ClusteringConfig with min_cluster_size, min_samples,
             merge_threshold, etc.
        low_quality_mask: (N,) bool — faces with low quality are *excluded*
            from clustering but their embeddings are still indexed back into
            the result for downstream confidence scoring.
        constraints: must_link / cannot_link decisions to apply as a post-fix.

    Returns:
        ClusterResult with labels in the full N-length embedding space; -1
        means "noise or low-quality". Faces that are low-quality get label
        -1 unconditionally so they never pollute a cluster.
    """
    n = embeddings.shape[0]
    if n == 0:
        return ClusterResult(
            labels=np.zeros(0, dtype=np.int32),
            probs=np.zeros(0, dtype=np.float32),
            n_clusters=0,
            n_noise=0,
        )

    embeddings = l2_normalize(embeddings.astype(np.float32, copy=False))
    low_quality_mask = (
        np.zeros(n, dtype=bool) if low_quality_mask is None else low_quality_mask.astype(bool)
    )

    # 1. Initial HDBSCAN over pairwise cosine distances.
    raw_labels, raw_probs = _hdbscan_fit(
        embeddings,
        min_cluster_size=cfg.min_cluster_size,
        min_samples=cfg.min_samples,
    )

    # 2. Centroid 2-pass merge over the surviving (>=0) initial labels.
    merged_labels = _centroid_merge(
        embeddings, raw_labels, merge_threshold=cfg.merge_threshold,
    )

    # 3. Apply review constraints. must_link unions; cannot_link splits.
    if constraints:
        merged_labels = _apply_constraints(merged_labels, constraints)

    # Low-quality faces → label -1 (do not pollute any cluster).
    final_labels = merged_labels.copy()
    final_labels[low_quality_mask] = -1

    # Renumber to 0..K-1 (compact, contiguous).
    final_labels, n_clusters = _renumber(final_labels)

    n_noise = int((final_labels == -1).sum())

    return ClusterResult(
        labels=final_labels.astype(np.int32, copy=False),
        probs=raw_probs.astype(np.float32, copy=False),
        n_clusters=n_clusters,
        n_noise=n_noise,
    )


# ---------------------------------------------------------------------------
# HDBSCAN adapter
# ---------------------------------------------------------------------------


def _hdbscan_fit(
    embeddings: np.ndarray,
    *,
    min_cluster_size: int,
    min_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Run HDBSCAN on the (precomputed-cosine) distance matrix.

    Lazy-imports hdbscan so this module is unit-testable on bare-bones CI.
    """
    try:
        import hdbscan  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "hdbscan is required to cluster embeddings; install with "
            "`uv pip install 'pick-face[dev]'` or `uv pip install hdbscan`."
        ) from e

    D = cosine_distance_matrix(embeddings)
    # HDBSCAN expects double precision for its precomputed distances.
    D = D.astype(np.float64, copy=False)
    np.fill_diagonal(D, 0.0)
    clusterer = hdbscan.HDBSCAN(
        metric="precomputed",
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method="leaf",
        cluster_selection_epsilon=0.0,
    )
    clusterer.fit(D)
    labels = np.asarray(clusterer.labels_, dtype=np.int32)
    probs = np.asarray(clusterer.probabilities_, dtype=np.float32)
    return labels, probs


# ---------------------------------------------------------------------------
# Centroid 2-pass merge
# ---------------------------------------------------------------------------


def _centroid_merge(
    embeddings: np.ndarray,
    labels: np.ndarray,
    *,
    merge_threshold: float,
) -> np.ndarray:
    """Merge clusters whose centroids have cosine similarity ≥ threshold.

    Implementation: union-find over the current label set; iteratively
    compute centroid-to-centroid cosine for cluster pairs above the
    threshold, then re-merge & repeat until stable. In practice this
    converges in 1-3 passes.

    `merge_threshold` here is *similarity* (cos ≥ t), per docs/04 §3.1.
    We convert to a distance cap of (1 - t) for the comparison.
    """
    if (labels == -1).all():
        return labels.copy()

    lbl = labels.copy()
    parents = {int(c): int(c) for c in np.unique(lbl) if c != -1}

    def find(x: int) -> int:
        # Path-compressed find.
        root = x
        while parents[root] != root:
            root = parents[root]
        while parents[x] != root:
            parents[x], x = root, parents[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Stable ID: keep the lower-numbered root (consistent with the
            # "preserve largest cluster" rule in docs/04 §2.4 — for our
            # database-level ID stability we use low ID as proxy because the
            # DB layer captures `merged_into` regardless).
            keep, give = (ra, rb) if ra < rb else (rb, ra)
            parents[give] = keep

    cap = 1.0 - float(merge_threshold)

    # Iterate while any merge happens. Hard cap to avoid pathological cases.
    for _ in range(10):
        centroids: dict[int, np.ndarray] = {}
        members: dict[int, list[int]] = {}
        for i, l in enumerate(lbl):
            if l == -1:
                continue
            root = find(int(l))
            members.setdefault(root, []).append(i)
        for root, idxs in members.items():
            if len(idxs) == 1:
                centroids[root] = embeddings[idxs[0]]
            else:
                c = embeddings[idxs].mean(axis=0)
                norm = np.linalg.norm(c)
                centroids[root] = c / norm if norm > 1e-12 else c

        ids = list(centroids.keys())
        if len(ids) < 2:
            break
        merged_any = False
        # vectorised pairwise sim
        C = np.stack([centroids[i] for i in ids], axis=0)
        sim = C @ C.T
        # We need an identity-friendly iteration that respects the small
        # cluster count: O(K^2) is fine because K << N.
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if (1.0 - sim[i, j]) <= cap:
                    union(ids[i], ids[j])
                    merged_any = True
        if not merged_any:
            break

    # Compress to canonical labels.
    out = np.full_like(lbl, -1)
    roots = sorted({find(int(c)) for c in np.unique(lbl) if c != -1})
    remap = {r: i for i, r in enumerate(roots)}
    for i in range(lbl.shape[0]):
        if lbl[i] != -1:
            out[i] = remap[find(int(lbl[i]))]
    return out


# ---------------------------------------------------------------------------
# Review constraints
# ---------------------------------------------------------------------------


def _apply_constraints(
    labels: np.ndarray,
    constraints: tuple[Constraint, ...],
) -> np.ndarray:
    """Enforce must_link/cannot_link decisions from review_decision."""
    lbl = labels.copy()
    n = lbl.shape[0]

    parents: dict[int, int] = {int(c): int(c) for c in np.unique(lbl) if c != -1}

    def find(x: int) -> int:
        root = x
        while parents[root] != root:
            root = parents[root]
        while parents[x] != root:
            parents[x], x = root, parents[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            keep, give = (ra, rb) if ra < rb else (rb, ra)
            parents[give] = keep

    for c in constraints:
        if c.kind == "must_link":
            if 0 <= c.face_a < n and 0 <= c.face_b < n and lbl[c.face_a] != -1 and lbl[c.face_b] != -1:
                union(int(lbl[c.face_a]), int(lbl[c.face_b]))
        elif c.kind == "cannot_link":
            # If both faces ended up in the same cluster, peel face_b into
            # a fresh singleton cluster so they no longer collide.
            if 0 <= c.face_a < n and 0 <= c.face_b < n:
                ca, cb = int(lbl[c.face_a]), int(lbl[c.face_b])
                if ca != -1 and cb != -1 and find(ca) == find(cb):
                    lbl[c.face_b] = int(lbl.max() + 1) if lbl.max() != -1 else 0
                    parents[int(lbl[c.face_b])] = int(lbl[c.face_b])

    # Final fix-up: write the union-find roots back into a contiguous range.
    out = np.full_like(lbl, -1)
    roots = sorted({find(int(c)) for c in np.unique(lbl) if c != -1})
    remap = {r: i for i, r in enumerate(roots)}
    for i in range(lbl.shape[0]):
        if lbl[i] != -1:
            out[i] = remap[find(int(lbl[i]))]
    return out


def _renumber(labels: np.ndarray) -> tuple[np.ndarray, int]:
    """Compact labels to 0..K-1, preserving order; -1 stays -1."""
    if (labels == -1).all():
        return labels.copy(), 0
    out = np.full_like(labels, -1)
    next_id = 0
    seen: dict[int, int] = {}
    for i, l in enumerate(labels):
        if l == -1:
            continue
        il = int(l)
        if il not in seen:
            seen[il] = next_id
            next_id += 1
        out[i] = seen[il]
    return out, next_id


# ---------------------------------------------------------------------------
# Confidence + threshold helpers (docs/04 §2.5)
# ---------------------------------------------------------------------------


def face_to_cluster_similarity(
    embeddings: np.ndarray,
    labels: np.ndarray,
) -> np.ndarray:
    """For each face, similarity to its cluster's centroid.

    -1 (noise / low-quality) → 0.0.
    Returns float32 (N,) array.
    """
    n = embeddings.shape[0]
    out = np.zeros(n, dtype=np.float32)
    for c in np.unique(labels):
        if c == -1:
            continue
        idx = np.where(labels == c)[0]
        if idx.size == 0:
            continue
        centroid = embeddings[idx].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm < 1e-12:
            continue
        centroid = centroid / norm
        sim = embeddings[idx] @ centroid
        out[idx] = sim.astype(np.float32, copy=False)
    return out


def incremental_assign(
    new_embeddings: np.ndarray,
    *,
    existing_centroids: np.ndarray,
    existing_labels: np.ndarray[int],
    strong_match: float,
    loose_match: float,
) -> tuple[np.ndarray[int], np.ndarray[float]]:
    """Assign N new face embeddings to the closest existing cluster, or
    mark them as noise if no cluster is close enough (M2 / docs/04 §3.2).

    Inputs:
        new_embeddings: (M, 512) L2-normalized float32 — the new faces
            that need labels. These DO NOT include any faces already in
            existing_centroids (the function is incremental).
        existing_centroids: (K, 512) L2-normalized float32 — the centroid
            of each existing cluster. Centroid 0 corresponds to label
            `existing_labels[0]`, etc.
        existing_labels: (K,) int — the cluster IDs in the main DB
            (1..N). These are NOT 0..K-1; they are real cluster row ids.
        strong_match: similarity ≥ this puts the face into the cluster
            unconditionally.
        loose_match:   similarity ≥ this puts the face into the cluster,
            but flagged for human review (cluster_prob reflects distance
            to strong_match). Below this → face stays unassigned (-1).

    Returns:
        (labels, probs): two (M,) int and float32 arrays. labels[i] is
            the assigned cluster id (or -1 for unassigned / noise);
            probs[i] is the *similarity* (not probability) of the
            assignment so the caller can mark low-confidence faces
            downstream.
    """
    if new_embeddings.size == 0 or existing_centroids.size == 0:
        m = new_embeddings.shape[0] if new_embeddings.ndim == 2 else 0
        return (
            np.full(m, -1, dtype=np.int32),
            np.zeros(m, dtype=np.float32),
        )

    embs = l2_normalize(new_embeddings.astype(np.float32, copy=False))
    cents = l2_normalize(existing_centroids.astype(np.float32, copy=False))

    sims = embs @ cents.T  # (M, K)
    best = sims.argmax(axis=1)
    best_sim = sims[np.arange(sims.shape[0]), best]

    labels = np.full(embs.shape[0], -1, dtype=np.int32)
    probs = np.zeros(embs.shape[0], dtype=np.float32)
    matched = best_sim >= loose_match
    labels[matched] = np.asarray(existing_labels)[best[matched]].astype(np.int32)
    matched_probs = best_sim[matched].astype(np.float32, copy=False)
    probs[matched] = matched_probs
    # Strong matches saturate to 1.0; loose matches stay where they are.
    strong = matched_probs >= strong_match
    probs[matched] = np.where(strong, 1.0, matched_probs)
    return labels, probs
