// PersonDetailPage — single-cluster waterfall + FaceViewer overlay.
//
// The waterfall uses `react-photo-album` Rows layout (M6-T-14).
// Clicking a photo opens the FaceViewer (lazy-loaded). The viewer's
// `open` state is driven by URL `?photo=<id>` so the back button closes
// it without losing scroll position.

import * as React from "react";
import { Suspense, lazy, useState } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import PhotoAlbum from "react-photo-album";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePersonQuery, usePersonPhotosQuery } from "@/lib/api/hooks";

const FaceViewer = lazy(() =>
  import("@/components/viewer/FaceViewer").then((m) => ({ default: m.FaceViewer })),
);

export function PersonDetailPage(): React.JSX.Element {
  const { id } = useParams<{ id: string }>();
  const personId = id ? Number(id) : null;
  const [search, setSearch] = useSearchParams();

  const { data: person, isLoading: personLoading } = usePersonQuery(personId);
  const { data: photosData, isLoading: photosLoading } = usePersonPhotosQuery(personId, 500);

  // Local roster for the viewer (Photo[] shape expected by FaceViewer).
  const roster = React.useMemo(
    () =>
      (photosData?.photos ?? []).map((p) => ({
        id: p.photo_id,
        url: p.url,
        thumbUrl: p.thumb_url,
        width: p.width ?? 0,
        height: p.height ?? 0,
      })),
    [photosData],
  );

  const photoParam = search.get("photo");
  const photoId = photoParam ? Number(photoParam) : null;
  const initialIndex = photoId
    ? roster.findIndex((p) => p.id === photoId)
    : -1;

  const [viewerOpen, setViewerOpen] = useState(initialIndex >= 0);

  const closeViewer = React.useCallback(() => {
    setViewerOpen(false);
    const next = new URLSearchParams(search);
    next.delete("photo");
    setSearch(next, { replace: true });
  }, [search, setSearch]);

  const onPhotoClick = React.useCallback(
    (index: number) => {
      const next = new URLSearchParams(search);
      next.set("photo", String(roster[index]?.id ?? ""));
      setSearch(next, { replace: false });
      setViewerOpen(true);
    },
    [search, setSearch, roster],
  );

  if (!personId || Number.isNaN(personId)) {
    return (
      <div className="container mx-auto p-6 text-sm text-muted-foreground">
        Invalid person id.
      </div>
    );
  }

  const albumPhotos = roster.map((p) => ({
    src: p.thumbUrl,
    width: p.width || 400,
    height: p.height || 300,
    alt: `photo ${p.id}`,
  }));

  return (
    <div className="container mx-auto p-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
            <Link to="/persons">
              <ArrowLeft className="mr-1 h-4 w-4" />
              All persons
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold tracking-tight">
            {personLoading ? <Skeleton className="h-7 w-48" /> : (person?.name ?? `Person ${personId}`)}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {person?.photo_count ?? 0} photos
          </p>
        </div>
      </header>

      {photosLoading && (
        <div
          className="grid gap-2"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))" }}
        >
          {Array.from({ length: 12 }).map((_, i) => (
            <Skeleton key={i} className="aspect-square w-full" />
          ))}
        </div>
      )}

      {!photosLoading && roster.length === 0 && (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            No photos for this person yet. Run a scan to populate.
          </CardContent>
        </Card>
      )}

      {!photosLoading && roster.length > 0 && (
        <div data-testid="person-photos">
          <PhotoAlbum
            layout="rows"
            photos={albumPhotos}
            targetRowHeight={180}
            onClick={({ index }) => onPhotoClick(index)}
          />
        </div>
      )}

      {viewerOpen && roster.length > 0 && initialIndex >= 0 && (
        <Suspense fallback={null}>
          <FaceViewer
            personId={personId}
            photos={roster}
            initialIndex={initialIndex}
            onClose={closeViewer}
          />
        </Suspense>
      )}
    </div>
  );
}