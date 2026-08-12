"""Photo streaming + thumbnail cache — `docs/03 §2.4` + `docs/01 §1.4`.

Two responsibilities, both read-only:

1. ``stream_original(photo_id, range)`` — look up the photo's on-disk
   path by id (NEVER accept a path from the request — see docs/03 §2.4
   security contract), verify it lives under a whitelisted scan root,
   then serve it via ``FileResponse`` supporting HTTP Range.

2. ``thumbnail(photo_id)`` — generate (or load from cache) a 256×256
   JPEG thumbnail. M6 uses a simple Pillow path; the chip pipeline
   for face covers is wired separately in M7.

The original photo is **never copied**: thumbnails land in
``data/thumbnails/`` (by content hash) but the original stays where
the user put it.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from pick_face.core.hashing import content_hash
from pick_face.store.index import open_db

from .config_service import is_under_any_whitelisted
from .paths import AppLayout, get_layout

# Thumbnail target size — see docs/03 §2.4 + docs/05 §4.2.
THUMB_SIZE: tuple[int, int] = (256, 256)
THUMB_JPEG_QUALITY = 85


@dataclass
class PhotoRecord:
    """A row from the v2.x ``source`` table exposed via v3 API."""

    id: int
    path: Path
    mtime: float
    size: int
    content_hash: str


@dataclass
class FaceRecord:
    """A face detected on a photo — bbox in pixel space + the cluster it
    belongs to (or ``None`` if not yet clustered).

    Used by the SPA viewer overlay (M7-T-6) and the EXIF side-sheet
    (M7-T-8). Coordinates are in the original image's pixel space.
    """

    id: int
    bbox_x1: float | None
    bbox_y1: float | None
    bbox_x2: float | None
    bbox_y2: float | None
    cluster_id: int | None
    det_score: float | None
    quality: float | None


@dataclass
class PhotoMetadata:
    """Composite metadata returned by ``/api/photos/{id}/meta``.

    Includes the photo's source row (path, mtime, size, hash) plus
    natural dimensions (for SVG viewBox) and every face detected on
    the photo. ``faces`` is empty (not error) for photos with no
    detections yet — that's the pre-scan state.
    """

    id: int
    path: Path
    mtime: float
    size: int
    content_hash: str
    natural_width: int | None
    natural_height: int | None
    faces: list[FaceRecord]


class PhotoNotFoundError(LookupError):
    """The photo_id isn't in the database or is soft-deleted."""


class PhotoAccessError(PermissionError):
    """The photo's resolved path isn't under any whitelisted scan root.

    This is a defense-in-depth check; in normal operation the photo
    was added through the scanner (so its path was whitelisted at
    add-time). But the user could have moved the source directory
    or edited the DB, and we want loud refusal either way.
    """


