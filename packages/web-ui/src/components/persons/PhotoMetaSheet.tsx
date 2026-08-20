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
import type { Exif } from "@/lib/api/schemas";

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
              {hasAnyExif(data.exif) ? (
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
                  {(data.exif.make || data.exif.model || data.exif.lens) && (
                    <>
                      <dt className="text-muted-foreground">Camera</dt>
                      <dd>
                        {[data.exif.make, data.exif.model].filter(Boolean).join(" ") || "—"}
                        {data.exif.lens ? (
                          <span className="block text-xs text-muted-foreground">
                            {data.exif.lens}
                          </span>
                        ) : null}
                      </dd>
                    </>
                  )}
                  {data.exif.taken_at !== null && (
                    <>
                      <dt className="text-muted-foreground">Taken</dt>
                      <dd>{formatTakenAt(data.exif.taken_at)}</dd>
                    </>
                  )}
                  {hasExposure(data.exif) && (
                    <>
                      <dt className="text-muted-foreground">Exposure</dt>
                      <dd>{formatExposure(data.exif)}</dd>
                    </>
                  )}
                  {data.exif.gps_lat !== null && data.exif.gps_lon !== null && (
                    <>
                      <dt className="text-muted-foreground">GPS</dt>
                      <dd className="font-mono text-xs">
                        {formatGps(data.exif.gps_lat, data.exif.gps_lon)}
                      </dd>
                    </>
                  )}
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No EXIF tags on this photo (PNG, stripped JPEG, or
                  missing metadata).
                </p>
              )}
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

function hasAnyExif(exif: Exif): boolean {
  return (
    exif.make !== null ||
    exif.model !== null ||
    exif.taken_at !== null ||
    exif.lens !== null ||
    exif.exposure !== null ||
    exif.f_number !== null ||
    exif.iso !== null ||
    exif.focal_length !== null ||
    exif.gps_lat !== null ||
    exif.gps_lon !== null
  );
}

function hasExposure(exif: Exif): boolean {
  return (
    exif.exposure !== null || exif.f_number !== null || exif.iso !== null || exif.focal_length !== null
  );
}

function formatTakenAt(epoch: number): string {
  try {
    return new Date(epoch * 1000).toLocaleString();
  } catch {
    return String(epoch);
  }
}

/** Render exposure as "1/200s • f/2.8 • ISO 400 • 50mm". Missing parts are dropped. */
function formatExposure(exif: Exif): string {
  const parts: string[] = [];
  if (exif.exposure !== null) {
    if (exif.exposure >= 1) {
      parts.push(`${exif.exposure.toFixed(1)}s`);
    } else if (exif.exposure > 0) {
      // 1/200s style
      const denom = Math.round(1 / exif.exposure);
      parts.push(`1/${denom}s`);
    }
  }
  if (exif.f_number !== null) parts.push(`f/${exif.f_number.toFixed(1)}`);
  if (exif.iso !== null) parts.push(`ISO ${exif.iso}`);
  if (exif.focal_length !== null) parts.push(`${Math.round(exif.focal_length)}mm`);
  return parts.join(" • ");
}

function formatGps(lat: number, lon: number): string {
  const fmt = (v: number, positive: string, negative: string) => {
    const abs = Math.abs(v);
    const deg = Math.floor(abs);
    const minFloat = (abs - deg) * 60;
    const min = Math.floor(minFloat);
    const sec = (minFloat - min) * 60;
    return `${deg}°${min}'${sec.toFixed(1)}"${v >= 0 ? positive : negative}`;
  };
  return `${fmt(lat, "N", "S")} ${fmt(lon, "E", "W")}`;
}
