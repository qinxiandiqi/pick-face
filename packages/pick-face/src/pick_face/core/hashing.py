"""xxh3_64 content hashing for source image idempotency.

Reference: docs/10 §3.3 + docs/03 §5 (幂等键).
Hash covers the first 64KB of the file (fast fingerprint, not full SHA).
64-bit collision space is sufficient for 50M files at 1e-9 false-positive rate.
"""

from __future__ import annotations

from pathlib import Path

import xxhash

HASH_ALGO = "xxh3_64"
HASH_PREFIX_BYTES = 64 * 1024  # 64 KB
HASH_HEX_LEN = 16  # xxh3_64 -> 64 bits = 16 hex chars


def content_hash(path: Path) -> str:
    """Compute xxh3_64 over the first 64KB of *path*; return 16-char hex.

    We deliberately do NOT hash the whole file: a 50MB RAW takes 50ms to read,
    a 64KB fingerprint takes <1ms. The trade-off: a malicious user could craft
    two files with identical first-64KB but different rest. For our use case
    (idempotent re-runs) this is acceptable; full SHA-256 is a v0.2 option.
    """
    h = xxhash.xxh3_64()
    with open(path, "rb") as f:
        h.update(f.read(HASH_PREFIX_BYTES))
    return h.hexdigest()


def content_hash_bytes(data: bytes) -> str:
    """Same algo for in-memory blobs (e.g. test fixtures)."""
    return xxhash.xxh3_64(data[:HASH_PREFIX_BYTES]).hexdigest()


def file_id(path: Path, size: int, mtime: float, hash_: str | None = None) -> str:
    """Composite file identity for incremental diff.

    Format: {abs_path}|{size}|{mtime:.3f}|{hash}
    Used as the idempotency key in source/face/link tables.
    """
    h = hash_ if hash_ is not None else content_hash(path)
    return f"{path.resolve()}|{size}|{mtime:.3f}|{h}"