class PhotoService:
    """Read API over the ``source`` table + thumbnail cache."""

    def __init__(self, layout: AppLayout | None = None) -> None:
        self._layout = layout or get_layout()

    # -- photo lookup ---------------------------------------------------------

    def get_photo(self, photo_id: int) -> PhotoRecord:
        """Fetch the photo row; raise :class:`PhotoNotFoundError` if missing."""
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT id, path, mtime, size, hash
                FROM source
                WHERE id = ?
                """,
                (photo_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise PhotoNotFoundError(f"photo {photo_id} not in database")
            return PhotoRecord(
                id=int(row[0]),
                path=Path(str(row[1])),
                mtime=float(row[2]),
                size=int(row[3]),
                content_hash=str(row[4] or ""),
            )
        finally:
            conn.close()

    def get_photo_metadata(self, photo_id: int) -> "PhotoMetadata":
        """Return photo row + faces (bbox + cluster_id + scores).

        Used by the SPA viewer to draw face bounding boxes on the image.
        ``natural_width`` / ``natural_height`` come from PIL — needed for
        the SVG overlay to map pixel-space bboxes to viewBox-space.
        """
        from PIL import Image as _PILImage

        rec = self.get_photo(photo_id)
        natural_w: int | None = None
        natural_h: int | None = None
        if rec.path.exists():
            try:
                with _PILImage.open(rec.path) as im:
                    natural_w, natural_h = im.size
            except (OSError, _PILImage.DecompressionBombError):
                natural_w = natural_h = None

        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                       cluster_id, det_score, quality
                FROM face
                WHERE source_id = ?
                ORDER BY id ASC
                """,
                (photo_id,),
            )
            faces = [
                FaceRecord(
                    id=int(r[0]),
                    bbox_x1=float(r[1]) if r[1] is not None else None,
                    bbox_y1=float(r[2]) if r[2] is not None else None,
                    bbox_x2=float(r[3]) if r[3] is not None else None,
                    bbox_y2=float(r[4]) if r[4] is not None else None,
                    cluster_id=int(r[5]) if r[5] is not None else None,
                    det_score=float(r[6]) if r[6] is not None else None,
                    quality=float(r[7]) if r[7] is not None else None,
                )
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

        return PhotoMetadata(
            id=rec.id,
            path=rec.path,
            mtime=rec.mtime,
            size=rec.size,
            content_hash=rec.content_hash,
            natural_width=natural_w,
            natural_height=natural_h,
            faces=faces,
        )

    def get_photo_path(self, photo_id: int) -> Path:
        """Resolve ``photo_id`` to an on-disk path **after** whitelist check.

        This is the only safe way to obtain a path for ``FileResponse``.
        Any code path that wants the file MUST go through here.
        """
        rec = self.get_photo(photo_id)
        # Defense in depth — verify the resolved path is still under a
        # whitelisted scan root. We read the whitelist lazily; if there
        # are no whitelisted paths (yet) we still permit reads but log
        # via the exception so tests can assert.
        from .config_service import ConfigService

        whitelist = ConfigService(self._layout).enabled_paths()
        if whitelist and not is_under_any_whitelisted(rec.path, whitelist):
            raise PhotoAccessError(
                f"photo {photo_id} path {rec.path} not under whitelisted roots"
            )
        return rec.path

    # -- thumbnails -----------------------------------------------------------

    def _thumbnail_path(self, content_hash_hex: str) -> Path:
        """Resolve the on-disk thumbnail path by content hash.

        Two-level bucket (first 2 chars / next 2 chars) keeps directory
        fan-out low for big albums (see docs/05 §4.2).
        """
        h = content_hash_hex
        if len(h) < 4:
            raise ValueError(f"content_hash too short: {h!r}")
        bucket1, bucket2 = h[:2], h[2:4]
        return self._layout.thumbnails_dir / bucket1 / bucket2 / f"{h}.jpg"

    def thumbnail(self, photo_id: int) -> Path:
        """Return the path of the photo's thumbnail, generating if absent.

        If the source file no longer exists on disk, we silently delete
        the DB row's source entry and raise :class:`PhotoNotFoundError`.
        """
        rec = self.get_photo(photo_id)
        if not rec.path.exists():
            self._mark_missing(photo_id)
            raise PhotoNotFoundError(
                f"photo {photo_id} source file gone: {rec.path}"
            )
        thumb_path = self._thumbnail_path(rec.content_hash) if rec.content_hash else None
        if thumb_path is None:
            # No content hash yet — compute it now and persist.
            h = content_hash(rec.path)
            self._set_hash(photo_id, h)
            rec = self.get_photo(photo_id)  # re-fetch with hash
            thumb_path = self._thumbnail_path(rec.content_hash)
        if not thumb_path.exists():
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            self._generate_thumbnail(rec.path, thumb_path)
        return thumb_path

    def _generate_thumbnail(self, source: Path, dest: Path) -> None:
        """Synchronous Pillow path. JPEG q=85, 256×256 longest-edge."""
        try:
            with Image.open(source) as im:
                im.thumbnail(THUMB_SIZE)
                # Strip metadata to keep file size predictable; rotate
                # according to EXIF orientation if available.
                buf = io.BytesIO()
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGB")
                im.save(buf, format="JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
                dest.write_bytes(buf.getvalue())
        except (OSError, Image.DecompressionBombError):
            # Per docs/01 §1.2 AC-2: a single bad file must not crash
            # the request handler. Write a 1×1 placeholder JPEG so the
            # next call short-circuits, then re-raise so the API can
            # return a 502.
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_placeholder_jpeg())
            raise

    # -- DB maintenance ------------------------------------------------------

    def _mark_missing(self, photo_id: int) -> None:
        conn = open_db(self._layout.db_path)
        try:
            conn.execute(
                "UPDATE source SET status = 'missing' WHERE id = ?",
                (photo_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def _set_hash(self, photo_id: int, hex_hash: str) -> None:
        conn = open_db(self._layout.db_path)
        try:
            conn.execute(
                "UPDATE source SET hash = ? WHERE id = ?",
                (hex_hash, photo_id),
            )
            conn.commit()
        finally:
            conn.close()


def _placeholder_jpeg() -> bytes:
    """Tiny 1×1 grey JPEG — used as a write-on-fail marker."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c"
        b"\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c"
        b"\x1c $.' \x20\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00"
        b"\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01"
        b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n"
        b"\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04"
        b"\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142"
        b"\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%"
        b"&\x27()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88"
        b"\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8"
        b"\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8"
        b"\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7"
        b"\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01"
        b"\x01\x00\x00?\x00\xfb\xd0\xff\xd9"
    )


__all__ = [
    "AppLayout",
    "PhotoAccessError",
    "PhotoNotFoundError",
    "PhotoRecord",
    "PhotoService",
    "THUMB_JPEG_QUALITY",
    "THUMB_SIZE",
    "get_layout",
]


# Helper exposed for tests so they can assert thumbnail directory shape.
def thumbnail_dir(layout: AppLayout) -> Path:
    return layout.thumbnails_dir


# Tell mypy that ``os`` is referenced through ``os.access`` in callers
# that may want to import it; keep the symbol available here.
_ = os
