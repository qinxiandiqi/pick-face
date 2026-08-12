import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
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
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: path.resolve(__dirname, "../static"),
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
