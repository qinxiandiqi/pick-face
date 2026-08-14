// TanStack Query hooks for every endpoint. Query keys are stable strings
// so `invalidateQueries({ queryKey: ['paths'] })` does the right thing.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
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

export function useActiveScanJobQuery(opts?: { refetchInterval?: number }): UseQueryResult<ScanJob | null> {
  return useQuery({
    queryKey: ["scan-active"],
    queryFn: () => api.getActiveScanJob(),
    refetchInterval: opts?.refetchInterval ?? 2_000,
  });
}

export function useStartScanMutation(): UseMutationResult<{ id: string }, Error, "incremental" | "full"> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kind) => api.startScanJob(kind),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["scan-active"] });
    },
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
// incremental event instead of waiting for the next `scan-active`
// poll tick.
//
// The hook takes a jobId (typically `useActiveScanJobQuery`'s result)
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
            void qc.invalidateQueries({ queryKey: ["scan-active"] });
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