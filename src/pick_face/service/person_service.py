"""Person-album read API — `docs/03 §2.3` + `docs/01 §1.3`.

Maps v2.x's ``cluster`` table (groups of faces) onto the v3
"virtual album" concept. For M6 the cover image is derived by
selecting the face with the highest ``quality`` + ``det_score`` in
the cluster and emitting its bounding-box crop from the original
photo (we don't have face chip files yet — those land in M7 via
``worker/cluster_worker``).

The service is read-only in M6: ``list_persons()``, ``get_person()``,
``get_person_photos()``, ``get_person_cover()``. Mutations (rename,
merge, delete) are documented as the ``api/review.py`` surface but
the implementation lands in M9.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pick_face.store.index import open_db

from .paths import AppLayout, get_layout


@dataclass
class PersonSummary:
    """One row of ``/api/persons`` list."""

    id: int
    label: str
    face_count: int
    photo_count: int


@dataclass
class PersonDetail(PersonSummary):
    """Detail row for ``/api/persons/{id}``."""

    sources: list[str]  # distinct scan roots contributing faces


class PersonService:
    """Read API over the v2.x ``cluster`` table."""

    def __init__(self, layout: AppLayout | None = None) -> None:
        self._layout = layout or get_layout()

    def list_persons(self, limit: int = 50, offset: int = 0) -> list[PersonSummary]:
        """List non-merged clusters, sorted by face count desc.

        The v2.x ``cluster.merged_into IS NULL`` predicate maps to
        ``persons.merged_into IS NULL`` in the v3 schema (see docs/05 §2).

        M8-T-6: faces whose underlying photo is soft-deleted
        (``source.status='removed'``) or vanished from disk
        (``source.status='missing'``) are excluded from the face
        count so the SPA waterfall doesn't surface "ghost" photos.
        The counts are computed via correlated subqueries so empty
        clusters (just-created, no faces assigned yet) still surface
        with ``face_count=0``.
        """
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT c.id, c.label,
                       (
                           SELECT COUNT(DISTINCT f.id)
                           FROM face f
                           JOIN source s ON s.id = f.source_id
                           WHERE f.cluster_id = c.id AND s.status = 'active'
                       ) AS face_count,
                       (
                           SELECT COUNT(DISTINCT f.source_id)
                           FROM face f
                           JOIN source s ON s.id = f.source_id
                           WHERE f.cluster_id = c.id AND s.status = 'active'
                       ) AS photo_count
                FROM cluster c
                WHERE c.merged_into IS NULL
                ORDER BY face_count DESC, c.id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            return [
                PersonSummary(
                    id=int(row[0]),
                    label=str(row[1]),
                    face_count=int(row[2] or 0),
                    photo_count=int(row[3] or 0),
                )
                for row in cur.fetchall()
            ]
        finally:
            conn.close()

    def count_persons(self) -> int:
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM cluster WHERE merged_into IS NULL"
            )
            return int(cur.fetchone()[0])
        finally:
            conn.close()

    def get_person(self, person_id: int) -> PersonDetail | None:
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT c.id, c.label,
                       (
                           SELECT COUNT(DISTINCT f.id)
                           FROM face f
                           JOIN source s ON s.id = f.source_id
                           WHERE f.cluster_id = c.id AND s.status = 'active'
                       ),
                       (
                           SELECT COUNT(DISTINCT f.source_id)
                           FROM face f
                           JOIN source s ON s.id = f.source_id
                           WHERE f.cluster_id = c.id AND s.status = 'active'
                       )
                FROM cluster c
                WHERE c.id = ? AND c.merged_into IS NULL
                """,
                (person_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            sources_cur = conn.execute(
                """
                SELECT DISTINCT s.path
                FROM face f
                JOIN source s ON s.id = f.source_id
                WHERE f.cluster_id = ? AND s.status = 'active'
                """,
                (person_id,),
            )
            sources = [str(r[0]) for r in sources_cur.fetchall()]
            return PersonDetail(
                id=int(row[0]),
                label=str(row[1]),
                face_count=int(row[2] or 0),
                photo_count=int(row[3] or 0),
                sources=sources,
            )
        finally:
            conn.close()

    def get_person_photos(
        self,
        person_id: int,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """Distinct photos containing a face in this cluster.

        Returns ``{photo_id, path, width, height}``-shaped dicts.
        We don't have width/height in v2.x ``source`` table (those
        live in EXIF), so we emit ``None`` for now and let the SPA
        load the photo via ``/api/photos/{id}`` to learn dimensions.
        """
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT DISTINCT s.id, s.path
                FROM face f
                JOIN source s ON s.id = f.source_id
                WHERE f.cluster_id = ? AND s.status = 'active'
                ORDER BY s.mtime DESC, s.id ASC
                LIMIT ? OFFSET ?
                """,
                (person_id, limit, offset),
            )
            return [{"photo_id": int(r[0]), "path": str(r[1])} for r in cur.fetchall()]
        finally:
            conn.close()

    def get_person_cover(self, person_id: int) -> tuple[Path, int] | None:
        """Return the cover photo path + face bbox for this cluster.

        Selection strategy (per ``docs/01 §1.3 AC-5`` + docs/03 §2.3):

        1. Highest ``quality`` (sharpest chip)
        2. Highest ``det_score`` (most confident detector output)
        3. Largest bbox area (most pixels = clearest face)

        Returns ``(photo_path, face_id)`` or ``None`` if the cluster
        has no faces / doesn't exist.
        """
        conn = open_db(self._layout.db_path)
        try:
            cur = conn.execute(
                """
                SELECT f.id, s.path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2
                FROM face f
                JOIN source s ON s.id = f.source_id
                WHERE f.cluster_id = ? AND s.status = 'active'
                ORDER BY
                    COALESCE(f.quality, 0) DESC,
                    COALESCE(f.det_score, 0) DESC,
                    ((COALESCE(f.bbox_x2,0)-COALESCE(f.bbox_x1,0))
                     *(COALESCE(f.bbox_y2,0)-COALESCE(f.bbox_y1,0))) DESC,
                    f.id ASC
                LIMIT 1
                """,
                (person_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return Path(str(row[1])), int(row[0])
        finally:
            conn.close()


__all__ = [
    "AppLayout",
    "PersonDetail",
    "PersonService",
    "PersonSummary",
    "get_layout",
]
