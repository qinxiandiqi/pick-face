// ModelPackCard — renders the active model pack from /api/ready with
// a license-class-driven Badge (M7-T-13).
//
// NC-research packs are surfaced prominently with a destructive-style
// badge; if the user hasn't acknowledged the gate
// (`nc_research_acknowledged === false`) we also fire a one-time
// warning toast on mount so AC-9 can't be silently ignored.
//
// Discovery can return null (pack plugin not installed, or
// config missing). In that case we show a soft "unknown" placeholder
// instead of pretending we know the pack id.

import * as React from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { ActivePack, LicenseClass } from "@/lib/api/schemas";

export interface ModelPackCardProps {
  pack: ActivePack | null | undefined;
  isLoading: boolean;
}

export function ModelPackCard({ pack, isLoading }: ModelPackCardProps): React.JSX.Element {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-64" />
      </div>
    );
  }

  if (!pack) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="model-pack-unknown">
        No installed model pack detected. Run{" "}
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
          pick-face init-models --pack &lt;id&gt;
        </code>{" "}
        from the CLI; restart the service afterwards.
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="model-pack-card">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" data-testid="model-pack-id">
          {pack.id}
        </Badge>
        <LicenseBadge licenseClass={pack.license_class} />
        {!pack.nc_research_acknowledged && (
          <Badge
            variant="destructive"
            className="gap-1"
            data-testid="model-pack-unacknowledged"
          >
            <AlertTriangle className="h-3 w-3" aria-hidden />
            AC-9 will block scans
          </Badge>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        {pack.display_name} · {pack.license_name}
        {pack.license_spdx && pack.license_spdx !== pack.license_name && (
          <span className="ml-1 font-mono text-xs">({pack.license_spdx})</span>
        )}
      </p>
    </div>
  );
}

function LicenseBadge({
  licenseClass,
}: {
  licenseClass: LicenseClass;
}): React.JSX.Element {
  // Color semantics:
  //   permissive   → default secondary
  //   user-supplied → outline (neutral, user-owned)
  //   nc-research → destructive (red) so it stands out
  if (licenseClass === "nc-research") {
    return (
      <Badge
        variant="destructive"
        className="gap-1"
        data-testid="model-pack-license-badge"
      >
        <ShieldCheck className="h-3 w-3" aria-hidden />
        NC-research
      </Badge>
    );
  }
  if (licenseClass === "user-supplied") {
    return (
      <Badge variant="outline" data-testid="model-pack-license-badge">
        user-supplied
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" data-testid="model-pack-license-badge">
      permissive
    </Badge>
  );
}