// Typed accessor for Vite-injected env vars. Fails loudly at module-load
// time if a required variable is missing — better than discovering it
// three component layers deep.

export const env = {
  /** Base URL for the FastAPI backend (no trailing slash). */
  apiBase: (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/+$/, ""),
  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD,
} as const;