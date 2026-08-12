// Thin fetch wrapper around the FastAPI backend.
//
// - Base URL from `import.meta.env.VITE_API_BASE` (defaults to `/api`).
// - Adds `Content-Type: application/json` for non-GET requests with a body.
// - Throws `ApiError` (typed, with code) on non-2xx responses.
// - Photo URLs (Range, thumb) are returned as plain URL strings — the
//   browser sends Range requests natively for `<img>` tags.

import { env } from "@/lib/env";
import { type ApiErrorBody, ApiErrorSchema } from "@/lib/api/schemas";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: unknown;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.detail = body.detail;
  }
}

function buildUrl(path: string, query?: Record<string, string | number | undefined>): string {
  const base = env.apiBase;
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${base}${cleanPath}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function parseError(res: Response): Promise<never> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    throw new ApiError(res.status, {
      code: "INTERNAL",
      message: `HTTP ${res.status} ${res.statusText}`,
    });
  }
  const parsed = ApiErrorSchema.safeParse(body);
  if (parsed.success) throw new ApiError(res.status, parsed.data);
  throw new ApiError(res.status, {
    code: "INTERNAL",
    message: `HTTP ${res.status} ${res.statusText}`,
    detail: body,
  });
}

async function request<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  query?: Record<string, string | number | undefined>,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  };
  const res = await fetch(buildUrl(path, query), init);
  if (!res.ok) return parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ============================================================================
// Endpoint methods (one per route in docs/03 §2).
// ============================================================================

export const api = {
  // Health
  health: () => request<import("@/lib/api/schemas").HealthResponse>("GET", "/health"),
  ready: () => request<import("@/lib/api/schemas").ReadyResponse>("GET", "/ready"),

  // Config — path whitelist
  listPaths: () =>
    request<{ paths: import("@/lib/api/schemas").WhitelistedPath[] }>(
      "GET",
      "/config/paths",
    ),
  listEnabledPaths: () =>
    request<{ paths: string[] }>("GET", "/config/paths/enabled"),
  addPath: (data: import("@/lib/api/schemas").PathAdd) =>
    request<import("@/lib/api/schemas").WhitelistedPath>(
      "POST",
      "/config/paths",
      data,
    ),
  updatePath: (
    id: number,
    data: import("@/lib/api/schemas").PathUpdate,
  ) =>
    request<import("@/lib/api/schemas").WhitelistedPath>(
      "PATCH",
      `/config/paths/${id}`,
      data,
    ),
  deletePath: (id: number) =>
    request<void>("DELETE", `/config/paths/${id}`),

  // Scan
  listScanJobs: () =>
    request<{ jobs: import("@/lib/api/schemas").ScanJob[] }>("GET", "/scan/jobs"),
  getActiveScanJob: () =>
    request<import("@/lib/api/schemas").ScanJob | null>(
      "GET",
      "/scan/jobs/active",
    ),
  getScanJob: (id: string) =>
    request<import("@/lib/api/schemas").ScanJob>("GET", `/scan/jobs/${id}`),
  startScanJob: (kind: "incremental" | "full") =>
    request<{ id: string }>("POST", "/scan/jobs", { kind }),

  // Persons
  listPersons: (limit = 50) =>
    request<{ persons: import("@/lib/api/schemas").Person[] }>(
      "GET",
      "/persons",
      undefined,
      { limit },
    ),
  countPersons: () =>
    request<{ count: number }>("GET", "/persons/count"),
  getPerson: (id: number) =>
    request<import("@/lib/api/schemas").PersonDetail>("GET", `/persons/${id}`),
  getPersonPhotos: (id: number, limit = 200) =>
    request<{ photos: import("@/lib/api/schemas").PersonPhoto[] }>(
      "GET",
      `/persons/${id}/photos`,
      undefined,
      { limit },
    ),
  getPersonCoverUrl: (id: number): string =>
    buildUrl(`/persons/${id}/cover`),

  // Photos
  getPhotoMeta: (id: number) =>
    request<import("@/lib/api/schemas").PhotoMeta>("GET", `/photos/${id}/meta`),
  // M7.5 — extended metadata including face bbox + cluster_id.
  // The /meta endpoint now returns the rich shape; kept the old name
  // as an alias for the thumbnail page summary.
  getPhotoMetadata: (id: number) =>
    request<import("@/lib/api/schemas").PhotoMetadata>(
      "GET",
      `/photos/${id}/meta`,
    ),
  getPhotoUrl: (id: number): string => buildUrl(`/photos/${id}`),
  getPhotoThumbUrl: (id: number): string => buildUrl(`/photos/${id}/thumb`),
};