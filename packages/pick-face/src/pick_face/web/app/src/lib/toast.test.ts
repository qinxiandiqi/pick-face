// toast — verify the typed facade narrows thrown values into the right
// sonner calls. We mock "sonner" so we can assert without rendering the
// Toaster. M7-T-11.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  });
  return { toast };
});

import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import * as sonner from "sonner";

const sonnerError = sonner.toast.error as unknown as ReturnType<typeof vi.fn>;
const sonnerSuccess = sonner.toast.success as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  sonnerError.mockClear();
  sonnerSuccess.mockClear();
});

describe("toast facade", () => {
  describe("fromError", () => {
    it("surfaces ApiError's message as title and code as description", () => {
      const e = new ApiError(409, {
        code: "DUPLICATE",
        message: "That path is already whitelisted.",
      });
      toast.fromError(e);
      expect(sonnerError).toHaveBeenCalledTimes(1);
      const [message, opts] = sonnerError.mock.calls[0] as [string, Record<string, unknown>];
      expect(message).toBe("That path is already whitelisted.");
      expect(opts.description).toBe("code: DUPLICATE");
      // 4xx is dismissable, not sticky.
      expect(opts.duration).toBe(6_000);
    });

    it("sticks 5xx errors so the user has time to retry", () => {
      const e = new ApiError(500, {
        code: "INTERNAL",
        message: "Internal server error",
      });
      toast.fromError(e);
      const [, opts] = sonnerError.mock.calls[0] as [string, Record<string, unknown>];
      expect(opts.duration).toBe(0);
    });

    it("falls back to err.message for plain Error", () => {
      toast.fromError(new Error("boom"));
      const [message, opts] = sonnerError.mock.calls[0] as [string, Record<string, unknown>];
      expect(message).toBe("boom");
      // No description for plain Error — only ApiError gets the code line.
      expect(opts.description).toBeUndefined();
    });

    it("falls back to the default message for unknown thrown values", () => {
      toast.fromError("string thrown");
      const [message] = sonnerError.mock.calls[0] as [string];
      expect(message).toBe("Something went wrong");
    });

    it("honors a custom fallback", () => {
      toast.fromError(undefined, "Scan could not start");
      const [message] = sonnerError.mock.calls[0] as [string];
      expect(message).toBe("Scan could not start");
    });

    it("uses err.message when present even if empty string is in fallback", () => {
      toast.fromError(new Error(""), "fallback");
      const [message] = sonnerError.mock.calls[0] as [string];
      expect(message).toBe("fallback");
    });
  });

  describe("direct helpers", () => {
    it("success() forwards message and short duration", () => {
      toast.success("done");
      const [message, opts] = sonnerSuccess.mock.calls[0] as [string, Record<string, unknown>];
      expect(message).toBe("done");
      expect(opts.duration).toBe(4_000);
    });

    it("error() forwards message and long duration", () => {
      toast.error("nope");
      const [, opts] = sonnerError.mock.calls[0] as [string, Record<string, unknown>];
      expect(opts.duration).toBe(6_000);
    });
  });
});