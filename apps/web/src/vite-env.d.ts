/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.css?raw" {
  const content: string;
  export default content;
}

// vitest reads the stylesheet source for the S2.6 print-CSS check
declare module "node:fs" {
  export function readFileSync(path: string, encoding: string): string;
}
