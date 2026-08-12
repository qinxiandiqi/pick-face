// Typed response shapes for every pick-face Web service endpoint.
// These mirror the Pydantic models declared in:
//   - src/pick_face/api/config.py
//   - src/pick_face/api/scan.py
//   - src/pick_face/api/persons.py
//   - src/pick_face/api/photos.py
//   - src/pick_face/api/health.py
//
// We hand-mirror rather than openapi-codegen: 14 endpoints, all Pydantic-
// typed, all small. Re-evaluate at M9 if endpoint count triples.

import { z } from "zod";

// ============================================================================
// Common
// ============================================================================

export const ErrorCode = z.enum([
  "NOT_FOUND",
  "NOT_A_DIRECTORY",
  "NOT_READABLE",
  "PATH_TRAVERSAL",
  "DUPLICATE",
  "NOT_WHITELISTED",
  "INVALID_PATH",
  "INTERNAL",
]);
export type ErrorCode = z.infer<typeof ErrorCode>;

export const ApiErrorSchema = z.object({
  code: ErrorCode,
  message: z.string(),
  detail: z.unknown().optional(),
});
export type ApiErrorBody = z.infer<typeof ApiErrorSchema>;

// ============================================================================
// Health
// ============================================================================

export const HealthResponseSchema = z.object({
  status: z.string(),
});
export type HealthResponse = z.infer<typeof HealthResponseSchema>;

export const ReadyResponseSchema = z.object({
  status: z.string(),
  data_dir: z.string().optional(),
  db: z.string().optional(),
  jobs: z.number().int().nonnegative().optional(),
});
export type ReadyResponse = z.infer<typeof ReadyResponseSchema>;

// ============================================================================
// Config (path whitelist)
// ============================================================================

export const WhitelistedPathSchema = z.object({
  id: z.number().int(),
  path: z.string(),
  enabled: z.boolean(),
  notes: z.string().optional().nullable(),
  created_at: z.string().optional().nullable(),
});
export type WhitelistedPath = z.infer<typeof WhitelistedPathSchema>;

export const PathAddSchema = z.object({
  path: z.string().min(1, "Path is required"),
  notes: z.string().optional(),
  enabled: z.boolean().optional().default(true),
});
export type PathAdd = z.infer<typeof PathAddSchema>;

export const PathUpdateSchema = z.object({
  enabled: z.boolean().optional(),
  notes: z.string().optional(),
});
export type PathUpdate = z.infer<typeof PathUpdateSchema>;

// ============================================================================
// Scan jobs
// ============================================================================

export const ScanState = z.enum([
  "QUEUED",
  "RUNNING",
  "DONE",
  "FAILED",
  "CANCELLED",
]);
export type ScanState = z.infer<typeof ScanState>;

export const ScanJobSchema = z.object({
  id: z.string(),
  kind: z.string(), // "incremental" | "full"
  state: ScanState,
  progress: z.object({
    processed: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
    faces: z.number().int().nonnegative(),
    errors: z.number().int().nonnegative(),
  }),
  started_at: z.string().optional().nullable(),
  ended_at: z.string().optional().nullable(),
  error: z.string().optional().nullable(),
});
export type ScanJob = z.infer<typeof ScanJobSchema>;

export const ScanProgressEventSchema = z.object({
  job_id: z.string(),
  state: ScanState,
  processed: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
  faces: z.number().int().nonnegative(),
  errors: z.number().int().nonnegative(),
});
export type ScanProgressEvent = z.infer<typeof ScanProgressEventSchema>;

// ============================================================================
// Persons (virtual albums)
// ============================================================================

export const PersonSchema = z.object({
  id: z.number().int(),
  name: z.string().nullable(),
  photo_count: z.number().int().nonnegative(),
  cover_face_id: z.number().int().nullable(),
});
export type Person = z.infer<typeof PersonSchema>;

export const PersonDetailSchema = z.object({
  id: z.number().int(),
  name: z.string().nullable(),
  photo_count: z.number().int().nonnegative(),
  cover_face_id: z.number().int().nullable(),
  sources: z.array(z.string()).optional().default([]),
});
export type PersonDetail = z.infer<typeof PersonDetailSchema>;

export const PersonPhotoSchema = z.object({
  photo_id: z.number().int(),
  url: z.string(),
  thumb_url: z.string(),
  width: z.number().int().nonnegative().optional(),
  height: z.number().int().nonnegative().optional(),
});
export type PersonPhoto = z.infer<typeof PersonPhotoSchema>;

// ============================================================================
// Photos
// ============================================================================

export const PhotoMetaSchema = z.object({
  id: z.number().int(),
  path: z.string(),
  mtime: z.number(),
  cluster_id: z.number().int().nullable(),
  url: z.string(),
  thumb_url: z.string(),
});
export type PhotoMeta = z.infer<typeof PhotoMetaSchema>;