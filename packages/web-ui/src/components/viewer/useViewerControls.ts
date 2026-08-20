// useViewerControls — encapsulates all gesture / keyboard / wheel logic
// for the FaceViewer (M7-T-1..T-5).
//
// Math reference (see plan):
//   fitScale = Math.min(viewportW / naturalW, viewportH / naturalH)
//   wheel:   scale = clamp(scale * (1 - dy * 0.002), 0.1, 8)
//            tx   = cursorX - (cursorX - tx) * (newScale / oldScale)
//   pan clamp: when scaledW <= viewportW → tx = (viewportW - scaledW) / 2
//              else                     → tx ∈ [viewportW - scaledW, 0]
//   pinch:   scale around centroid
//   dblclk:  toggle fitScale ↔ 2 * fitScale (center pan)

import { useEffect, useRef } from "react";
import { useGesture } from "@use-gesture/react";

import { useViewerStore } from "@/lib/viewerStore";

export interface UseViewerControlsArgs {
  naturalW: number;
  naturalH: number;
  viewportW: number;
  viewportH: number;
  enabled: boolean;
}

export function useViewerControls({
  naturalW,
  naturalH,
  viewportW,
  viewportH,
  enabled,
}: UseViewerControlsArgs): {
  onWheel: (e: React.WheelEvent) => void;
} {
  const fitScale =
    naturalW > 0 && naturalH > 0 && viewportW > 0 && viewportH > 0
      ? Math.min(viewportW / naturalW, viewportH / naturalH)
      : 1;

  // Always read the latest store state inside callbacks via getState().
  useGesture(
    {
      onDrag: ({ offset: [ox, oy], pinching, cancel }) => {
        if (pinching) {
          cancel?.();
          return;
        }
        const s = useViewerStore.getState();
        const clamped = clampPan(
          ox,
          oy,
          s.scale * naturalW,
          s.scale * naturalH,
          viewportW,
          viewportH,
        );
        useViewerStore.setState({ pan: { x: clamped.x, y: clamped.y } });
      },
      // @use-gesture/react's `onPinch` state doesn't surface `scale` in its
      // public type — it's available at runtime as the gesture's incremental
      // multiplier. Cast the whole arg to read it.
      onPinch: ((arg: unknown) => {
        const { origin: [ox, oy], scale: ps } = arg as {
          origin: [number, number];
          scale: number;
        };
        const s = useViewerStore.getState();
        const newScale = clamp(s.scale * ps, 0.1, 8);
        // Recenter pan to keep the pinch origin under the same image pixel.
        const ratio = newScale / s.scale;
        const newPan = clampPan(
          ox - (ox - s.pan.x) * ratio,
          oy - (oy - s.pan.y) * ratio,
          newScale * naturalW,
          newScale * naturalH,
          viewportW,
          viewportH,
        );
        useViewerStore.setState({ scale: newScale, pan: newPan });
      }) as unknown as Parameters<typeof useGesture>[0]["onPinch"],
      onDoubleClick: ({ event }) => {
        event?.preventDefault();
        const s = useViewerStore.getState();
        const target = fitScale * 2;
        const next = Math.abs(s.scale - fitScale) < 0.01 ? target : fitScale;
        const newPan = clampPan(
          (viewportW - next * naturalW) / 2,
          (viewportH - next * naturalH) / 2,
          next * naturalW,
          next * naturalH,
          viewportW,
          viewportH,
        );
        useViewerStore.setState({ scale: next, pan: newPan });
      },
    },
    {
      target: typeof window !== "undefined" ? window : undefined,
      eventOptions: { passive: false },
      enabled,
      drag: { from: () => [useViewerStore.getState().pan.x, useViewerStore.getState().pan.y] },
      pinch: { from: () => [1, useViewerStore.getState().scale], scaleBounds: { min: 0.1, max: 8 } },
    },
  );

  // Wheel handler — attached manually so we can preventDefault().
  const wheelHandler = useRef<(e: React.WheelEvent) => void>(undefined);
  wheelHandler.current = (e: React.WheelEvent) => {
    if (!enabled) return;
    e.preventDefault?.();
    const s = useViewerStore.getState();
    const newScale = clamp(s.scale * (1 - e.deltaY * 0.002), 0.1, 8);
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const cursorX = e.clientX - rect.left;
    const cursorY = e.clientY - rect.top;
    const ratio = newScale / s.scale;
    const newPan = clampPan(
      cursorX - (cursorX - s.pan.x) * ratio,
      cursorY - (cursorY - s.pan.y) * ratio,
      newScale * naturalW,
      newScale * naturalH,
      viewportW,
      viewportH,
    );
    useViewerStore.setState({ scale: newScale, pan: newPan });
  };

  // Global keyboard handler — only attached while open.
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const s = useViewerStore.getState();
      switch (e.key) {
        case "ArrowLeft":
        case "PageUp":
          e.preventDefault();
          s.prev();
          break;
        case "ArrowRight":
        case "PageDown":
        case " ":
          e.preventDefault();
          s.next();
          break;
        case "+":
        case "=":
          e.preventDefault();
          useViewerStore.setState({ scale: clamp(s.scale * 1.2, 0.1, 8) });
          break;
        case "-":
        case "_":
          e.preventDefault();
          useViewerStore.setState({ scale: clamp(s.scale / 1.2, 0.1, 8) });
          break;
        case "0":
          e.preventDefault();
          useViewerStore.setState({
            scale: fitScale,
            pan: {
              x: (viewportW - fitScale * naturalW) / 2,
              y: (viewportH - fitScale * naturalH) / 2,
            },
          });
          break;
        case "f":
        case "F":
          e.preventDefault();
          s.toggleFullscreen();
          break;
        // Escape is handled by Dialog — don't double-handle.
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, fitScale, naturalW, naturalH, viewportW, viewportH]);

  return {
    onWheel: (e: React.WheelEvent) => wheelHandler.current?.(e),
  };
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function clampPan(
  tx: number,
  ty: number,
  scaledW: number,
  scaledH: number,
  viewportW: number,
  viewportH: number,
): { x: number; y: number } {
  let x: number;
  let y: number;
  if (scaledW <= viewportW) {
    x = (viewportW - scaledW) / 2;
  } else {
    x = clamp(tx, viewportW - scaledW, 0);
  }
  if (scaledH <= viewportH) {
    y = (viewportH - scaledH) / 2;
  } else {
    y = clamp(ty, viewportH - scaledH, 0);
  }
  return { x, y };
}
