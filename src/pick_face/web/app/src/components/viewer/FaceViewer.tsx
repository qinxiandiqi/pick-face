// FaceViewer — modal photo viewer (M7-T-1..T-5).
//
// Responsibilities:
//   - Render current photo (with CSS transform from store: scale + pan).
//   - Render <FaceOverlay> (no-op for M7; M7.5 fills in bboxes).
//   - Wire gesture/keyboard/wheel via useViewerControls.
//   - Toggle fullscreen on the viewer container.
//   - Pre-load next + prev images so ← / → feel instant.

import * as React from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { FaceOverlay } from "@/components/viewer/FaceOverlay";
import { ViewerToolbar } from "@/components/viewer/ViewerToolbar";
import { useViewerControls } from "@/components/viewer/useViewerControls";
import { useViewerStore, type ViewerPhoto } from "@/lib/viewerStore";
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

  // Track natural image size.
  useEffect(() => {
    if (!current) return;
    const img = new Image();
    img.onload = () => setNatural({ w: img.naturalWidth, h: img.naturalHeight });
    img.src = current.url;
  }, [current?.url]);

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
          <FaceOverlay naturalW={natural.w} naturalH={natural.h} boxes={[]} />
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