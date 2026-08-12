// FaceOverlay — SVG overlay that draws face bboxes on top of the photo.
// M7 ships this as a no-op (empty rects) — M7.5 will feed bboxes from
// `/api/photos/{id}/metadata` once that endpoint is extended.
//
// Math: viewBox = "0 0 naturalW naturalH"; each rect's coordinates are
// in image-natural pixels (browser handles CSS scaling via the parent
// transform). When face data arrives the parent simply passes a non-empty
// `boxes` array.

import * as React from "react";

export interface Bbox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface FaceOverlayProps {
  naturalW: number;
  naturalH: number;
  boxes: Bbox[];
}

export function FaceOverlay({ naturalW, naturalH, boxes }: FaceOverlayProps): React.JSX.Element | null {
  if (naturalW <= 0 || naturalH <= 0) return null;
  if (boxes.length === 0) return null;
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox={`0 0 ${naturalW} ${naturalH}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
    >
      {boxes.map((b, i) => (
        <rect
          key={i}
          x={b.x}
          y={b.y}
          width={b.w}
          height={b.h}
          fill="none"
          stroke="hsl(var(--primary))"
          strokeWidth={Math.max(2, Math.min(naturalW, naturalH) / 200)}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}