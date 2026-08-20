// Test setup: jsdom-friendly matchers + auto-cleanup for React Testing
// Library. Loaded by vitest.config.ts → setupFiles.
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom doesn't ship `navigator.serviceWorker` or `window.matchMedia`.
// The PWA tests (`InstallAppButton.test.tsx`, `PwaSettingsCard.test.tsx`,
// `lib/pwa.test.ts`) need both, so we stub the minimum viable surface.
// Real browsers always supply these; the stub only affects unit tests.

if (typeof navigator !== "undefined" && !("serviceWorker" in navigator)) {
  Object.defineProperty(navigator, "serviceWorker", {
    value: {
      register: vi.fn().mockResolvedValue({
        update: vi.fn(),
        unregister: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      controller: null,
      ready: Promise.resolve({} as unknown as ServiceWorkerRegistration),
    },
    configurable: true,
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});