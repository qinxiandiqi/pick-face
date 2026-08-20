// Vitest shim for the `virtual:pwa-register` module that vite-plugin-pwa
// injects at build time. Vitest doesn't drive the plugin pipeline, so we
// point the virtual specifier at this file via `vitest.config.ts` alias.
// Production behaviour is exercised in `pnpm preview` + manual smoke.

export interface RegisterSWOptions {
  immediate?: boolean;
  onNeedRefresh?: () => void;
  onOfflineReady?: () => void;
  onRegistered?: (registration: ServiceWorkerRegistration | undefined) => void;
  onRegisterError?: (error: unknown) => void;
}

export type UpdateSW = (reloadPage?: boolean) => Promise<void>;

export function registerSW(_options: RegisterSWOptions = {}): UpdateSW {
  // The real module returns an `updateSW(reload?)` function. In tests we
  // never register a SW anyway (the production gating in `lib/pwa.ts`
  // early-returns), so the stub satisfies the type without doing anything.
  return async () => undefined;
}
