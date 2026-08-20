import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "node:path";

// pick-face v3.0 Web SPA — Vite config.
//
// `base: '/'` is hard-coded: FastAPI mounts the static bundle at `/`, and
// sub-path reverse-proxy support is deferred to M10 (deployment milestone).
//
// `build.outDir = '../static'`: vite writes the built index.html + assets/
// directly into the directory that `src/pick_face/api/app.py:84-92` mounts
// at `/`. No copy step in CI; just `pnpm build` then `uv build`.
//
// `server.proxy['/api']` lets `pnpm dev` proxy API calls to a FastAPI
// process running on :8000. Set `VITE_API_BASE=http://localhost:8000/api`
// in `.env.local` instead if you hit SSE buffering through the proxy.
//
// M7.9 — VitePWA wiring. We serve `public/manifest.webmanifest` directly
// (manifest: false) and let Workbox generate `sw.js` + `registerSW.js`.
// `registerType: 'prompt'` keeps SW updates user-controlled — `lib/pwa.ts`
// surfaces a toast with a Reload action rather than auto-reloading.
// `devOptions.enabled: false` so `pnpm dev` doesn't ship a half-built SW.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      injectRegister: "script",
      devOptions: { enabled: false },
      manifest: false,
      filename: "sw.js",
      manifestFilename: "manifest.webmanifest",
      strategies: "generateSW",
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest}"],
        cleanupOutdatedCaches: true,
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        // Don't pre-cache HTML at navigation time — `navigateFallback` does
        // it on-demand. Keeping the runtime cache list narrow lets us audit
        // exactly which endpoints are eligible for offline reuse.
        runtimeCaching: [
          {
            // Face thumbnails — small, reused across the waterfall and the
            // viewer. CacheFirst with a 30-day TTL. Cap at 256 entries so a
            // runaway library doesn't fill the disk.
            urlPattern: ({ url }) =>
              url.pathname.startsWith("/api/photos/") &&
              /\/thumb\/?$/.test(url.pathname),
            handler: "CacheFirst",
            options: {
              cacheName: "pickface-thumbs",
              expiration: {
                maxEntries: 256,
                maxAgeSeconds: 30 * 24 * 3600,
              },
              cacheableResponse: { statuses: [0, 200] },
              matchOptions: { ignoreVary: true },
            },
          },
          {
            // Person list + per-person photo list. Small JSON, frequently
            // re-fetched; SWR keeps the waterfall snappy on revisit while
            // still pulling a fresh page in the background.
            urlPattern: ({ url }) =>
              url.pathname === "/api/persons" ||
              /^\/api\/persons\/[^/]+\/photos\/?$/.test(url.pathname),
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "pickface-lists",
              expiration: { maxEntries: 32, maxAgeSeconds: 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          // Deliberately NOT cached:
          //   /api/photos/{id}            — original image; served via
          //                                 Range, Workbox's default
          //                                 RangeRequestsPlugin keeps
          //                                 partial fetches correct.
          //   /api/scan/jobs/{id}/events  — SSE must never hit cache.
        ],
      },
    }),
  ],
  base: "/",
  build: {
    outDir: path.resolve(__dirname, "../pick-face/src/pick_face/web/static"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
