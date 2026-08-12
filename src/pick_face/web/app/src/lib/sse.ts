// Typed EventSource wrapper for `/api/scan/jobs/{id}/events`.
//
// Events emitted by the backend (see `src/pick_face/api/scan.py:170-178`):
//   - "progress" → ScanProgressEvent payload
//   - "closed"   → upstream disconnected; client may close + retry
//   - "end"      → terminal state reached; stream closes
//
// Browser EventSource cannot send custom headers and has no POST support;
// we use it as-is since the scan-events endpoint is GET-only.

import { z } from "zod";
import { ScanProgressEventSchema } from "@/lib/api/schemas";

export interface ScanEventStreamHandlers {
  onProgress: (e: z.infer<typeof ScanProgressEventSchema>) => void;
  onClosed?: () => void;
  onEnd?: () => void;
  onError?: (err: Event) => void;
}

export function openScanEventStream(
  jobId: string,
  handlers: ScanEventStreamHandlers,
): EventSource {
  const es = new EventSource(`/api/scan/jobs/${jobId}/events`, {
    withCredentials: false,
  });

  es.addEventListener("progress", (ev) => {
    try {
      const parsed = ScanProgressEventSchema.safeParse(JSON.parse((ev as MessageEvent).data));
      if (parsed.success) handlers.onProgress(parsed.data);
    } catch {
      // malformed event payload — ignore; onError will fire on next issue
    }
  });

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