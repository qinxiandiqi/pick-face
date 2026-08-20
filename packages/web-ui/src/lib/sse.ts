// Typed EventSource wrapper.
//
// Two streams are exposed:
//
//   1. Per-job stream  — `/api/scan/jobs/{id}/events` (existing, M8-T-8).
//      Emits per-image ``new_photo`` / per-cluster ``new_person`` /
//      per-merge ``merged`` events; consumed by ``usePersonsLiveInvalidator``.
//      Also emits per-tick ``progress`` for the legacy per-job banner.
//
//   2. Global stream   — `/api/scan/events` (new). Emits ``snapshot`` on
//      connect and ``job_update`` whenever the *active* job's identity,
//      state, or progress changes. Consumed by the SPA
//      ``ScanProgressBanner`` as a polling replacement.
//
// Browser EventSource cannot send custom headers and has no POST support;
// we use it as-is since both scan-events endpoints are GET-only.

import { z } from "zod";
import {
  ScanJob,
  ScanJobSchema,
  ScanMergedEventSchema,
  ScanNewPersonEventSchema,
  ScanNewPhotoEventSchema,
  ScanProgressEventSchema,
} from "@/lib/api/schemas";

export interface ScanEventStreamHandlers {
  onProgress: (e: z.infer<typeof ScanProgressEventSchema>) => void;
  /** M8-T-8: emitted per scanned image that yielded ≥ 1 face. */
  onNewPhoto?: (e: z.infer<typeof ScanNewPhotoEventSchema>) => void;
  /** M8-T-8: emitted when the cluster worker inserts a new cluster row. */
  onNewPerson?: (e: z.infer<typeof ScanNewPersonEventSchema>) => void;
  /** M8-T-8: emitted when two clusters merge during recluster. */
  onMerged?: (e: z.infer<typeof ScanMergedEventSchema>) => void;
  onClosed?: () => void;
  onEnd?: () => void;
  onError?: (err: Event) => void;
}

/** Bind a typed payload handler. Skipped when the handler is undefined. */
function bindPayload<T>(
  es: EventSource,
  name: string,
  schema: z.ZodType<T>,
  handler: ((e: T) => void) | undefined,
): void {
  if (!handler) return;
  es.addEventListener(name, (ev) => {
    try {
      const parsed = schema.safeParse(JSON.parse((ev as MessageEvent).data));
      if (parsed.success) handler(parsed.data);
    } catch {
      // malformed event payload — ignore; onError will fire on next issue
    }
  });
}

export function openScanEventStream(
  jobId: string,
  handlers: ScanEventStreamHandlers,
): EventSource {
  const es = new EventSource(`/api/scan/jobs/${jobId}/events`, {
    withCredentials: false,
  });

  bindPayload(es, "progress", ScanProgressEventSchema, handlers.onProgress);
  bindPayload(es, "new_photo", ScanNewPhotoEventSchema, handlers.onNewPhoto);
  bindPayload(es, "new_person", ScanNewPersonEventSchema, handlers.onNewPerson);
  bindPayload(es, "merged", ScanMergedEventSchema, handlers.onMerged);

  es.addEventListener("closed", () => {
    handlers.onClosed?.();
    es.close();
  });

  es.addEventListener("end", () => {
    handlers.onEnd?.();
    es.close();
  });

  es.addEventListener("error", (ev) => {
    handlers.onError?.(ev);
  });

  return es;
}

// ============================================================================
// Global scan-events stream  — `/api/scan/events`
// ============================================================================
//
// Pushes the *active* scan job to subscribed browsers, replacing the
// 2-second TanStack Query refetchInterval the banner used to drive.
// The server emits a full ``ScanJob`` payload on every state / progress
// change; we expose it via ``onSnapshot`` (initial state) and
// ``onJobUpdate`` (subsequent changes). The browser-side EventSource
// auto-reconnects on transient errors so a stale ``null`` snapshot
// followed by a fresh ``job_update`` is enough to recover from a
// dropped backend connection.

export interface GlobalScanEventStreamHandlers {
  /** Initial active job (or null). Fired once on connect. */
  onSnapshot: (job: ScanJob | null) => void;
  /** Active job changed (state, progress, or a new job took over). */
  onJobUpdate?: (job: ScanJob | null) => void;
  /** Heartbeat — purely informational; default handler is a no-op. */
  onPing?: () => void;
  /** Network error — the browser will auto-reconnect, but you can surface UI. */
  onError?: (err: Event) => void;
}

export function openGlobalScanEventStream(
  handlers: GlobalScanEventStreamHandlers,
): EventSource {
  const es = new EventSource(`/api/scan/events`, { withCredentials: false });

  bindPayload(es, "snapshot", ScanJobSchema.nullable(), handlers.onSnapshot);
  bindPayload(es, "job_update", ScanJobSchema.nullable(), handlers.onJobUpdate);

  if (handlers.onPing) {
    es.addEventListener("ping", () => handlers.onPing?.());
  }

  es.addEventListener("error", (ev) => {
    handlers.onError?.(ev);
  });

  return es;
}