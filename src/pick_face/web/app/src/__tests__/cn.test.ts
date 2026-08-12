// cn() — class-name helper. Trivial tests but guards against drift.

import { describe, expect, it } from "vitest";
import { cn } from "@/lib/cn";

describe("cn", () => {
  it("joins truthy values", () => {
    expect(cn("a", "b", "c")).toBe("a b c");
  });

  it("skips falsy values", () => {
    expect(cn("a", undefined, null, false, "b")).toBe("a b");
  });

  it("deduplicates conflicting tailwind classes", () => {
    // tailwind-merge resolves px-2 px-4 → px-4
    expect(cn("px-2", "px-4")).toBe("px-4");
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
  });

  it("keeps non-conflicting classes", () => {
    expect(cn("text-sm", "font-bold")).toBe("text-sm font-bold");
  });
});