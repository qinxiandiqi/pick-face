// SettingsPage — three tabs (M6-T-12).
//
// Paths  : whitelist CRUD via PathList + PathAddDialog (rhf + zod).
// Scan   : start a new scan, view job status. Real SSE progress lives in
//          the global ScanProgressBanner (rendered by AppShell).
// Model  : active pack + license-class Badge (M7-T-13) via
//          <ModelPackCard>, fed by /api/ready.active_pack.

import * as React from "react";
import { useEffect, useRef, useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PathList } from "@/components/settings/PathList";
import { PathAddDialog } from "@/components/settings/PathAddDialog";
import { ModelPackCard } from "@/components/settings/ModelPackCard";
import { PwaSettingsCard } from "@/components/settings/PwaSettingsCard";
import { Button } from "@/components/ui/button";
import { useReadyQuery, useStartScanMutation } from "@/lib/api/hooks";
import { toast } from "@/lib/toast";
import { Skeleton } from "@/components/ui/skeleton";

export function SettingsPage(): React.JSX.Element {
  const [addOpen, setAddOpen] = useState(false);
  const startScan = useStartScanMutation();
  const { data: ready } = useReadyQuery();

  // One-time toast on mount when the active pack is NC-research and
  // the user hasn't acknowledged the gate — silent re-mount shouldn't
  // re-fire it.
  const warnedRef = useRef(false);
  useEffect(() => {
    if (warnedRef.current) return;
    if (!ready?.active_pack) return;
    const pack = ready.active_pack;
    if (pack.license_class === "nc-research" && !pack.nc_research_acknowledged) {
      warnedRef.current = true;
      toast.warning(
        `${pack.id} is non-commercial-research licensed.`,
        {
          description:
            "Set [runtime] accept_noncommercial_model_license = true in pick-face.toml, then restart.",
          duration: 0,
        },
      );
    }
  }, [ready?.active_pack]);

  return (
    <div className="container mx-auto p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage scan paths, scans, and the active model pack.
        </p>
      </header>

      <Tabs defaultValue="paths" className="space-y-4">
        <TabsList>
          <TabsTrigger value="paths">Paths</TabsTrigger>
          <TabsTrigger value="scan">Scan</TabsTrigger>
          <TabsTrigger value="model">Model</TabsTrigger>
          <TabsTrigger value="app">App</TabsTrigger>
        </TabsList>

        <TabsContent value="paths" className="space-y-4">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle>Whitelisted paths</CardTitle>
                <CardDescription>
                  Directories the scanner is allowed to read. Photos outside
                  these roots cannot be served.
                </CardDescription>
              </div>
              <Button onClick={() => setAddOpen(true)} data-testid="add-path-button">
                Add path
              </Button>
            </CardHeader>
            <CardContent>
              <PathList />
            </CardContent>
          </Card>
          <PathAddDialog open={addOpen} onOpenChange={setAddOpen} />
        </TabsContent>

        <TabsContent value="scan" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Run a scan</CardTitle>
              <CardDescription>
                Incremental scans re-process only changed files; full scans
                re-process everything in the whitelist.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button
                onClick={() =>
                  startScan.mutate("incremental", {
                    onError: (e) => toast.fromError(e, "Could not start scan"),
                  })
                }
                disabled={startScan.isPending}
              >
                Start incremental scan
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  startScan.mutate("full", {
                    onError: (e) => toast.fromError(e, "Could not start scan"),
                  })
                }
                disabled={startScan.isPending}
              >
                Start full scan
              </Button>
              {startScan.isSuccess && (
                <span className="ml-2 self-center text-sm text-muted-foreground">
                  Job {startScan.data.id} enqueued — see banner above.
                </span>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>App status</CardTitle>
            </CardHeader>
            <CardContent>
              {ready ? (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">Status</dt>
                  <dd>{ready.status}</dd>
                  <dt className="text-muted-foreground">Data dir</dt>
                  <dd className="font-mono">{ready.data_dir ?? "—"}</dd>
                  <dt className="text-muted-foreground">Jobs</dt>
                  <dd>{ready.jobs ?? 0}</dd>
                </dl>
              ) : (
                <Skeleton className="h-16 w-full" />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="model" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Active model pack</CardTitle>
              <CardDescription>
                The detector + embedder used for scans. Change with
                <code className="mx-1 rounded bg-muted px-1.5 py-0.5 text-xs">
                  pick-face init-models --pack &lt;id&gt;
                </code>
                from the CLI; restart the service afterwards.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ModelPackCard pack={ready?.active_pack ?? null} isLoading={!ready} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="app" className="space-y-4">
          <PwaSettingsCard />
        </TabsContent>
      </Tabs>
    </div>
  );
}