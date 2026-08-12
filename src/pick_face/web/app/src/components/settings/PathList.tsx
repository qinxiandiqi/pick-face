// PathList — table of whitelisted paths with Switch (enable/disable)
// and Delete button (M6-T-12).

import * as React from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useDeletePathMutation,
  usePathsQuery,
  useUpdatePathMutation,
} from "@/lib/api/hooks";

export function PathList(): React.JSX.Element {
  const { data, isLoading, isError, error } = usePathsQuery();
  const updatePath = useUpdatePathMutation();
  const deletePath = useDeletePathMutation();

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-sm text-destructive">
        Failed to load paths: {error instanceof Error ? error.message : "unknown"}
      </p>
    );
  }

  const paths = data?.paths ?? [];
  if (paths.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="paths-empty">
        No paths yet. Click "Add path" to whitelist a directory.
      </p>
    );
  }

  return (
    <ul className="divide-y" data-testid="path-list">
      {paths.map((p) => (
        <li key={p.id} className="flex items-center gap-3 py-3">
          <Switch
            checked={p.enabled}
            disabled={updatePath.isPending}
            onCheckedChange={(enabled) =>
              updatePath.mutate({ id: p.id, data: { enabled } })
            }
            aria-label={`Toggle path ${p.path}`}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-sm">{p.path}</p>
            {p.notes && (
              <p className="truncate text-xs text-muted-foreground">{p.notes}</p>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete path ${p.path}`}
            disabled={deletePath.isPending}
            onClick={() => {
              if (confirm(`Remove ${p.path} from the whitelist?`)) {
                deletePath.mutate(p.id);
              }
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </li>
      ))}
    </ul>
  );
}