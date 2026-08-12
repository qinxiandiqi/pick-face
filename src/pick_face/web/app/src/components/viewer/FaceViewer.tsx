// FaceViewer — modal photo viewer (M7-T-1..T-5).
//
// Responsibilities:
//   - Render current photo (with CSS transform from store: scale + pan).
//   - Render <FaceOverlay> with face bboxes from /api/photos/{id}/meta
//     (M7.5 — M7-T-6).
//   - Wire gesture/keyboard/wheel via useViewerControls.
//   - Toggle fullscreen on the viewer container.
//   - Pre-load next + prev images so ← / → feel instant.

import * as React from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { FaceOverlay, type Bbox } from "@/components/viewer/FaceOverlay";
import { ViewerToolbar } from "@/components/viewer/ViewerToolbar";
import { useViewerControls } from "@/components/viewer/useViewerControls";
import { useViewerStore, type ViewerPhoto } from "@/lib/viewerStore";
import { usePhotoMetadataQuery } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";

export interface FaceViewerProps {
  personId: number;
  photos: ViewerPhoto[];
  initialIndex: number;
  onClose?: () => void;
}

export function FaceViewer({
  personId,
  photos,
  initialIndex,
  onClose,
}: FaceViewerProps): React.JSX.Element {
  const open = useViewerStore((s) => s.open);
  const openViewer = useViewerStore((s) => s.openViewer);
  const closeViewer = useViewerStore((s) => s.closeViewer);
  const index = useViewerStore((s) => s.index);
  const scale = useViewerStore((s) => s.scale);
  const pan = useViewerStore((s) => s.pan);
  const fullscreen = useViewerStore((s) => s.fullscreen);
  const storePhotos = useViewerStore((s) => s.photos);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [viewport, setViewport] = useState({ w: 0, h: 0 });
  const [natural, setNatural] = useState({ w: 0, h: 0 });

  // Sync external `photos` + `initialIndex` into the store.
  // (PersonDetailPage already drove the URL ?photo=...; we just open.)
  useEffect(() => {
    if (photos.length === 0) return;
    if (!open) openViewer(personId, photos, initialIndex);
  }, [open, openViewer, photos, personId, initialIndex]);

  const current = storePhotos[index];

  // M7.5 — fetch extended metadata (bbox + cluster_id) for the current photo.
  // The endpoint returns natural dimensions; we MUST favour the server's
  // values when available (the on-load handler that uses <img>.naturalWidth
  // is a fallback for cases where the dims are missing — e.g. corrupt JPEG).
  const { data: photoMeta } = usePhotoMetadataQuery(open ? current?.id ?? null : null);

  // Track natural image size — prefer the server-reported dimensions
  // (PIL opened the file reliably), fall back to <img>.naturalWidth.
  useEffect(() => {
    if (!current) return;
    if (photoMeta?.natural_width && photoMeta?.natural_height) {
      setNatural({ w: photoMeta.natural_width, h: photoMeta.natural_height });
      return;
    }
    const img = new Image();
    img.onload = () => setNatural({ w: img.naturalWidth, h: img.naturalHeight });
    img.src = current.url;
  }, [current?.url, current?.id, photoMeta?.natural_width, photoMeta?.natural_height]);

  // Build bbox list for the overlay. Server returns [x1, y1, x2, y2];
  // overlay wants {x, y, w, h} plus clusterId for the highlight filter.
  const boxes: Bbox[] = React.useMemo(
    () =>
      (photoMeta?.faces ?? [])
        .filter((f) => f.bbox !== null)
        .map((f) => {
          const [x1, y1, x2, y2] = f.bbox as [number, number, number, number];
          return { x: x1, y: y1, w: x2 - x1, h: y2 - y1, clusterId: f.cluster_id };
        }),
    [photoMeta],
  );

  // Track container size (resized on fullscreen toggle).
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setViewport({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setViewport({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [open]);

  // Hook gestures + keyboard + wheel.
  const { onWheel: handleWheel } = useViewerControls({
    naturalW: natural.w,
    naturalH: natural.h,
    viewportW: viewport.w,
    viewportH: viewport.h,
    enabled: open,
  });

  // Wire fullscreen API to the store.
  useEffect(() => {
    if (!open) return;
    const el = containerRef.current;
    if (!el) return;
    if (fullscreen && !document.fullscreenElement) {
      el.requestFullscreen?.().catch(() => {
        // ignore — user may have denied
      });
    } else if (!fullscreen && document.fullscreenElement === el) {
      void document.exitFullscreen?.();
    }
  }, [open, fullscreen]);

  useEffect(() => {
    const onChange = () => {
      const isFs = !!document.fullscreenElement;
      if (!isFs && useViewerStore.getState().fullscreen) {
        useViewerStore.setState({ fullscreen: false });
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      closeViewer();
      onClose?.();
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className={cn(
          "max-w-none w-screen h-screen p-0 bg-black border-0",
          "data-[state=open]:animate-none data-[state=open]:fade-in-0",
        )}
        aria-describedby={undefined}
        data-testid="face-viewer"
      >
        <div
          ref={containerRef}
          className="relative h-full w-full overflow-hidden"
          onWheel={handleWheel}
        >
          {current && (
            <img
              ref={imgRef}
              key={current.id}
              src={current.url}
              alt=""
              draggable={false}
              className="absolute left-0 top-0 select-none"
              style={{
                transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
                transformOrigin: "top left",
                touchAction: "none",
              }}
            />
          )}
          {current && (
            <FaceOverlay
              naturalW={natural.w}
              naturalH={natural.h}
              boxes={boxes}
              highlightClusterId={personId}
            />
          )}
          <ViewerToolbar />

          {/* Preload neighbors */}
          {storePhotos[index + 1] && (
            <link rel="preload" as="image" href={storePhotos[index + 1].url} />
          )}
          {storePhotos[index - 1] && (
            <link rel="preload" as="image" href={storePhotos[index - 1].url} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}