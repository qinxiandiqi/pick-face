// SettingsPage — three tabs (M6-T-12).
//
// Paths  : whitelist CRUD via PathList + PathAddDialog (rhf + zod).
// Scan   : start a new scan, view job status. Real SSE progress lives in
//          the global ScanProgressBanner (rendered by AppShell).
// Model  : placeholder card listing the active pack from /api/health.
//          NC-research Badge (M7-T-13) deferred to M7.5.

import * as React from "react";
import { useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PathList } from "@/components/settings/PathList";
import { PathAddDialog } from "@/components/settings/PathAddDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useReadyQuery, useStartScanMutation } from "@/lib/api/hooks";
import { Skeleton } from "@/components/ui/skeleton";

export function SettingsPage(): React.JSX.Element {
  const [addOpen, setAddOpen] = useState(false);
  const startScan = useStartScanMutation();
  const { data: ready } = useReadyQuery();

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
                onClick={() => startScan.mutate("incremental")}
                disabled={startScan.isPending}
              >
                Start incremental scan
              </Button>
              <Button
                variant="outline"
                onClick={() => startScan.mutate("full")}
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
            <CardContent className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">yunet-sface</Badge>
              <span className="text-sm text-muted-foreground">
                MIT · 128-D · Pi 3B friendly (M7.5: NC-research Badge here)
              </span>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}