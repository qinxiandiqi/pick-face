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

// M7.7 — /api/ready gains an `active_pack` block so the Model tab can
// render the real pack id + license. license_class drives the
// NC-research Badge (M7-T-13).
export const LicenseClassSchema = z.enum([
  "permissive",
  "nc-research",
  "user-supplied",
]);
export type LicenseClass = z.infer<typeof LicenseClassSchema>;

export const ActivePackSchema = z.object({
  id: z.string(),
  display_name: z.string(),
  license_class: LicenseClassSchema,
  license_name: z.string(),
  license_spdx: z.string(),
  // True iff the pack is not NC-research, OR the user has explicitly
  // accepted the NC-research gate. False means AC-9 will block scans.
  nc_research_acknowledged: z.boolean(),
});
export type ActivePack = z.infer<typeof ActivePackSchema>;

export const ReadyResponseSchema = z.object({
  status: z.string(),
  data_dir: z.string().optional(),
  db: z.string().optional(),
  jobs: z.number().int().nonnegative().optional(),
  active_pack: ActivePackSchema.nullable().optional(),
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

// Wire format: ScanState values are serialized lowercase by the
// backend (`api.scan._serialize` → ``job.state.value`` where the enum
// uses ``"running"`` / ``"queued"`` / …). Earlier the frontend used
// uppercase strings, which made zod silently drop the field on every
// payload — the banner then saw ``state === undefined`` and always
// took the "no spinner" branch. Aligning here means all consumers
// (banner, scan query, SSE events) speak the same vocabulary.
export const ScanState = z.enum([
  "queued",
  "running",
  "paused",
  "done",
  "failed",
  "cancelled",
]);
export type ScanState = z.infer<typeof ScanState>;

export const ScanJobSchema = z.object({
  id: z.string(),
  kind: z.string(), // "incremental" | "full"
  state: ScanState,
  // Backend always emits this; older ``/jobs/active`` responses
  // (M7 and earlier) may omit it — accept either shape so callers
  // can use the same type for both legacy polling and the new
  // global SSE.
  paths: z.array(z.string()).optional(),
  progress: z.object({
    processed: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
    faces: z.number().int().nonnegative(),
    errors: z.number().int().nonnegative(),
    eta_sec: z.number().int().nonnegative().nullable().optional(),
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

// ----------------------------------------------------------------------------
// M8-T-8 — incremental ingestion events (appended to the scan-{id}.events.jsonl
// sidecar; the SSE generator emits them as `event: new_photo` / `new_person` /
// `merged`). The cluster worker doesn't know the active job id when it emits,
// so a "no_job" guard is implemented in the SSE generator (events without a
// matching job are dropped silently).
// ----------------------------------------------------------------------------

export const ScanNewPhotoEventSchema = z.object({
  photo_id: z.number().int().positive(),
  face_count: z.number().int().nonnegative(),
});
export type ScanNewPhotoEvent = z.infer<typeof ScanNewPhotoEventSchema>;

export const ScanNewPersonEventSchema = z.object({
  cluster_id: z.number().int().positive(),
  label: z.string(),
});
export type ScanNewPersonEvent = z.infer<typeof ScanNewPersonEventSchema>;

export const ScanMergedEventSchema = z.object({
  cluster_id: z.number().int().positive(),
  into_cluster_id: z.number().int().positive(),
  face_count: z.number().int().nonnegative(),
});
export type ScanMergedEvent = z.infer<typeof ScanMergedEventSchema>;

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

// M7.5 — extended photo metadata: photo row + every face (bbox + cluster_id).
// Mirrors `pick_face.service.photo_service.PhotoMetadata`.
export const FaceInPhotoSchema = z.object({
  id: z.number().int(),
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]).nullable(),
  cluster_id: z.number().int().nullable(),
  det_score: z.number().nullable(),
  quality: z.number().nullable(),
});
export type FaceInPhoto = z.infer<typeof FaceInPhotoSchema>;

// EXIF block surfaced by /api/photos/{id}/meta (M7.6 — fills the side-sheet).
// Mirrors `pick_face.service.photo_service.ExifRecord`. Every field is
// optional — stripped JPEGs / PNGs return all-null.
export const ExifSchema = z.object({
  make: z.string().nullable(),
  model: z.string().nullable(),
  taken_at: z.number().nullable(),        // epoch seconds (UTC)
  lens: z.string().nullable(),
  exposure: z.number().nullable(),        // seconds
  f_number: z.number().nullable(),
  iso: z.number().int().nullable(),
  focal_length: z.number().nullable(),    // mm
  gps_lat: z.number().nullable(),         // signed decimal degrees
  gps_lon: z.number().nullable(),
});
export type Exif = z.infer<typeof ExifSchema>;

export const PhotoMetadataSchema = z.object({
  id: z.number().int(),
  path: z.string(),
  mtime: z.number(),
  size: z.number().int(),
  content_hash: z.string(),
  natural_width: z.number().int().nullable(),
  natural_height: z.number().int().nullable(),
  faces: z.array(FaceInPhotoSchema),
  exif: ExifSchema,
});
export type PhotoMetadata = z.infer<typeof PhotoMetadataSchema>;