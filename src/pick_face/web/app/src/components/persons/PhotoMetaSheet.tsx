// PhotoMetaSheet — right-side drawer showing extended photo metadata
// (M7-T-8). Triggered by an info button on the photo card or inside the
// viewer. Reads from /api/photos/{id}/meta (extended M7.5 response).
//
// Sections:
//   - Identity: id, path, mtime, size, hash.
//   - Faces: list of detected faces with cluster_id, bbox, det_score,
//     quality. Empty state: "No faces detected — run a scan."
//
// EXIF (camera make/model, exposure, GPS) is intentionally NOT here yet:
// the backend endpoint doesn't expose it. When M7.5's photo metadata
// extension adds EXIF (separate PR), this drawer gains a "Camera" section.

import * as React from "react";
import { FileText, Image as ImageIcon, MapPin, ScanLine } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { usePhotoMetadataQuery } from "@/lib/api/hooks";

export interface PhotoMetaSheetProps {
  photoId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PhotoMetaSheet({
  photoId,
  open,
  onOpenChange,
}: PhotoMetaSheetProps): React.JSX.Element {
  const { data, isLoading, isError } = usePhotoMetadataQuery(
    open ? photoId : null,
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="overflow-y-auto"
        data-testid="photo-meta-sheet"
      >
        <SheetHeader className="pb-4">
          <SheetTitle>Photo details</SheetTitle>
          <SheetDescription>
            Extended metadata fetched from the server.
          </SheetDescription>
        </SheetHeader>

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}

        {isError && (
          <p className="text-sm text-destructive">
            Failed to load metadata. Try again.
          </p>
        )}

        {data && (
          <div className="space-y-6">
            <section>
              <SectionHeader icon={FileText}>Identity</SectionHeader>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">ID</dt>
                <dd className="font-mono">{data.id}</dd>
                <dt className="text-muted-foreground">Path</dt>
                <dd className="break-all font-mono text-xs">{data.path}</dd>
                <dt className="text-muted-foreground">Modified</dt>
                <dd>{formatMtime(data.mtime)}</dd>
                <dt className="text-muted-foreground">Size</dt>
                <dd>{formatBytes(data.size)}</dd>
                <dt className="text-muted-foreground">Content hash</dt>
                <dd className="font-mono text-xs">{data.content_hash}</dd>
              </dl>
            </section>

            <section>
              <SectionHeader icon={ImageIcon}>Image</SectionHeader>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Dimensions</dt>
                <dd>
                  {data.natural_width ?? "?"} × {data.natural_height ?? "?"} px
                </dd>
              </dl>
            </section>

            <section>
              <SectionHeader icon={ScanLine}>
                Faces ({data.faces.length})
              </SectionHeader>
              {data.faces.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No faces detected. Run a scan to populate.
                </p>
              ) : (
                <ul className="space-y-2 text-sm" data-testid="meta-faces-list">
                  {data.faces.map((f) => (
                    <li
                      key={f.id}
                      className="rounded-md border bg-muted/30 p-2 font-mono text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <span>face #{f.id}</span>
                        <span className="text-muted-foreground">
                          cluster: {f.cluster_id ?? "—"}
                        </span>
                      </div>
                      {f.bbox && (
                        <div className="text-muted-foreground">
                          bbox [{f.bbox.map((n) => n.toFixed(1)).join(", ")}]
                        </div>
                      )}
                      <div className="text-muted-foreground">
                        det={f.det_score?.toFixed(2) ?? "—"} • q=
                        {f.quality?.toFixed(2) ?? "—"}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <SectionHeader icon={MapPin}>EXIF</SectionHeader>
              <p className="text-sm text-muted-foreground">
                Camera / GPS / exposure data isn't surfaced yet — backend
                extension lands in a follow-up PR.
              </p>
            </section>
          </div>
        )}

        <div className="mt-6 flex justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function SectionHeader({
  icon: Icon,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
      <Icon className="h-3.5 w-3.5" />
      {children}
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatMtime(epoch: number): string {
  if (!epoch) return "—";
  try {
    const d = new Date(epoch * 1000);
    return d.toLocaleString();
  } catch {
    return String(epoch);
  }
}
