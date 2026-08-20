// TanStack Query hooks for every endpoint. Query keys are stable strings
// so `invalidateQueries({ queryKey: ['paths'] })` does the right thing.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import * as React from "react";
import { useEffect } from "react";

import { api } from "@/lib/api/client";
import type {
  HealthResponse,
  PathAdd,
  PathUpdate,
  PersonDetail,
  PersonPhoto,
  PhotoMeta,
  PhotoMetadata,
  ReadyResponse,
  ScanJob,
  WhitelistedPath,
} from "@/lib/api/schemas";

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export function useHealthQuery(): UseQueryResult<HealthResponse> {
  return useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });
}

export function useReadyQuery(): UseQueryResult<ReadyResponse> {
  return useQuery({ queryKey: ["ready"], queryFn: () => api.ready(), staleTime: 30_000 });
}

// ---------------------------------------------------------------------------
// Path whitelist
// ---------------------------------------------------------------------------

export function usePathsQuery(): UseQueryResult<{ paths: WhitelistedPath[] }> {
  return useQuery({
    queryKey: ["paths"],
    queryFn: () => api.listPaths(),
    staleTime: 5_000,
  });
}

export function useAddPathMutation(): UseMutationResult<WhitelistedPath, Error, PathAdd> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data) => api.addPath(data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["paths"] });
      void qc.invalidateQueries({ queryKey: ["paths-enabled"] });
    },
  });
}

export function useUpdatePathMutation(): UseMutationResult<
  WhitelistedPath,
  Error,
  { id: number; data: PathUpdate }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }) => api.updatePath(id, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["paths"] });
      void qc.invalidateQueries({ queryKey: ["paths-enabled"] });
    },
  });
}

