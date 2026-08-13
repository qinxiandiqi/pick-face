// vitest config — separate from vite.config.ts so the build doesn't
// require vitest types at compile time.

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The VitePWA virtual module (`virtual:pwa-register`) only resolves when
// the VitePWA plugin runs at build time. Vitest doesn't drive that plugin
// pipeline, so we alias the virtual specifier to a tiny stub that satisfies
// the type and exposes a no-op `registerSW`. Production paths are exercised
// in `pnpm preview` + manual smoke, not vitest.

const pwaRegisterStub = path.resolve(__dirname, "src/test-shims/pwa-register.ts");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "virtual:pwa-register": pwaRegisterStub,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
