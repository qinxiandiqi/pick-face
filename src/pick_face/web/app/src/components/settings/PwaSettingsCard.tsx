// PwaSettingsCard — Settings → App tab content (M7-T-9).
//
// Two affordances:
//   1. <InstallAppButton> — the explicit, user-initiated install path.
//      Renders nothing unless `beforeinstallprompt` has fired.
//   2. "Check for update" — triggers `lib/pwa.refreshPwa()`. Useful when
//      the user has been on the page for a while and the SW auto-update
//      check (typically every 24h) hasn't run yet.

import * as React from "react";
import { useState } from "react";
import { RefreshCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { refreshPwa } from "@/lib/pwa";
import { InstallAppButton } from "@/components/settings/InstallAppButton";

export function PwaSettingsCard(): React.JSX.Element {
  const [checking, setChecking] = useState(false);

  async function handleCheck(): Promise<void> {
    setChecking(true);
    try {
      await refreshPwa();
    } finally {
      setChecking(false);
    }
  }

  return (
    <Card data-testid="pwa-settings-card">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>App</CardTitle>
          <Badge variant="outline" data-testid="pwa-install-state">
            PWA
          </Badge>
        </div>
        <CardDescription>
          Install pick-face as a standalone app on this device, or check
          for a newer version without reloading the page.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        <InstallAppButton />
        <Button
          variant="outline"
          onClick={handleCheck}
          disabled={checking}
          className="gap-2"
          data-testid="check-update-button"
        >
          <RefreshCcw className="h-4 w-4" aria-hidden />
          {checking ? "Checking…" : "Check for update"}
        </Button>
      </CardContent>
    </Card>
  );
}
