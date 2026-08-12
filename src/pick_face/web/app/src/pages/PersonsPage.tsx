// PersonsPage — virtual-album waterfall (M6-T-13).
//
// Renders one `<PersonCard>` per cluster, sorted by face count desc.
// Each card links to /persons/:id. Loading state uses `<Skeleton>` cards.

import * as React from "react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePersonsQuery } from "@/lib/api/hooks";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/cn";

function PersonCard({
  id,
  name,
  photoCount,
}: {
  id: number;
  name: string | null;
  photoCount: number;
}): React.JSX.Element {
  return (
    <Link to={`/persons/${id}`} className="block group">
      <Card className="overflow-hidden transition-shadow hover:shadow-md">
        <div className="relative aspect-square w-full overflow-hidden bg-muted">
          {/* Cover face chip — falls back to thumb via /api/persons/{id}/cover
              (112×112 face crop). When M7.5 adds face bbox data we can
              composite the bbox over the photo; for M7 it's just the cover. */}
          <img
            src={api.getPersonCoverUrl(id)}
            alt={name ?? `Person ${id}`}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
            onError={(e) => {
              // Cover endpoint may 404 if cover_face_id is null. Hide broken img.
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
        <CardHeader className="p-3">
          <h3 className={cn("truncate text-sm font-medium")}>
            {name ?? `Person ${id}`}
          </h3>
          <p className="text-xs text-muted-foreground">
            {photoCount} {photoCount === 1 ? "photo" : "photos"}
          </p>
        </CardHeader>
        <CardContent className="p-3 pt-0" />
      </Card>
    </Link>
  );
}

function PersonCardSkeleton(): React.JSX.Element {
  return (
    <Card className="overflow-hidden">
      <Skeleton className="aspect-square w-full" />
      <div className="space-y-2 p-3">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </Card>
  );
}

export function PersonsPage(): React.JSX.Element {
  const { data, isLoading, isError, error } = usePersonsQuery(100);
  const persons = data?.persons ?? [];
  const sorted = [...persons].sort((a, b) => b.photo_count - a.photo_count);

  return (
    <div className="container mx-auto p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Persons</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {isLoading
            ? "Loading…"
            : `${sorted.length} ${sorted.length === 1 ? "person" : "persons"} detected`}
        </p>
      </header>

      {isError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load: {error instanceof Error ? error.message : "unknown error"}
        </div>
      )}

      {!isError && (
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}
          data-testid="persons-grid"
        >
          {isLoading
            ? Array.from({ length: 12 }).map((_, i) => <PersonCardSkeleton key={i} />)
            : sorted.map((p) => (
                <PersonCard
                  key={p.id}
                  id={p.id}
                  name={p.name}
                  photoCount={p.photo_count}
                />
              ))}
        </div>
      )}
    </div>
  );
}