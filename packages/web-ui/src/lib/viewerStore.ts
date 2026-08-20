// viewerStore — zustand store backing the FaceViewer state. Lives in
// `lib/` so the PersonDetailPage (which sets initial state) and the
// FaceViewer (which reads/mutates state) both import the same instance.

import { create } from "zustand";

export interface ViewerPhoto {
  id: number;
  url: string;
  thumbUrl: string;
  width: number;
  height: number;
}

export interface ViewerState {
  open: boolean;
  personId: number | null;
  photos: ViewerPhoto[];
  index: number;
  scale: number;
  pan: { x: number; y: number };
  fullscreen: boolean;

  // Actions
  openViewer: (personId: number, photos: ViewerPhoto[], initialIndex: number) => void;
  closeViewer: () => void;
  next: () => void;
  prev: () => void;
  setZoom: (z: number) => void;
  setPan: (p: { x: number; y: number }) => void;
  resetView: () => void;
  toggleFullscreen: () => void;
}

export const useViewerStore = create<ViewerState>((set, get) => ({
  open: false,
  personId: null,
  photos: [],
  index: 0,
  scale: 1,
  pan: { x: 0, y: 0 },
  fullscreen: false,

  openViewer: (personId, photos, initialIndex) =>
    set({
      open: true,
      personId,
      photos,
      index: Math.max(0, Math.min(initialIndex, photos.length - 1)),
      scale: 1,
      pan: { x: 0, y: 0 },
    }),
  closeViewer: () => set({ open: false, fullscreen: false }),
  next: () => {
    const s = get();
    if (s.photos.length === 0) return;
    set({ index: Math.min(s.photos.length - 1, s.index + 1), scale: 1, pan: { x: 0, y: 0 } });
  },
  prev: () => {
    const s = get();
    if (s.photos.length === 0) return;
    set({ index: Math.max(0, s.index - 1), scale: 1, pan: { x: 0, y: 0 } });
  },
  setZoom: (z) => set({ scale: Math.max(0.1, Math.min(8, z)) }),
  setPan: (p) => set({ pan: p }),
  resetView: () => set({ scale: 1, pan: { x: 0, y: 0 } }),
  toggleFullscreen: () => set((s) => ({ fullscreen: !s.fullscreen })),
}));

// Convenience selector for the slice used by FaceViewer/useViewerControls.
export type ViewerStoreApi = typeof useViewerStore;

// Re-export the slice type for tooling.
export type { ViewerState as ViewerStateType };
// silence the unused export warning under strict
void (null as unknown as ViewerStoreApi);

// Re-export so callers can do `useViewerStore.getState()` without aliasing.
export const viewerStoreSlice = useViewerStore;