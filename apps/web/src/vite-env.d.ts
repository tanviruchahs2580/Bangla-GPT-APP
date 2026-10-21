/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  // Client telemetry (AUD-HI-07): both optional; telemetry stays off without
  // a DSN regardless of consent, and without a release the tag is absent.
  readonly VITE_SENTRY_DSN?: string;
  readonly VITE_RELEASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.css?raw" {
  const content: string;
  export default content;
}

// vitest reads the stylesheet source for the print-CSS check
declare module "node:fs" {
  export function readFileSync(path: string, encoding: string): string;
}
