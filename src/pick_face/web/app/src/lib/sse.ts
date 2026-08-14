// Typed EventSource wrapper for `/api/scan/jobs/{id}/events`.
//
// Events emitted by the backend (see `src/pick_face/api/scan.py`):
//   - "progress"   → ScanProgressEvent payload (existing)
//   - "new_photo"  → ScanNewPhotoEvent payload (M8-T-8)
//   - "new_person" → ScanNewPersonEvent payload (M8-T-8)
//   - "merged"     → ScanMergedEvent payload (M8-T-8)
//   - "closed"     → upstream disconnected; client may close + retry
//   - "end"        → terminal state reached; stream closes
//
// Browser EventSource cannot send custom headers and has no POST support;
// we use it as-is since the scan-events endpoint is GET-only.

import { z } from "zod";
import {
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