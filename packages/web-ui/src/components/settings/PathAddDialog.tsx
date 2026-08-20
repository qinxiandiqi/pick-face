// PathAddDialog — shadcn Dialog + react-hook-form + zod.
//
// zod schema mirrors the server's Pydantic validation in
// `src/pick_face/api/config.py:60-90`. We also call `addPath()` which
// will throw ApiError(404/403/409) on the same conditions server-side,
// surfaced as form errors via react-hook-form's setError.
//
// Picking a directory — browser sandbox limitation:
//
//   The form asks for an *absolute* path because the backend whitelist
//   needs one to walk. Browsers cannot (for security reasons) expose
//   the absolute filesystem path of a user-picked folder to a web page
//   on Chromium / Safari / Edge. Firefox is the one exception: since
//   v49 it exposes `File.path` on files returned by `<input
//   webkitdirectory>`. Everywhere else, the best the picker can hand
//   us is the picked directory's *name* — we pre-fill it and surface
//   a hint so the user knows to add the parent path manually.

import * as React from "react";
import { useRef, useState } from "react";
import { FolderOpen } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { useAddPathMutation } from "@/lib/api/hooks";

// Client-side mirror of the server's validation rules. The server
// enforces these authoritatively; we duplicate them here for nicer UX.
const schema = z.object({
  path: z
    .string()
    .min(1, "Path is required")
    .refine((v) => v.trim().length > 0, "Path cannot be blank"),
  notes: z.string().optional(),
});

type FormData = z.infer<typeof schema>;

/** Best-effort: extract an absolute-path-shaped string from a picked file.
 *
 *  Order of preference (browsers vary):
 *   1. `file.path` — Firefox-only non-standard property; gives the
 *      absolute path on disk. When present, the picker has done the
 *      whole job.
 *   2. `webkitRelativePath.split('/')[0]` — the picked directory's
 *      name. Available on every browser that supports
 *      ``<input webkitdirectory>``. We prefix with ``/`` so the
 *      placeholder makes it obvious this is just the leaf and the
 *      parent still needs typing.
 *
 *  Returns ``{ value, complete }`` so the caller can warn when only
 *  the name was recovered.
 */
function extractPickedPath(file: File): { value: string; complete: boolean } {
  const f = file as File & { path?: string };
  if (f.path && f.path.length > 0) {
    return { value: f.path, complete: true };
  }
  const rel = file.webkitRelativePath || "";
  const leaf = rel.split("/")[0] || file.name;
  return { value: leaf, complete: false };
}

export function PathAddDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}): React.JSX.Element {
  const addPath = useAddPathMutation();
  const dirPickerRef = useRef<HTMLInputElement>(null);
  // null = user hasn't picked anything yet, "complete" = absolute path
  // recovered, "name-only" = browser only gave us the directory name.
  const [pickerHint, setPickerHint] = useState<"none" | "complete" | "name-only">(
    "none",
  );

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { path: "", notes: "" },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      await addPath.mutateAsync({
        path: data.path.trim(),
        notes: data.notes || undefined,
        enabled: true,
      });
      reset();
      setPickerHint("none");
      onOpenChange(false);
    } catch (e) {
      if (e instanceof ApiError) {
        // Map known server error codes to form-level errors.
        const map: Record<string, string> = {
          NOT_A_DIRECTORY: "That path is not a directory.",
          NOT_READABLE: "That directory is not readable.",
          PATH_TRAVERSAL: "That path is not allowed (contains '..').",
          DUPLICATE: "That path is already whitelisted.",
        };
        setError("path", {
          message: map[e.code] ?? e.message,
        });
      } else if (e instanceof Error) {
        setError("path", { message: e.message });
      }
    }
  });

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      reset();
      setPickerHint("none");
      // Clear the file input so re-opening lets the user pick the
      // same folder again.
      if (dirPickerRef.current) dirPickerRef.current.value = "";
    }
    onOpenChange(next);
  };

  const onPickDirectory = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const { value, complete } = extractPickedPath(files[0]);
    setValue("path", value, {
      shouldValidate: true,
      shouldDirty: true,
    });
    setPickerHint(complete ? "complete" : "name-only");
    // Move the keyboard cursor into the input so the user can edit
    // the prefilled value immediately (especially when only the leaf
    // name was recoverable and they need to type the parent).
    document.getElementById("path")?.focus();
  };

  // Feature detection: webkitdirectory works in every modern browser,
  // but ``window.showDirectoryPicker`` (File System Access API) is
  // Chromium-only and gives a *handle*, not a path — same problem.
  // Stay with the universal input.
  const supportsDirectoryPicker = (() => {
    if (typeof document === "undefined") return false;
    const probe = document.createElement("input");
    // Both legacy ``webkitdirectory`` and standard ``directory`` (used
    // by Chromium 86+) gate the feature; either being truthy means
    // the browser will show a folder picker.
    return "webkitdirectory" in probe || "directory" in probe;
  })();

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add scan path</DialogTitle>
          <DialogDescription>
            Whitelist an absolute directory. Photos outside whitelisted paths
            cannot be served by the API.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4" data-testid="add-path-form">
          <div className="space-y-2">
            <Label htmlFor="path">Absolute path</Label>
            <div className="flex gap-2">
              <Input
                id="path"
                placeholder="/mnt/photos/2024"
                autoComplete="off"
                autoFocus
                aria-invalid={!!errors.path}
                data-testid="add-path-input"
                {...register("path")}
                className="flex-1"
              />
              {supportsDirectoryPicker && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => dirPickerRef.current?.click()}
                    data-testid="browse-directory-button"
                  >
                    <FolderOpen className="mr-2 h-4 w-4" aria-hidden />
                    Browse
                  </Button>
                  {/* Hidden webkitdirectory input — clicking the
                      visible button above delegates here. We accept
                      the ``path`` non-standard property on the picked
                      ``File`` (Firefox) and fall back to the leaf
                      directory name everywhere else. */}
                  <input
                    ref={dirPickerRef}
                    type="file"
                    // Standard ``directory`` plus the legacy
                    // ``webkitdirectory`` keeps both Firefox and
                    // Chromium happy.
                    {...({ webkitdirectory: "", directory: "" } as Record<
                      string,
                      string
                    >)}
                    multiple={false}
                    className="hidden"
                    onChange={onPickDirectory}
                    data-testid="directory-picker-input"
                  />
                </>
              )}
            </div>
            {pickerHint === "name-only" && (
              <p className="text-xs text-muted-foreground" data-testid="picker-hint">
                Browser only exposed the directory name. Add the parent path
                above before submitting (e.g. <code>C:\Users\me\Pictures</code>).
              </p>
            )}
            {pickerHint === "complete" && (
              <p className="text-xs text-muted-foreground" data-testid="picker-hint">
                Picked from system folder picker — confirm the path before
                submitting.
              </p>
            )}
            {errors.path && (
              <p className="text-sm text-destructive" role="alert">
                {errors.path.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">Notes (optional)</Label>
            <Input
              id="notes"
              placeholder="e.g. 2024 vacation"
              autoComplete="off"
              {...register("notes")}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Adding…" : "Add path"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}