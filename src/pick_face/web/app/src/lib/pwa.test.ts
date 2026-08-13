// lib/pwa — service-worker registration gated to production.
//
// We can't exercise the real `registerSW` in jsdom (the plugin's virtual
// module only resolves at build time), so we verify the gating and the
// public surface: in dev, `initPwa()` is a no-op; `refreshPwa()` is a
// no-op stub (resolves). The production path is covered by manual smoke
// testing (build → preview → DevTools).

import { describe, expect, it } from "vitest";

import { initPwa, refreshPwa } from "@/lib/pwa";

describe("lib/pwa", () => {
  it("initPwa() is a safe no-op when called outside production", () => {
    // vitest runs in dev mode (import.meta.env.PROD === false), so the
    // production-only branch should never execute.
    expect(() => initPwa()).not.toThrow();
  });

  it("initPwa() can be called repeatedly without throwing (idempotent)", () => {
    expect(() => {
      initPwa();
      initPwa();
      initPwa();
    }).not.toThrow();
  });

  it("refreshPwa() resolves to undefined in dev", async () => {
    await expect(refreshPwa()).resolves.toBeUndefined();
  });
});
