// TanStack Query hooks for every endpoint. Query keys are stable strings
// so `invalidateQueries({ queryKey: ['paths'] })` does the right thing.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

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