export function useDeletePathMutation(): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.deletePath(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["paths"] });
      void qc.invalidateQueries({ queryKey: ["paths-enabled"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

// Push-based replacement for the legacy `useActiveScanJobQuery`
// polling hook (M8 → SSE switchover). Opens an EventSource to
// ``/api/scan/events``, which emits a ``snapshot`` on connect and a
// ``job_update`` whenever the active job's identity / state / progress
// changes. Returns the same ``{data: ScanJob | null}`` shape so the
// ScanProgressBanner can swap implementations without rewiring callers.
//
// The browser's EventSource auto-reconnects on transient errors; we
// just surface a single ``onError`` toast in the consuming banner.
//
// Implementation note: we deliberately do NOT use ``useQuery`` here —
// SSE state lives outside the TanStack cache and re-renders are driven
// by React state updates inside the effect below. Reusing the
// ``["scan-active"]`` key would cause two competing sources of truth.
export function useActiveScanJobStream(): {
  data: ScanJob | null;
  status: "connecting" | "open" | "closed";
} {
  const [data, setData] = React.useState<ScanJob | null>(null);
  const [status, setStatus] = React.useState<"connecting" | "open" | "closed">("connecting");

  useEffect(() => {
    // EventSource is a browser-only constructor; dynamic-import the
    // helper so SSR / jsdom-without-polyfill tests can import this
    // module without crashing.
    let es: EventSource | null = null;
    let cancelled = false;
    void (async () => {
      try {
        const { openGlobalScanEventStream } = await import("@/lib/sse");
        if (cancelled) return;
        es = openGlobalScanEventStream({
          onSnapshot: (job) => {
            setData(job);
            setStatus("open");
          },
          onJobUpdate: (job) => {
            setData(job);
          },
          onError: () => {
            setStatus("closed");
            // Browser EventSource auto-reconnects; the next
            // ``snapshot`` event will flip status back to "open".
          },
        });
      } catch {
        // EventSource unavailable (SSR, Node test env). Leave data as
        // null — banner renders nothing, same as before any scan.
        setStatus("closed");
      }
    })();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, []);

  return { data, status };
}

export function useStartScanMutation(): UseMutationResult<{ id: string }, Error, "incremental" | "full"> {
  // No cache invalidation needed — the global ``/api/scan/events``
  // SSE pushes a fresh ``job_update`` when the runner transitions
  // the new job to RUNNING, which the banner picks up automatically.
  return useMutation({
    mutationFn: (kind) => api.startScanJob(kind),
  });
}

// ---------------------------------------------------------------------------
// Persons
// ---------------------------------------------------------------------------

export function usePersonsQuery(limit = 50): UseQueryResult<{ persons: import("@/lib/api/schemas").Person[] }> {
  return useQuery({
    queryKey: ["persons", limit],
    queryFn: () => api.listPersons(limit),
    staleTime: 5_000,
  });
}

export function usePersonQuery(id: number | null): UseQueryResult<PersonDetail> {
  return useQuery({
    queryKey: ["person", id],
    queryFn: () => api.getPerson(id!),
    enabled: id !== null,
  });
}

export function usePersonPhotosQuery(
  id: number | null,
  limit = 200,
): UseQueryResult<{ photos: PersonPhoto[] }> {
  return useQuery({
    queryKey: ["person-photos", id, limit],
    queryFn: () => api.getPersonPhotos(id!, limit),
    enabled: id !== null,
  });
}

// ---------------------------------------------------------------------------
// Photos
// ---------------------------------------------------------------------------

export function usePhotoMetaQuery(id: number | null): UseQueryResult<PhotoMeta> {
  return useQuery({
    queryKey: ["photo-meta", id],
    queryFn: () => api.getPhotoMeta(id!),
    enabled: id !== null,
  });
}

// M7.5 — extended metadata (path + faces + bbox + cluster_id). Used by
// FaceViewer to draw the SVG overlay and by the EXIF side-sheet.
export function usePhotoMetadataQuery(
  id: number | null,
): UseQueryResult<PhotoMetadata> {
  return useQuery({
    queryKey: ["photo-metadata", id],
    queryFn: () => api.getPhotoMetadata(id!),
    enabled: id !== null,
  });
}

// ---------------------------------------------------------------------------
// M8-T-8 — persons live invalidator. Subscribes to SSE events that
// signal cluster-side mutations (`new_photo` / `new_person` / `merged`)
// and refetches any active `persons` query. Used by the SPA
// ScanProgressBanner so the Persons grid refreshes within ~0.5s of an
// incremental event instead of waiting for the next global ``job_update``.
//
// The hook takes a jobId (typically `useActiveScanJobStream`'s result)
// and silently does nothing when the job is null or already terminal.
// ---------------------------------------------------------------------------

export function usePersonsLiveInvalidator(
  jobId: string | null | undefined,
  options?: { onNewPhoto?: () => void; onNewPerson?: () => void; onMerged?: () => void },
): void {
  const qc = useQueryClient();
  useEffect(() => {
    if (!jobId) return;
    // Dynamic import so test environments without a window object
    // (jsdom without EventSource) don't crash on module load.
    let es: EventSource | null = null;
    let cancelled = false;
    void (async () => {
      try {
        const { openScanEventStream } = await import("@/lib/sse");
        if (cancelled) return;
        es = openScanEventStream(jobId, {
          // We never receive progress here (the banner has its own
          // consumer); suppress the required handler with a no-op.
          onProgress: () => {},
          onNewPhoto: (e) => {
            options?.onNewPhoto?.();
            void qc.invalidateQueries({ queryKey: ["persons"] });
            // photo count + face count may have changed.
            if (e.photo_id) {
              void qc.invalidateQueries({
                queryKey: ["photo-metadata", e.photo_id],
              });
            }
          },
          onNewPerson: () => {
            options?.onNewPerson?.();
            void qc.invalidateQueries({ queryKey: ["persons"] });
          },
          onMerged: () => {
            options?.onMerged?.();
            void qc.invalidateQueries({ queryKey: ["persons"] });
          },
        });
      } catch {
        // EventSource unavailable (SSR, test env without polyfill).
        // Fall back to the polling cadence of usePersonsQuery.
      }
    })();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [jobId, qc, options]);
}