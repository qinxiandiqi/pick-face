// PathAddDialog — shadcn Dialog + react-hook-form + zod.
//
// zod schema mirrors the server's Pydantic validation in
// `src/pick_face/api/config.py:60-90`. We also call `addPath()` which
// will throw ApiError(404/403/409) on the same conditions server-side,
// surfaced as form errors via react-hook-form's setError.

import * as React from "react";
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

export function PathAddDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}): React.JSX.Element {
  const addPath = useAddPathMutation();

  const {
    register,
    handleSubmit,
    reset,
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
            <Input
              id="path"
              placeholder="/mnt/photos/2024"
              autoComplete="off"
              autoFocus
              aria-invalid={!!errors.path}
              {...register("path")}
            />
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
              onClick={() => {
                reset();
                onOpenChange(false);
              }}
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