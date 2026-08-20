// Scan progress banner — polls /api/scan/jobs/active, opens an SSE stream
// when a job is running, renders a Progress bar. On `end` event: closes
// the EventSource, fires a toast via the @/lib/toast facade, invalidates
// persons cache.
//
// Mounted at the AppShell level (above the route outlet) so the banner
// stays visible while the user navigates between pages.

import * as React from "react";
import { useEffect } from "react";
import { Loader2, X } from "lucide-react";

import {
  useActiveScanJobQuery,
  usePersonsLiveInvalidator,
  useStartScanMutation,
} from "@/lib/api/hooks";
import { openScanEventStream } from "@/lib/sse";
import { toast } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

export function ScanProgressBanner(): React.JSX.Element | null {
  const { data: job } = useActiveScanJobQuery({ refetchInterval: 2_000 });
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

  // Local mirror of the progress payload so we can render without
  // hammering the API while SSE is open.
  const [localProgress, setLocalProgress] = React.useState<{
    processed: number;
    total: number;
    faces: number;
  } | null>(null);

  useEffect(() => {
    if (!job || job.state !== "RUNNING") {
      setLocalProgress(null);
      return;
    }
    setLocalProgress({
      processed: job.progress.processed,
      total: job.progress.total,
      faces: job.progress.faces,
    });

    const es = openScanEventStream(job.id, {
      onProgress: (e) => {
        setLocalProgress({
          processed: e.processed,
          total: e.total,
          faces: e.faces,
        });
      },
      onEnd: () => {
        toast.success(`Scan complete · ${localProgress?.faces ?? 0} faces`);
        setLocalProgress(null);
      },
      onError: () => {
        toast.error("Scan stream disconnected");
        setLocalProgress(null);
      },
    });

    return () => es.close();
    // We intentionally exclude `localProgress` from deps to avoid resubscribing
    // on every progress event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.state]);

  if (!job) return null;

  const progress = localProgress ?? job.progress;
  const pct = progress.total > 0 ? Math.min(100, (progress.processed / progress.total) * 100) : 0;

  return (
    <div
      className="flex items-center gap-3 border-b bg-muted/40 px-4 py-2 text-sm"
      data-testid="scan-progress-banner"
    >
      {job.state === "RUNNING" ? (
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
      {!job.state.startsWith("DONE") && job.state !== "FAILED" && job.state !== "CANCELLED" && (
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
      {job.state === "RUNNING" && (
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