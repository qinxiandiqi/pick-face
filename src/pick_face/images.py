"""Image decode + EXIF rotate + downsample to 1600-px long edge.

Reference: docs/09 §2.1 + §2.2–2.4.

Format routing (see docs/09):
- JPG/PNG/WebP/BMP/GIF/TIFF → Pillow directly
- HEIC/HEIF → pillow-heif opener (optional extra; raises ImportError cleanly)
- RAW (CR2/NEF/ARW/DNG/RAF/ORF/RW2) → Pillow EXIF-thumbnail first, fallback
  to rawpy if available (optional extra; raises ImportError cleanly)

The output is one tuple of (BGR ndarray for detector, RGB PIL for thumbnail).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pick_face.errors import ImageDecodeError

# Long-edge cap (docs/09 §2.3 — 1600 px empirical knee)
MAX_LONG_EDGE = 1600


@dataclass(frozen=True)
class DecodedImage:
    """One decoded source image, post EXIF-rotation, post downsample."""

    path: Path
    bgr: np.ndarray  # (H, W, 3) uint8 contiguous — detector input
    pil_rgb_size: tuple[int, int]  # (W, H) — for thumb width=160
    original_size: tuple[int, int]  # (W, H) before downsample


def decode(path: Path) -> DecodedImage:
    """Decode *path* and return a (BGR, PIL-thumb-size) pair.

    Raises:
        ImageDecodeError: file missing, unsupported format, or corrupt.
    """
    try:
        pil = _open_with_pillow(path)
    except FileNotFoundError as e:
        raise ImageDecodeError(f"file not found: {path}") from e
    except PermissionError as e:
        raise ImageDecodeError(f"permission denied: {path}") from e
    except Exception as e:
        raise ImageDecodeError(f"pillow failed to open {path}: {e}") from e

    if pil is None:
        # HEIC / RAW fallback path. Raise a clear, actionable error.
        raise ImageDecodeError(
            f"unsupported or missing-codec format: {path.name}. "
            f"Install pick-face[heic] for HEIC, pick-face[raw] for camera RAW."
        )

    pil = _exif_transpose(pil)
    original_size = pil.size  # (W, H)
    pil = _downsample(pil)

    rgb_array = np.asarray(pil.convert("RGB"))
    bgr = np.ascontiguousarray(rgb_array[..., ::-1])  # RGB → BGR
    return DecodedImage(
        path=path,
        bgr=bgr,
        pil_rgb_size=pil.size,
        original_size=original_size,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _open_with_pillow(path: Path):
    """Open *path* with Pillow, trying HEIF then RAW extras in turn.

    Returns None if the format is recognised as HEIC/RAW but the matching
    extra is not installed. Raises whatever Pillow raises for corrupt JPG/PNG.
    """
    from PIL import Image

    suffix = path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError:
            return None
        return Image.open(path)  # noqa: F821 — pillow-heif registered

    if suffix in {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}:
        # Fast path: try the embedded EXIF thumbnail first (Pillow native).
        try:
            img = Image.open(path)
            img.load()  # force parse; raises if file corrupt
            return img
        except Exception:
            # Slow path: rawpy full decode if installed.
            try:
                import rawpy
            except ImportError:
                return None
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True, no_auto_bright=True, output_color=rawpy.ColorSpace.sRGB
                )
            return Image.fromarray(rgb)

    return Image.open(path)


def _exif_transpose(pil):
    """Apply EXIF orientation (the 90% of phone-photo pitfalls)."""
    from PIL import ImageOps

    return ImageOps.exif_transpose(pil)


def _downsample(pil):
    """Cap the long edge at MAX_LONG_EDGE with bilinear resampling."""
    from PIL import Image

    w, h = pil.size
    long_edge = max(w, h)
    if long_edge <= MAX_LONG_EDGE:
        return pil
    scale = MAX_LONG_EDGE / long_edge
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return pil.resize((new_w, new_h), Image.Resampling.BILINEAR)
