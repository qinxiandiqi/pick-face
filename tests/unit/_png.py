"""Build tiny valid PNG bytes for tests that just need *something readable*.

Why hand-rolled (vs Pillow): zero extra deps; Pillow may not be installed in
the bare-bones py312 venv that runs unit tests. The 2x2 PNG is ~60 bytes.
"""

from __future__ import annotations

import zlib


def make_minimal_png(width: int = 2, height: int = 2) -> bytes:
    """Build a valid 2x2 RGB PNG bytes (no external deps)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + tag
            + data
            + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(
        b"IHDR",
        width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00",
    )
    # 2x2 red+green pixels, each row prefixed with filter byte 0
    raw = b"\x00" + b"\xff\x00\x00\xff" * width
    raw += b"\x00" + b"\x00\xff\x00\xff" * width
    idat = chunk(b"IDAT", zlib.compress(raw, 9))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend
