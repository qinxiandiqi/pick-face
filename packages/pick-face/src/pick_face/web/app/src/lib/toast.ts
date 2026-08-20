// toast — typed facade over sonner.
//
// Why: we want every user-facing error in the SPA to flow through one
// entry point so we can later swap the underlying toaster library
// without grepping the codebase, and so we can produce user copy that
// is consistent across mutation sites (e.g. always include the API
// error code as a secondary line).
//
// Import rule: **no other component may import from "sonner"** —
// always import from "@/lib/toast". Sonner is an implementation detail
// of this module.

import { toast as sonnerToast } from "sonner";

import { ApiError } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Defaults — keep these aligned with the SonnerToaster in toaster.tsx so a
// user can read either in-flight toasts and the post-load ones identically.
// ---------------------------------------------------------------------------

const DEFAULT_SUCCESS_MS = 4_000;
const DEFAULT_ERROR_MS = 6_000;

// ---------------------------------------------------------------------------
// Public surface — drop-in replacement for the sonner API.
// ---------------------------------------------------------------------------

export interface ToastAction {
  /** Short label rendered as a button inside the toast. */
  label: string;
  /** Click handler. Keep it side-effect-only — sonner does not await it. */
  onClick: () => void;
}

export interface ToastOptions {
  /** Optional secondary line shown below the title. */
  description?: string;
  /** Override the auto-dismiss timer (ms). 0 disables auto-dismiss. */
  duration?: number;
  /**
   * Optional inline action button (e.g. "Reload" for service-worker
   * updates). Sonner renders this as a tappable button at the right of
   * the toast. The toast itself does NOT auto-dismiss when the action is
   * clicked — call sites are responsible for follow-up UX.
   */
  action?: ToastAction;
}

/** Success toast — operation completed. Defaults to 4s dismiss. */
export function success(message: string, opts: ToastOptions = {}): void {
  sonnerToast.success(message, {
    description: opts.description,
    duration: opts.duration ?? DEFAULT_SUCCESS_MS,
    action: opts.action,
  });
}

/** Error toast — operation failed but the user can continue. Defaults to 6s. */
export function error(message: string, opts: ToastOptions = {}): void {
  sonnerToast.error(message, {
    description: opts.description,
    duration: opts.duration ?? DEFAULT_ERROR_MS,
    action: opts.action,
  });
}

/** Informational toast — passive hint to the user. */
export function info(message: string, opts: ToastOptions = {}): void {
  sonnerToast(message, {
    description: opts.description,
    duration: opts.duration ?? DEFAULT_SUCCESS_MS,
    action: opts.action,
  });
}

/** Warning toast — softer than `error`, often used for non-blocking issues. */
export function warning(message: string, opts: ToastOptions = {}): void {
  sonnerToast.warning(message, {
    description: opts.description,
    duration: opts.duration ?? DEFAULT_ERROR_MS,
    action: opts.action,
  });
}

/** Narrow an arbitrary thrown value into a user-facing error toast. */
export function fromError(err: unknown, fallback = "Something went wrong"): void {
  if (err instanceof ApiError) {
    // The server already produced a human-readable message; surface the
    // machine-readable `code` as a secondary line for support / triage.
    error(err.message, {
      description: `code: ${err.code}`,
      // Keep the toast sticky on 5xx — the user probably needs to retry.
      duration: err.status >= 500 ? 0 : DEFAULT_ERROR_MS,
    });
    return;
  }
  if (err instanceof Error) {
    error(err.message || fallback);
    return;
  }
  error(fallback);
}

// The `toast` object form mirrors the sonner API for ergonomic swap-ins:
//   toast.success(...) → success(...)
//   toast.error(...)   → error(...)
//   toast.fromError(...) → fromError(...)
//   toast.info(...)    → info(...)
//   toast.warning(...) → warning(...)
// Keeping it as a const lets callers keep `toast.success(...)` style if
// they already wrote it that way; we don't need to migrate them.
export const toast = {
  success,
  error,
  info,
  warning,
  fromError,
};

export type { ApiError };