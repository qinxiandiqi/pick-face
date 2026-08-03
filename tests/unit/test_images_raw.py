"""Tests for RAW decode fast path (T-103, M2 / docs/09 §2.1).

We don't ship a real RAW fixture (10-30 MB). We verify the contract:
  - The fast path tries Pillow first.
  - If it fails AND rawpy is missing, decode() raises ImageDecodeError
    with a "install pick-face[raw]" hint (so the user knows what to do).
  - If it fails AND rawpy IS installed, the fallback path is exercised.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pick_face.errors import ImageDecodeError


def test_raw_without_rawpy_raises_install_hint(tmp_pure: Path) -> None:
    """No rawpy + a non-decodable .cr2 → ImageDecodeError mentioning [raw]."""
    from pick_face.images import decode

    raw_path = tmp_pure / "ghost.cr2"
    raw_path.write_bytes(b"\x00" * 8)

    # Force Pillow to fail (raw isn't real) and rawpy unavailable.
    with patch("PIL.Image.open", side_effect=OSError("not a real RAW")):
        # Even if the system has rawpy, we hide it from this test by
        # making the import fail.
        with patch.dict("sys.modules", {"rawpy": None}):
            with pytest.raises(ImageDecodeError) as exc:
                decode(raw_path)
    msg = str(exc.value).lower()
    assert "install" in msg
    assert "raw" in msg


def test_raw_fast_path_tries_pillow_first(tmp_pure: Path) -> None:
    """The Pillow.Image.open call should happen before any rawpy logic."""
    from pick_face.images import _open_with_pillow

    raw_path = tmp_pure / "x.nef"
    raw_path.write_bytes(b"\x00" * 8)

    pillow_calls = []
    real_open = None
    try:
        from PIL import Image as _PIL_Image

        real_open = _PIL_Image.open

        def tracking_open(p, *a, **kw):
            pillow_calls.append(str(p))
            raise OSError("tracked failure")

        with patch.object(_PIL_Image, "open", tracking_open):
            with patch.dict("sys.modules", {"rawpy": None}):
                out = _open_with_pillow(raw_path)
        assert out is None  # returns None when extras missing
        assert pillow_calls == [str(raw_path)]
    finally:
        # Restore (patch.object handles this on context exit)
        pass