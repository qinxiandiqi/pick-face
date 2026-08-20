// Scan progress banner — drives its job state from a single SSE
// connection (`/api/scan/events`), renders a progress bar, and fires
// toasts on terminal state. The per-job SSE (`/jobs/{id}/events`) is
// kept open only for `new_photo` / `new_person` / `merged` events
// (M8-T-8) — consumed by usePersonsLiveInvalidator below.
//
// Mounted at the AppShell level (above the route outlet) so the banner
// stays visible while the user navigates between pages.

import * as React from "react";
import { Loader2, X } from "lucide-react";

import {
  useActiveScanJobStream,
  usePersonsLiveInvalidator,
  useStartScanMutation,
} from "@/lib/api/hooks";
import { toast } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

export function ScanProgressBanner(): React.JSX.Element | null {
  // Global SSE: snapshot + job_update events cover both state
  // transitions AND progress ticks. No polling.
  const { data: job } = useActiveScanJobStream();
  const startScan = useStartScanMutation();

  // M8-T-8 — when a scan is running, refetch the persons grid on each
  // new_photo / new_person / merged event. The hook auto-cleans up
  // when the job terminates.
  usePersonsLiveInvalidator(job?.id, {
    onNewPhoto: () => {
      // Throttled toast: fire at most once per 1.5s so a 50-photo
      // burst doesn't spam the UI.
      flashNewPhotoToast();
    },
    onNewPerson: () => {
      toast.success("New person detected");
    },
    onMerged: () => {
      // Silent — merged clusters are an internal bookkeeping event.
    },
  });

  // Track the previous job so we can fire a "Scan complete" toast
  // exactly once when a RUNNING job transitions to a terminal state.
  const prevStateRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    const prev = prevStateRef.current;
    prevStateRef.current = job?.state ?? null;
    if (
      prev === "running" &&
      job &&
      (job.state === "done" || job.state === "failed" || job.state === "cancelled")
    ) {
      const verb =
        job.state === "done" ? "complete" : job.state === "failed" ? "failed" : "cancelled";
      toast.success(
        job.state === "done"
          ? `Scan complete · ${job.progress.faces} faces`
          : `Scan ${verb}`,
      );
    }
  }, [job]);

  if (!job) return null;

  const progress = job.progress;
  const pct = progress.total > 0 ? Math.min(100, (progress.processed / progress.total) * 100) : 0;

  return (
    <div
      className="flex items-center gap-3 border-b bg-muted/40 px-4 py-2 text-sm"
      data-testid="scan-progress-banner"
    >
      {job.state === "running" ? (
        <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
      ) : (
        <span className="h-2 w-2 rounded-full bg-muted-foreground" aria-hidden />
      )}
      <div className="flex-1">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {job.state} · {progress.processed}/{progress.total} · {progress.faces} faces
          </span>
          <span>{Math.round(pct)}%</span>
        </div>
        <Progress value={pct} className="mt-1 h-1.5" />
      </div>
      {!job.state.startsWith("done") && job.state !== "failed" && job.state !== "cancelled" && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            startScan.mutate("incremental", {
              onError: (e) => toast.fromError(e, "Could not start scan"),
            })
          }
          disabled={startScan.isPending}
        >
          New scan
        </Button>
      )}
      {job.state === "running" && (
        <Button variant="ghost" size="icon" aria-label="Dismiss">
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

// ---- toast throttle -------------------------------------------------------

let lastNewPhotoToastAt = 0;
function flashNewPhotoToast(): void {
  const now = Date.now();
  if (now - lastNewPhotoToastAt < 1_500) return;
  lastNewPhotoToastAt = now;
  toast.success("New photo indexed");
}