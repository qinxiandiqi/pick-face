// PWA registration — single side-effect module loaded from main.tsx.
//
// `vite-plugin-pwa` generates `sw.js` + `registerSW.js` at build time.
// We use `registerType: 'prompt'` (see vite.config.ts) which means the
// plugin emits an `update` function we can call manually instead of
// forcing a hard reload.
//
// Two entry points:
//   - `initPwa()`  — call once at boot. Wires `onNeedRefresh` (toast with
//                    Reload action) and `onOfflineReady` (one-shot
//                    success toast). Gated to production — `pnpm dev`
//                    never registers a service worker.
//   - `refreshPwa()` — check for an update without reloading. Used by
//                      the "Check for update" button on Settings → App.

import { registerSW } from "virtual:pwa-register";

import { toast } from "@/lib/toast";

// `updateSW(true)` reloads the page after applying a new SW; `updateSW(false)`
// only checks + applies without reloading. We hoist it so the toast's Reload
// action can capture it via closure.
let updateSW: (reload?: boolean) => Promise<void> = async () => undefined;

let initialized = false;

export function initPwa(): void {
  if (initialized) return;
  initialized = true;

  if (!import.meta.env.PROD) return;

  // `immediate: true` registers the SW as soon as this module loads rather
  // than waiting for `window.load`. Production-only by the gating above.
  //
  // `registerSW` returns the update function directly (not a Promise of
  // one). We assign it to the hoisted `updateSW` so the toast's Reload
  // action can capture it via closure.
  try {
    updateSW = registerSW({
      immediate: true,
      onNeedRefresh() {
        toast.info("New version available", {
          description: "Reload to update pick-face.",
          duration: 0,
          action: {
            label: "Reload",
            onClick: () => {
              void updateSW(true);
            },
          },
        });
      },
      onOfflineReady() {
        toast.success("Ready to work offline", {
          description: "App shell and recent thumbnails are cached.",
        });
      },
    });
  } catch {
    // SW registration can throw in private modes, on broken proxies, or in
    // iframes with restrictive sandbox flags. Fail silent — the SPA still
    // works without offline / install support.
  }
}

export async function refreshPwa(): Promise<void> {
  // In dev this is a no-op (updateSW is the stub defined above); in prod
  // `false` means "check + apply, but don't reload the page".
  await updateSW(false);
}
