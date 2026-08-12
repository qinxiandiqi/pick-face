// FaceOverlay — SVG overlay that draws face bboxes on top of the photo.
//
// M7.5: fed from `/api/photos/{id}/meta` (M7-T-6). Coordinates are in
// image-natural pixels; the browser handles CSS scaling via the parent
// transform. When `boxes` is empty we render nothing — a photo with no
// detections shouldn't get a clutter of invisible rects.
//
// `highlightClusterId` lets the parent (the /persons/:id route) emphasise
// the faces that belong to the person being viewed, while dimming the
// others.

import * as React from "react";

export interface Bbox {
  x: number;
  y: number;
  w: number;
  h: number;
  clusterId: number | null;
}

export interface FaceOverlayProps {
  naturalW: number;
  naturalH: number;
  boxes: Bbox[];
  /** Optional: cluster id of the current person — those faces get the
   *  primary stroke, others get a muted one. Pass null to render all
   *  faces uniformly. */
  highlightClusterId?: number | null;
}

export function FaceOverlay({
  naturalW,
  naturalH,
  boxes,
  highlightClusterId = null,
}: FaceOverlayProps): React.JSX.Element | null {
  if (naturalW <= 0 || naturalH <= 0) return null;
  if (boxes.length === 0) return null;
  const strokeWidth = Math.max(2, Math.min(naturalW, naturalH) / 200);
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox={`0 0 ${naturalW} ${naturalH}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
      data-testid="face-overlay"
    >
      {boxes.map((b, i) => {
        const dim =
          highlightClusterId !== null &&
          b.clusterId !== null &&
          b.clusterId !== highlightClusterId;
        return (
          <rect
            key={i}
            x={b.x}
            y={b.y}
            width={b.w}
            height={b.h}
            fill="none"
            stroke={dim ? "hsl(var(--muted-foreground))" : "hsl(var(--primary))"}
            strokeOpacity={dim ? 0.45 : 1}
            strokeWidth={strokeWidth}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}