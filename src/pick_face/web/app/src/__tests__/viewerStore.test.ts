// viewerStore — pure zustand store. No DOM, easy to test.

import { describe, expect, it } from "vitest";
import { useViewerStore } from "@/lib/viewerStore";

const roster = [
  { id: 1, url: "/api/photos/1", thumbUrl: "/api/photos/1/thumb", width: 800, height: 600 },
  { id: 2, url: "/api/photos/2", thumbUrl: "/api/photos/2/thumb", width: 800, height: 600 },
  { id: 3, url: "/api/photos/3", thumbUrl: "/api/photos/3/thumb", width: 800, height: 600 },
];

describe("useViewerStore", () => {
  it("starts closed", () => {
    const s = useViewerStore.getState();
    expect(s.open).toBe(false);
    expect(s.photos).toEqual([]);
    expect(s.index).toBe(0);
  });

  it("opens with initial index + resets zoom/pan", () => {
    useViewerStore.setState({ scale: 4, pan: { x: 100, y: 100 } });
    useViewerStore.getState().openViewer(7, roster, 1);
    const s = useViewerStore.getState();
    expect(s.open).toBe(true);
    expect(s.personId).toBe(7);
    expect(s.photos).toEqual(roster);
    expect(s.index).toBe(1);
    expect(s.scale).toBe(1);
    expect(s.pan).toEqual({ x: 0, y: 0 });
  });

  it("clamps initial index to valid range", () => {
    useViewerStore.getState().openViewer(7, roster, 999);
    expect(useViewerStore.getState().index).toBe(2);

    useViewerStore.getState().openViewer(7, roster, -5);
    expect(useViewerStore.getState().index).toBe(0);
  });

  it("next/prev move within bounds and reset view", () => {
    useViewerStore.getState().openViewer(7, roster, 1);
    useViewerStore.setState({ scale: 2.5, pan: { x: 50, y: 50 } });

    useViewerStore.getState().next();
    expect(useViewerStore.getState().index).toBe(2);
    expect(useViewerStore.getState().scale).toBe(1);
    expect(useViewerStore.getState().pan).toEqual({ x: 0, y: 0 });

    useViewerStore.getState().next();
    expect(useViewerStore.getState().index).toBe(2); // clamped

    useViewerStore.getState().prev();
    expect(useViewerStore.getState().index).toBe(1);

    useViewerStore.getState().prev();
    useViewerStore.getState().prev();
    expect(useViewerStore.getState().index).toBe(0); // clamped
  });

  it("setZoom clamps to [0.1, 8]", () => {
    useViewerStore.getState().setZoom(0.001);
    expect(useViewerStore.getState().scale).toBe(0.1);
    useViewerStore.getState().setZoom(99);
    expect(useViewerStore.getState().scale).toBe(8);
    useViewerStore.getState().setZoom(2);
    expect(useViewerStore.getState().scale).toBe(2);
  });

  it("toggleFullscreen flips the boolean", () => {
    expect(useViewerStore.getState().fullscreen).toBe(false);
    useViewerStore.getState().toggleFullscreen();
    expect(useViewerStore.getState().fullscreen).toBe(true);
    useViewerStore.getState().toggleFullscreen();
    expect(useViewerStore.getState().fullscreen).toBe(false);
  });

  it("closeViewer resets state", () => {
    useViewerStore.getState().openViewer(7, roster, 1);
    useViewerStore.setState({ fullscreen: true });
    useViewerStore.getState().closeViewer();
    const s = useViewerStore.getState();
    expect(s.open).toBe(false);
    expect(s.fullscreen).toBe(false);
  });
});