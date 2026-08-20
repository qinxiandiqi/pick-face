// ViewerToolbar — small toolbar at the bottom of the FaceViewer.
// Shown only when fullscreen is not active. Provides Reset, Prev/Next,
// and Close buttons.

import * as React from "react";
import { ChevronLeft, ChevronRight, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useViewerStore } from "@/lib/viewerStore";

export function ViewerToolbar(): React.JSX.Element | null {
  const open = useViewerStore((s) => s.open);
  const index = useViewerStore((s) => s.index);
  const total = useViewerStore((s) => s.photos.length);
  const prev = useViewerStore((s) => s.prev);
  const next = useViewerStore((s) => s.next);
  const resetView = useViewerStore((s) => s.resetView);
  const closeViewer = useViewerStore((s) => s.closeViewer);

  if (!open) return null;

  return (
    <div
      className="pointer-events-auto absolute inset-x-0 bottom-0 flex items-center justify-center gap-2 bg-gradient-to-t from-black/70 to-transparent p-4 text-white"
      data-testid="viewer-toolbar"
    >
      <Button
        variant="ghost"
        size="icon"
        aria-label="Previous photo"
        onClick={prev}
        disabled={index <= 0}
        className="text-white hover:bg-white/20"
      >
        <ChevronLeft className="h-5 w-5" />
      </Button>
      <span className="px-2 text-sm tabular-nums">
        {total > 0 ? `${index + 1} / ${total}` : "—"}
      </span>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Next photo"
        onClick={next}
        disabled={index >= total - 1}
        className="text-white hover:bg-white/20"
      >
        <ChevronRight className="h-5 w-5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Reset view"
        onClick={resetView}
        className="ml-4 text-white hover:bg-white/20"
      >
        <RotateCcw className="h-5 w-5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Close viewer"
        onClick={closeViewer}
        className="ml-2 text-white hover:bg-white/20"
      >
        <X className="h-5 w-5" />
      </Button>
    </div>
  );
}